#!/usr/bin/env python3
"""验证实际任务接收状态的不变量、时序等价和四态输入行为。"""
from concurrent.futures import ThreadPoolExecutor
import argparse
from context import context
import hashlib
import json
from pathlib import Path
import runpy
import shlex
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--out',type=Path,required=True)
args=parser.parse_args()
OUT=args.out.resolve()
OUT.mkdir(parents=True,exist_ok=True)
BASE=OUT/'context'
extraction=context(BASE)
HELPER=ROOT/'rtl/npu/top/npu_task_accept_qualify.sv'
MODES=[('generic',[]),('synthesis',['-DSYNTHESIS=1']),('fpga',['-DXILINX_FPGA=1']),
       ('fpga_synthesis',['-DSYNTHESIS=1','-DXILINX_FPGA=1'])]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def execute(command,log):
    with log.open('w')as stream:
        subprocess.run(list(map(str,command)),cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=300)
def formal(job):
    name,flags,cap=job
    key=name+'_capable'+str(cap)
    invariant=OUT/(key+'_invariant.ys');log=OUT/(key+'_invariant.log')
    invariant.write_text('\n'.join([
      'read_slang --top task_accept_property '+shlex.join([*flags,'-GVECTOR_ENGINE_CAPABLE='+str(cap),str(BASE/'reference.sv')]),
      'prep -top task_accept_property -flatten','async2sync','opt -full',
      'sat -tempinduct -seq 2 -maxsteps 5 -prove proof_idle 1 -verify'])+'\n')
    execute([sys.executable,ROOT/'scripts/fpga/open_fpga_synth.py','--worker',invariant],log)
    assert 'Induction step proven' in log.read_text()
    invariant_hash=sha(log)
    commands=[]
    for label in('reference','candidate'):
      commands += ['read_slang --top task_accept_property '+shlex.join([*flags,
        '-GVECTOR_ENGINE_CAPABLE='+str(cap),str(BASE/(label+'.sv')),str(HELPER)]),
        'setattr -mod -unset keep_hierarchy','setattr -unset keep_hierarchy',
        'prep -top task_accept_property -flatten','async2sync','opt -full',
        'rename -top '+label,'design -stash '+label]
    commands += ['design -copy-from reference -as reference reference',
      'design -copy-from candidate -as candidate candidate','equiv_make reference candidate proof',
      'hierarchy -top proof','equiv_simple -short -seq 2','equiv_induct -seq 3','equiv_status -assert']
    script,log=OUT/(key+'.ys'),OUT/(key+'.log')
    script.write_text('\n'.join(commands)+'\n')
    execute([sys.executable,ROOT/'scripts/fpga/open_fpga_synth.py','--worker',script],log)
    assert 'Equivalence successfully proven!'in log.read_text()
    print(key+' PASS',flush=True)
    return {'mode':name,'vector_capable':cap,'passed':True,'inputs_constrained':False,
            'invariant_log_sha256':invariant_hash,'equivalence_log_sha256':sha(log)}

