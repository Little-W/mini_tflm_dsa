#!/usr/bin/env python3
"""验证池化限幅的完整输入数值和四态行为。"""
from concurrent.futures import ThreadPoolExecutor
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--out',type=Path,required=True)
args=parser.parse_args()
OUT=args.out.resolve()
OUT.mkdir(parents=True,exist_ok=True)
REFERENCE_COMMIT='86034eb4'
ORIGINAL_ENGINE=subprocess.check_output(['git','show',REFERENCE_COMMIT+':rtl/npu/conv/vector_engine.sv'],cwd=ROOT,text=True)
CURRENT_ENGINE=(ROOT/'rtl/npu/conv/vector_engine.sv').read_text()
START='  for (genvar lane=0;lane<PE_COUNT;lane++) begin : g_pool_lane_clamp'
END='  for (genvar entry=0;entry<TILE;entry++) begin : g_result_write'
def extract(source):
    first=source.index(START)
    last=source.index(END,first)
    return source[first:last]
def module(source):
    block=extract(source)
    for old,new in [('PE_COUNT','p_lanes'),('accum_lane','i_accumulator'),('pool_lane_value','o_value'),
                    ('c.activation_min[7:0]','i_minimum'),('c.activation_max[7:0]','i_maximum'),
                    ('c.activation_min[7]','i_minimum[7]'),('c.activation_max[7]','i_maximum[7]')]:
        block=block.replace(old,new)
    return """module vector_pool_clamp #(parameter int unsigned p_lanes=8)(
 input wire logic signed[31:0] i_accumulator[p_lanes],
 input wire logic signed[7:0] i_minimum,i_maximum,
 output logic[7:0] o_value[p_lanes]);
"""+block+'endmodule\n'
reference=module(ORIGINAL_ENGINE)
CANDIDATE=OUT/'candidate.sv'
CANDIDATE.write_text(module(CURRENT_ENGINE))
REFERENCE=OUT/'reference.sv'
REFERENCE.write_text(reference)
assert CURRENT_ENGINE.replace(extract(CURRENT_ENGINE),extract(ORIGINAL_ENGINE))==ORIGINAL_ENGINE
MODES=[('generic',[]),('synthesis',['-DSYNTHESIS=1']),
       ('fpga',['-DXILINX_FPGA=1']),('fpga_synthesis',['-DSYNTHESIS=1','-DXILINX_FPGA=1'])]

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def execute(command,log):
    with log.open('w') as stream:
        subprocess.run(list(map(str,command)),cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,
                       check=True,timeout=300)

def formal(job):
    name,flags,lanes=job
    key=name+'_lanes'+str(lanes)
    commands=[]
    for label,source in [('reference',REFERENCE),('candidate',CANDIDATE)]:
        commands += ['read_slang --top vector_pool_clamp '+shlex.join([*flags,'-Gp_lanes='+str(lanes),str(source)]),
                     'setattr -mod -unset keep_hierarchy','setattr -unset keep_hierarchy',
                     'prep -top vector_pool_clamp -flatten','rename -top '+label,'design -stash '+label]
    commands += ['design -copy-from reference -as reference reference',
                 'design -copy-from candidate -as candidate candidate',
                 'equiv_make reference candidate proof','hierarchy -top proof',
                 'equiv_simple','equiv_status -assert']
    script,log=OUT/(key+'.ys'),OUT/(key+'.log')
    script.write_text('\n'.join(commands)+'\n')
    execute([sys.executable,ROOT/'scripts/fpga/open_fpga_synth.py','--worker',script],log)
    assert 'Equivalence successfully proven!' in log.read_text()
    print(key+' PASS',flush=True)
    return {'mode':name,'lanes':lanes,'passed':True,'log_sha256':sha(log)}

