#!/usr/bin/env python3
"""验证四类激活限幅的完整有符号范围、寄存边沿及四态行为。"""
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
REF=OUT/'reference_vector_activation_clamp.sv'
REF.write_text(subprocess.check_output(['git','show',REFERENCE+':rtl/npu/conv/vector_activation_clamp.sv'],cwd=ROOT,text=True))
CANDIDATE=ROOT/'rtl/npu/conv/vector_activation_clamp.sv'
MODES=[('generic',[]),('synthesis',['-DSYNTHESIS=1']),
       ('fpga',['-DXILINX_FPGA=1']),('fpga_synthesis',['-DSYNTHESIS=1','-DXILINX_FPGA=1'])]
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def execute(command,log):
    with log.open('w') as stream:
        subprocess.run(list(map(str,command)),cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,
                       check=True,timeout=300)
def formal(mode):
    name,flags=mode
    commands=[]
    for label,source in [('reference',REF),('candidate',CANDIDATE)]:
        commands += ['read_slang --top vector_activation_clamp '+shlex.join([*flags,str(source)]),
          'prep -top vector_activation_clamp -flatten','rename -top '+label,'design -stash '+label]
    commands += ['design -copy-from reference -as reference reference',
      'design -copy-from candidate -as candidate candidate','equiv_make reference candidate proof',
      'hierarchy -top proof','equiv_simple -short -seq 2','equiv_induct -seq 3','equiv_status -assert']
    script,log=OUT/(name+'.ys'),OUT/(name+'.log')
    script.write_text('\n'.join(commands)+'\n')
    execute([sys.executable,ROOT/'scripts/fpga/open_fpga_synth.py','--worker',script],log)
    assert 'Equivalence successfully proven!' in log.read_text()
    print(name+' PASS',flush=True)
    return {'mode':name,'passed':True,'log_sha256':sha(log)}
tb_ref=OUT/'reference.sv'
tb_ref.write_text(REF.read_text().replace('module vector_activation_clamp (','module activation_reference (',1))
bench=OUT/'tb.sv'
bench.write_text('''module tb;
reg clk=0;
reg signed[31:0] cfg_output_offset,cfg_minimum,cfg_maximum;
reg signed[63:0] i_quantized_value,i_add_rounded_value;
reg signed[7:0] i_average_floor,i_average_rounded;
reg signed[8:0] i_average_divided;
wire[3:0][31:0] expected,actual;
integer checks=0;
activation_reference reference_dut(.*,.o_result(expected));
vector_activation_clamp candidate_dut(.*,.o_result(actual));
function automatic reg symbol(input integer value);
case(value%4)0:symbol=0;1:symbol=1;2:symbol=1'bx;3:symbol=1'bz;endcase
endfunction
task check;begin
if(actual!==expected)$fatal(1,"激活结果不同 sample=%0d expected=%h actual=%h",checks,expected,actual);
checks++;
end endtask
initial begin
for(integer sample=0;sample<262144;sample++)begin
cfg_output_offset=$urandom;cfg_minimum=$urandom;cfg_maximum=$urandom;
i_quantized_value={$urandom,$urandom};i_add_rounded_value={$urandom,$urandom};
i_average_floor=$urandom;i_average_rounded=$urandom;i_average_divided=$urandom;
case(sample%32)
0:begin cfg_minimum=-128;cfg_maximum=127;end
1:begin cfg_minimum=127;cfg_maximum=-128;end
2:begin cfg_minimum=cfg_maximum;end
3:begin i_quantized_value=$signed(i_average_divided);i_add_rounded_value=$signed(i_average_divided);end
4:begin i_quantized_value=64'h7fffffffffffffff;cfg_output_offset=127;end
5:begin i_quantized_value=64'h8000000000000000;cfg_output_offset=-128;end
6:begin i_add_rounded_value=255;end
7:begin i_add_rounded_value=-256;end
8:begin cfg_minimum='x;end
9:begin cfg_maximum='z;end
10:begin cfg_output_offset[sample%32]=1'bx;end
11:begin i_quantized_value[sample%64]=1'bz;end
12:begin i_add_rounded_value[sample%64]=1'bx;end
13:begin i_average_floor[sample%8]=1'bz;end
14:begin i_average_divided[sample%9]=1'bx;end
15:begin i_average_rounded[sample%8]=1'bz;end
16:begin i_quantized_value='x;i_add_rounded_value='z;end
17:begin i_quantized_value=$signed(cfg_minimum[7:0]);i_add_rounded_value=$signed(cfg_maximum[7:0]);end
18:begin cfg_minimum=$signed(i_average_floor);cfg_maximum=$signed(i_average_divided);end
19:begin cfg_output_offset=0;end
default:begin
i_quantized_value=$signed(10'($urandom));i_add_rounded_value=$signed(10'($urandom));
if(sample%8==0)begin cfg_minimum[sample%32]=symbol(sample>>5);cfg_maximum[(sample>>4)%32]=symbol(sample>>7);end
end
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
    assert 'PASS comparisons=524288' in log.read_text()
    print(name+' four-state PASS',flush=True)
    return {'mode':name,'passed':True,'comparisons':524288,'log_sha256':sha(log)}
with ThreadPoolExecutor(max_workers=2) as workers:
    proofs=list(workers.map(formal,MODES))
with ThreadPoolExecutor(max_workers=2) as workers:
    four_states=list(workers.map(four,MODES))
(OUT/'summary.json').write_text(json.dumps({'passed':True,'formal':proofs,'four_state':four_states,
  'source_sha256':{'reference':sha(REF),'candidate':sha(CANDIDATE)},
  'external_inputs_constrained':False,'all_public_outputs_compared':True,'test_sha256':sha(Path(__file__))},indent=2)+'\n')