reference=OUT/'reference.sv'
reference.write_text((BASE/'reference.sv').read_text().replace('module task_accept_property','module task_accept_reference',1))
bench=OUT/'tb.sv'
bench.write_text('''module tb;
reg clk=0,rst_n=0,calc_start,cfg_vector_enable,cfg_conv_enable,done_valid,done_ready;
reg[1:0]abort_state;
reg ps_capacity_fault,shared_ram_capacity_fault,vector_shared_store_o_error,dma_bus_error;
reg frame_mode_q,inner_done_valid;reg[1:0]inner_err_code;
reg run_conv,conv_error,vector_engine_ready,ctrl_sa_ready,frame_scheduler_ready;
reg[2:0]cfg_valid_q;
reg operand_cache_idle,frame_prefetch_idle,conv_task_idle;
wire[6:0]expected[2],actual[2];integer checks=0;
for(genvar cap=0;cap<2;cap++)begin:g_cap
task_accept_reference #(.VECTOR_ENGINE_CAPABLE(cap)) reference_dut(.*,
.sa_ready(expected[cap][0]),.vector_start_fire(expected[cap][1]),.task_accept_ready(expected[cap][2]),
.run_vector(expected[cap][3]),.vector_rejected(expected[cap][4]),.task_fault(expected[cap][5]),.proof_idle(expected[cap][6]));
task_accept_property #(.VECTOR_ENGINE_CAPABLE(cap)) candidate_dut(.*,
.sa_ready(actual[cap][0]),.vector_start_fire(actual[cap][1]),.task_accept_ready(actual[cap][2]),
.run_vector(actual[cap][3]),.vector_rejected(actual[cap][4]),.task_fault(actual[cap][5]),.proof_idle(actual[cap][6]));
end
task check;begin
for(integer cap=0;cap<2;cap++)begin
if(actual[cap]!==expected[cap])$fatal(1,"任务接收结果不同 sample=%0d cap=%0d expected=%b actual=%b",checks,cap,expected[cap],actual[cap]);
checks++;
end
end endtask
initial begin
for(integer sample=0;sample<262144;sample++)begin
 rst_n=sample%2048!=0;
 {calc_start,cfg_vector_enable,cfg_conv_enable,done_valid,done_ready,abort_state,
 ps_capacity_fault,shared_ram_capacity_fault,vector_shared_store_o_error,dma_bus_error,
 frame_mode_q,inner_done_valid,inner_err_code,run_conv,conv_error,vector_engine_ready,
 ctrl_sa_ready,frame_scheduler_ready,cfg_valid_q,operand_cache_idle,frame_prefetch_idle,conv_task_idle}=$urandom;
 if(sample%64<32)begin
  {ps_capacity_fault,shared_ram_capacity_fault,vector_shared_store_o_error,dma_bus_error}=0;
  frame_mode_q=0;inner_done_valid=0;inner_err_code=0;conv_error=0;
  abort_state=0;cfg_valid_q=0;vector_engine_ready=1;ctrl_sa_ready=1;frame_scheduler_ready=1;
  operand_cache_idle=1;frame_prefetch_idle=1;conv_task_idle=1;cfg_conv_enable=0;
  calc_start=sample%16==4;cfg_vector_enable=sample[6];done_valid=sample%16==12;done_ready=1;
 end
 case(sample%32)
 4:if(sample%128<64)cfg_vector_enable=1'bx;
 5:if(sample%128>=64)cfg_vector_enable=1'bz;
 6:conv_error=1'bx;
 7:run_conv=1'bz;
 8:dma_bus_error=1'bx;
 9:abort_state[0]=1'bz;
 10:calc_start=1'bx;
 11:done_valid=1'bz;
 12:frame_prefetch_idle=1'bx;
 13:cfg_conv_enable=1'bx;
 14:rst_n=1'bx;
 15:inner_err_code=2'bxz;
 default:begin end
 endcase
 #1;check();clk=1;#1;check();clk=0;
end
$display("PASS comparisons=%0d",checks);$finish;
end
endmodule
''')
def four(mode):
    name,flags=mode;exe=OUT/(name+'_simulation');log=OUT/(name+'_run.log')
    execute(['iverilog','-g2012',*flags,'-s','tb','-o',exe,reference,BASE/'candidate.sv',HELPER,bench],OUT/(name+'_compile.log'))
    execute(['vvp',exe],log)
    assert 'PASS comparisons=1048576'in log.read_text()
    print(name+' four-state PASS',flush=True)
    return {'mode':name,'passed':True,'comparisons':1048576,'log_sha256':sha(log)}
with ThreadPoolExecutor(max_workers=2)as workers:
    proofs=list(workers.map(formal,[(name,flags,cap)for name,flags in MODES for cap in(0,1)]))
with ThreadPoolExecutor(max_workers=2)as workers:four_state=list(workers.map(four,MODES))
source_tools=runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))
sources=source_tools['with_dependencies']([ROOT/'rtl/npu/top/npu_top.sv'],ROOT)
flags=['--keep-hierarchy','-I'+str(ROOT/'include'),'-I'+str(ROOT/'rtl/npu/ps_compact'),
 '-I'+str(ROOT/'asic/rtl'),'-DSYNTHESIS=1','-DXILINX_FPGA=1','-DGEMMORA_PS_POOL_BYTES=49152',
 '-DGEMMORA_PS_FORCE_RAW=1','-DGEMPACT_PS_COMPRESS=1','-GSIZE=16','-GBUS_WIDTH=64',
 '-GADDR_WIDTH=32','-GVECTOR_PE_COUNT=8','-GWINDOW_LANES=8','-GSHARED_BANK_BYTES=8192',
 '-GSHARED_BANK_COUNT=7']
script,log=OUT/'parent_elaborate.ys',OUT/'parent_elaborate.log'
script.write_text('read_slang --top npu_top '+shlex.join(flags+list(map(str,sources)))+
 '\nhierarchy -check -top npu_top\n')
execute([sys.executable,ROOT/'scripts/fpga/open_fpga_synth.py','--worker',script],log)
parent_elaboration={'passed':True,'log_sha256':sha(log),'options':flags,
 'sources_sha256':{str(p.relative_to(ROOT)):sha(p)for p in source_tools['input_files'](sources,ROOT,[ROOT/'include'])}}
report={'passed':True,'formal':proofs,'four_state':four_state,'source_sha256':{
 'npu_task_accept_qualify.sv':sha(HELPER),'reference_context':sha(BASE/'reference.sv'),
 'candidate_context':sha(BASE/'candidate.sv'),'candidate_parent':sha(ROOT/'rtl/npu/top/npu_top.sv')},
 'test_sha256':sha(Path(__file__)),'context_script_sha256':sha(Path(__file__).with_name('context.py')),
 'nonstate_fanins_unconstrained':True,'parent_composition':extraction,'parent_elaboration':parent_elaboration}
(OUT/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