bench=OUT/'tb.sv'
bench.write_text('''module tb;
reg signed[31:0] i_accumulator[8];
reg signed[7:0] i_minimum,i_maximum;
wire[7:0] expected[8],actual[8];
integer checks=0;
pool_reference #(.p_lanes(8)) reference_dut(.*,.o_value(expected));
vector_pool_clamp #(.p_lanes(8)) candidate_dut(.*,.o_value(actual));
function automatic reg symbol(input integer value);
case(value%4)0:symbol=0;1:symbol=1;2:symbol=1'bx;3:symbol=1'bz;endcase
endfunction
initial begin
for(integer sample=0;sample<131072;sample++)begin
 i_minimum=$urandom;i_maximum=$urandom;
 for(integer lane=0;lane<8;lane++)i_accumulator[lane]=$urandom;
 case(sample%16)
  0:begin i_minimum=-128;i_maximum=127;end
  1:begin i_minimum=127;i_maximum=-128;end
  2:begin i_minimum=i_maximum;end
  3:begin for(integer lane=0;lane<8;lane++)i_accumulator[lane][7:0]=i_minimum;end
  4:begin for(integer lane=0;lane<8;lane++)i_accumulator[lane][7:0]=i_maximum;end
  5:i_minimum[sample%8]=1'bx;
  6:i_maximum[sample%8]=1'bz;
  7:begin i_minimum='x;i_maximum='z;end
  8:begin for(integer lane=0;lane<8;lane++)i_accumulator[lane][sample%8]=1'bx;end
  9:begin for(integer lane=0;lane<8;lane++)i_accumulator[lane][sample%8]=1'bz;end
  10:begin for(integer lane=0;lane<8;lane++)i_accumulator[lane]='x;end
  11:begin for(integer lane=0;lane<8;lane++)i_accumulator[lane][31:8]='z;end
  default:begin
   for(integer lane=0;lane<8;lane++)for(integer bit_index=0;bit_index<8;bit_index++)
    if((sample+lane+bit_index)%3==0)i_accumulator[lane][bit_index]=symbol(sample+bit_index);
   i_minimum[sample%8]=symbol(sample>>4);i_maximum[(sample>>4)%8]=symbol(sample>>6);
  end
 endcase
 #1;
 for(integer lane=0;lane<8;lane++)begin
  if(actual[lane]!==expected[lane])$fatal(1,"限幅结果不同 sample=%0d lane=%0d",sample,lane);
  checks++;
 end
end
$display("PASS comparisons=%0d",checks);$finish;
end
endmodule
''')
tb_ref=OUT/'tb_reference.sv'
tb_ref.write_text(reference.replace('module vector_pool_clamp #(','module pool_reference #(',1))

def four(mode):
    name,flags=mode
    exe=OUT/(name+'_simulation')
    execute(['iverilog','-g2012',*flags,'-s','tb','-o',exe,tb_ref,CANDIDATE,bench],OUT/(name+'_compile.log'))
    log=OUT/(name+'_run.log')
    execute(['vvp',exe],log)
    assert 'PASS comparisons=1048576' in log.read_text()
    print(name+' four-state PASS',flush=True)
    return {'mode':name,'passed':True,'comparisons':1048576,'log_sha256':sha(log)}

with ThreadPoolExecutor(max_workers=2) as workers:
    proof=list(workers.map(formal,[(name,flags,lanes)for name,flags in MODES for lanes in(1,8,16)]))
with ThreadPoolExecutor(max_workers=2) as workers:
    four_state=list(workers.map(four,MODES))
report={'passed':True,'parent_composition':{'passed':True,'reference_commit':REFERENCE_COMMIT,
        'unchanged_parent_except_proven_clamp':True,'vector_engine_sha256':sha(ROOT/'rtl/npu/conv/vector_engine.sv')},
        'candidate_sha256':sha(CANDIDATE),'test_sha256':sha(Path(__file__)),
        'formal':proof,'four_state':four_state,'binary_inputs_constrained':False,
        'all_public_outputs_compared':True}
(OUT/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
