#!/usr/bin/env python3
"""验证向量控制边界比较及舍入进位的公开时序输出。"""
from concurrent.futures import ThreadPoolExecutor
import argparse
import hashlib
import json
from pathlib import Path
import runpy
import shlex
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/'rtl/npu/conv'
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--out',type=Path,required=True)
args=parser.parse_args()
OUT=args.out.resolve()
OUT.mkdir(parents=True,exist_ok=True)
REFERENCE='86034eb4'
REFERENCE_DIR=OUT/'reference'
REFERENCE_DIR.mkdir(exist_ok=True)
for name in ('vector_round_shift','vector_engine_control'):
    path=REFERENCE_DIR/(name+'.sv')
    path.write_text(subprocess.check_output(['git','show',REFERENCE+':rtl/npu/conv/'+name+'.sv'],cwd=ROOT,text=True))
MODES=[('generic',[]),('synthesis',['-DSYNTHESIS=1']),
       ('fpga',['-DXILINX_FPGA=1']),('fpga_synthesis',['-DSYNTHESIS=1','-DXILINX_FPGA=1'])]
resolve=runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def execute(command,log):
    with log.open('w')as stream:
        subprocess.run(list(map(str,command)),cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=600)
def formal(job):
    name,flags,kind,middle,input_stage=job
    key=f'{name}_{kind}_middle{middle}_input{input_stage}'
    top='vector_round_shift' if kind=='round' else 'vector_engine_control'
    options=[f'-GREGISTER_MIDDLE={middle}',f'-GREGISTER_INPUT={input_stage}'] if kind=='round' else [
      '-Gp_tile=16','-Gp_bus_width=64','-Gp_dma_size=64','-Gp_pe_count=8','-Gp_window_lanes=8',
      '-Gp_shared_storage_enable=1','-Gp_shared_quant_enable=0']
    commands=[]
    for label,source in [('reference',REFERENCE_DIR/(top+'.sv')),('candidate',BASE/(top+'.sv'))]:
        sources=resolve([source],ROOT)
        commands += ['read_slang --top '+top+' '+shlex.join([*flags,*options,*map(str,sources)]),
          'setattr -mod -unset keep_hierarchy','setattr -unset keep_hierarchy',
          'prep -top '+top+' -flatten','memory_map','async2sync','opt -full',
          'rename -top '+label,'design -stash '+label]
    commands += ['design -copy-from reference -as reference reference',
      'design -copy-from candidate -as candidate candidate','equiv_make reference candidate proof',
      'hierarchy -top proof','equiv_simple -short -seq 2','equiv_induct -seq 3','equiv_status -assert']
    script,log=OUT/(key+'.ys'),OUT/(key+'.log')
    script.write_text('\n'.join(commands)+'\n')
    execute([sys.executable,ROOT/'scripts/fpga/open_fpga_synth.py','--worker',script],log)
    assert 'Equivalence successfully proven!' in log.read_text()
    print(key+' PASS',flush=True)
    return {'mode':name,'kind':kind,'middle':middle,'input_stage':input_stage,'passed':True,
            'all_public_outputs_compared':True,'external_inputs_constrained':False,'log_sha256':sha(log)}

