#!/usr/bin/env python3
"""验证 PE 低半字比较的完整时序和四态行为。"""
from concurrent.futures import ThreadPoolExecutor
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--out',type=Path,required=True)
args=parser.parse_args()
OUT=args.out.resolve()
OUT.mkdir(parents=True,exist_ok=True)
REFERENCE='86034eb4'
REF=OUT/'reference_vector_pe.sv'
REF.write_text(subprocess.check_output(['git','show',REFERENCE+':rtl/npu/conv/vector_pe.sv'],cwd=ROOT,text=True))
CANDIDATE=ROOT/'rtl/npu/conv/vector_pe.sv'
MODES=[('generic',[]),('synthesis',['-DSYNTHESIS=1']),
       ('fpga',['-DXILINX_FPGA=1']),('fpga_synthesis',['-DSYNTHESIS=1','-DXILINX_FPGA=1'])]
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def execute(command,log):
    with log.open('w') as stream:
        subprocess.run(list(map(str,command)),cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,
                       check=True,timeout=300)
def formal(job):
    name,flags,extended,preselected=job
    key=f'{name}_extended{extended}_preselected{preselected}'
    commands=[]
    for label,source in [('reference',REF),('candidate',CANDIDATE)]:
        commands += ['read_slang --top vector_pe '+shlex.join([*flags,
          '-GENABLE_EXTENDED_MULTIPLY='+str(extended),'-Gp_accumulator_preselected='+str(preselected),str(source)]),
          'prep -top vector_pe -flatten','rename -top '+label,'design -stash '+label]
    commands += ['design -copy-from reference -as reference reference',
      'design -copy-from candidate -as candidate candidate','equiv_make reference candidate proof',
      'hierarchy -top proof','equiv_simple -short -seq 2','equiv_induct -seq 3','equiv_status -assert']
    script,log=OUT/(key+'.ys'),OUT/(key+'.log')
    script.write_text('\n'.join(commands)+'\n')
    execute([sys.executable,ROOT/'scripts/fpga/open_fpga_synth.py','--worker',script],log)
    assert 'Equivalence successfully proven!' in log.read_text()
    print(key+' PASS',flush=True)
    return {'mode':name,'extended_multiply':extended,'accumulator_preselected':preselected,
            'passed':True,'log_sha256':sha(log)}
tb_ref=OUT/'reference.sv'
tb_ref.write_text(REF.read_text().replace('module vector_pe #(','module pe_reference #(',1))
bench=OUT/'tb.sv'
bench.write_text('''module tb;
reg clk=0,i_en;
reg[2:0]i_op;
reg signed[15:0] i_a,i_b;
reg signed[31:0] i_acc;
wire signed[31:0] expected[4],actual[4];
integer checks=0;
for(genvar mode=0;mode<4;mode++)begin:g_mode
pe_reference #(.ENABLE_EXTENDED_MULTIPLY(mode%2),.p_accumulator_preselected(mode/2)) ref_dut(.*,.o_result(expected[mode]));
vector_pe #(.ENABLE_EXTENDED_MULTIPLY(mode%2),.p_accumulator_preselected(mode/2)) dut(.*,.o_result(actual[mode]));
end
function automatic reg symbol(input integer value);
case(value%4)0:symbol=0;1:symbol=1;2:symbol=1'bx;3:symbol=1'bz;endcase
endfunction
task check;begin
for(integer mode=0;mode<4;mode++)begin
if(actual[mode]!==expected[mode])$fatal(1,"PE结果不同 sample=%0d mode=%0d",checks,mode);
checks++;
end
end endtask
initial begin
for(integer sample=0;sample<131072;sample++)begin
i_a=$urandom;i_b=$urandom;i_acc=$urandom;i_op=3'(sample);i_en=(sample%16<12)?1:symbol(sample>>4);
case(sample%16)
0:begin i_acc={{16{i_a[15]}},i_a};end
1:begin i_acc[31:16]={16{i_a[15]}};end
2:i_acc[sample%32]=1'bx;
3:i_a[sample%16]=1'bz;
4:i_b[sample%16]=1'bx;
5:i_op[sample%3]=1'bx;
6:i_op[sample%3]=1'bz;
7:begin i_acc='x;i_a='z;end
8:begin i_acc[31:16]='0;i_a[15]=1;end
9:begin i_acc[31:16]='1;i_a[15]=0;end
default:begin end
endcase
#1;check();clk=1;#1;check();clk=0;
end
$display("PASS comparisons=%0d",checks);$finish;
end
endmodule
''')
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
    proofs=list(workers.map(formal,[(name,flags,e,p)for name,flags in MODES for e in(0,1)for p in(0,1)]))
with ThreadPoolExecutor(max_workers=2) as workers:
    four_states=list(workers.map(four,MODES))
(OUT/'summary.json').write_text(json.dumps({'passed':True,'formal':proofs,'four_state':four_states,
  'source_sha256':{'reference':sha(REF),'candidate':sha(CANDIDATE)},
  'external_inputs_constrained':False,'all_public_outputs_compared':True,'test_sha256':sha(Path(__file__))},indent=2)+'\n')