round_ref=OUT/'round_reference.sv'
round_ref.write_text((REFERENCE_DIR/'vector_round_shift.sv').read_text().replace('module vector_round_shift #(','module round_reference #(',1))
round_tb=OUT/'round_tb.sv'
round_tb.write_text('''module tb;
reg clk=0;reg signed[63:0]value;reg[5:0]amount;
wire signed[63:0]expected[4],actual[4],expected_floor[4],actual_floor[4];
integer checks=0;
for(genvar mode=0;mode<4;mode++)begin:g_mode
round_reference #(.REGISTER_MIDDLE(mode%2),.REGISTER_INPUT(mode/2)) ref_dut(.clk(clk),.value(value),.amount(amount),.result(expected[mode]),.floor_value(expected_floor[mode]));
vector_round_shift #(.REGISTER_MIDDLE(mode%2),.REGISTER_INPUT(mode/2)) dut(.clk(clk),.value(value),.amount(amount),.result(actual[mode]),.floor_value(actual_floor[mode]));
end
task check;begin
for(integer mode=0;mode<4;mode++)begin
 if({actual[mode],actual_floor[mode]}!=={expected[mode],expected_floor[mode]})$fatal(1,"舍入结果不同 sample=%0d mode=%0d",checks,mode);
 checks++;
end
end endtask
initial begin
for(integer sample=0;sample<131072;sample++)begin
 value={$urandom,$urandom};amount=6'(sample);
 case(sample%16)
 0:value=64'h7fffffffffffffff;
 1:value=64'h8000000000000000;
 2:value='1;
 3:value=0;
 4:value[sample%64]=1'bx;
 5:value[sample%64]=1'bz;
 6:amount[sample%6]=1'bx;
 7:amount[sample%6]=1'bz;
 8:begin value='x;amount='z;end
 9:begin value=64'h7fffffffffffffff;value[(sample>>4)%64]=1'bx;end
 default:begin end
 endcase
 #1;check();clk=1;#1;check();clk=0;
end
$display("PASS comparisons=%0d",checks);$finish;
end
endmodule
''')
control_sources=[]
for label,path in [('reference',REFERENCE_DIR/'vector_engine_control.sv'),('candidate',BASE/'vector_engine_control.sv')]:
    text=path.read_text()
    first=text.index('  // 完成状态在位置更新后') if label=='reference' else text.index('  logic next_position_less, next_position_equal;')
    last=text.index('  always_ff @(posedge clk or negedge rst_n)',first)
    unit=OUT/(label+'_position.sv')
    unit.write_text('module '+label+'''_position(input logic clk,input logic[31:0]position_next,
input logic[63:0]position_count,output logic position_has_more,o_position_is_last);
'''+text[first:last]+'endmodule\n')
    control_sources.append(unit)
control_tb=OUT/'position_tb.sv'
control_tb.write_text('''module tb;
reg clk=0;reg[31:0]position_next;reg[63:0]position_count;
wire[1:0]expected,actual;integer checks=0;
reference_position ref_dut(.*,.position_has_more(expected[0]),.o_position_is_last(expected[1]));
candidate_position dut(.*,.position_has_more(actual[0]),.o_position_is_last(actual[1]));
task check;begin if(actual!==expected)$fatal(1,"位置比较结果不同 sample=%0d",checks);checks++;end endtask
initial begin
for(integer sample=0;sample<131072;sample++)begin
 position_next=$urandom;position_count={$urandom,$urandom};
 case(sample%16)
 0:position_count[31:0]=position_next;
 1:position_count=0;
 2:position_next='1;
 3:position_next[sample%32]=1'bx;
 4:position_count[sample%32]=1'bz;
 5:position_count[63:32]='x;
 6:begin position_next='x;position_count='z;end
 default:begin end
 endcase
 #1;check();clk=1;#1;check();clk=0;
end
$display("PASS comparisons=%0d",checks);$finish;
end
endmodule
''')
def four(job):
    name,flags,kind=job
    key=name+'_'+kind
    sources=([round_ref,BASE/'vector_round_shift.sv']if kind=='round' else control_sources)
    bench=round_tb if kind=='round' else control_tb
    count=1048576 if kind=='round' else 262144
    dependencies=resolve(sources,ROOT)
    exe=OUT/(key+'_simulation')
    execute(['iverilog','-g2012',*flags,'-s','tb','-o',exe,*dependencies,bench],OUT/(key+'_compile.log'))
    log=OUT/(key+'_run.log')
    execute(['vvp',exe],log)
    assert 'PASS comparisons='+str(count) in log.read_text()
    print(key+' four-state PASS',flush=True)
    return {'mode':name,'kind':kind,'passed':True,'comparisons':count,'log_sha256':sha(log)}
jobs=[(name,flags,'round',middle,inp)for name,flags in MODES for middle in(0,1)for inp in(0,1)]
jobs += [(name,flags,'control',0,0)for name,flags in MODES]
with ThreadPoolExecutor(max_workers=2)as workers:proofs=list(workers.map(formal,jobs))
with ThreadPoolExecutor(max_workers=2)as workers:
    four_states=list(workers.map(four,[(name,flags,kind)for name,flags in MODES for kind in('round','position')]))
report={'passed':True,'formal':proofs,'four_state':four_states,'test_sha256':sha(Path(__file__)),'reference_commit':REFERENCE,
        'reference_sha256':{name:sha(REFERENCE_DIR/(name+'.sv'))for name in('vector_round_shift','vector_engine_control')},
        'source_sha256':{name:sha(BASE/(name+'.sv'))for name in('vector_round_shift','vector_engine_control')}}
(OUT/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
