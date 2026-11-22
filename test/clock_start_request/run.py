"""检查唤醒控制的状态、启动握手和时钟请求。"""
from pathlib import Path
import re,subprocess,json,sys,hashlib,argparse
ROOT=Path(__file__).resolve().parents[2]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--out',type=Path,required=True)
parser.add_argument('--source-root',type=Path,default=ROOT)
parser.add_argument('--reference',default='6f70ce67')
args=parser.parse_args()
OUT=args.out.resolve();OUT.mkdir(parents=True,exist_ok=True)
relative='rtl/axi_top/npu_axil_top.sv'
(OUT/'reference.sv').write_bytes(subprocess.check_output(['git','show',args.reference+':'+relative],cwd=ROOT))
(OUT/'current.sv').write_bytes((args.source_root/relative).read_bytes())

def extract(source,label):
 begin=source.index('    always_ff @(posedge clk or negedge rst_n) begin\n        if (!rst_n) begin\n            npu_clk_reset_warmup_q')
 end=source.index('    assign npu_core_calc_start',begin)
 process=source[begin:end]
 # 组合资格从生产表达式读取，两个设计分别保留内部请求名称。
 start=re.search(r'assign npu_core_calc_start\s*=.*?;',source,re.S)[0]
 enable=re.search(r'assign npu_clk_gate_en\s*=.*?;',source,re.S)[0]
 text='''module control #(parameter int ENABLE_CLOCK_GATING=1)(
 input logic clk,rst_n,calc_start_pulse,npu_sa_ready,npu_done_fire,npu_done_valid,npu_axi_idle,npu_busy,
 output wire [5:0] observed_state,
 output wire observed_acceptance,observed_clock_enable,
 output wire observed_profile_error);
 logic [1:0] npu_clk_reset_warmup_q;
 logic npu_clk_req_q,npu_start_pending_q,npu_start_warmup_q,npu_done_seen_q;
 wire npu_core_calc_start,npu_clk_gate_en;
'''+process+start+'''
 generate if(ENABLE_CLOCK_GATING!=0)begin
'''+enable+'''
 end else begin
 assign npu_clk_gate_en=1'b1;
 end endgenerate
 assign observed_state={npu_clk_reset_warmup_q,npu_clk_req_q,npu_start_pending_q,npu_start_warmup_q,npu_done_seen_q};
 assign observed_acceptance=npu_core_calc_start && npu_sa_ready;
 assign observed_clock_enable=npu_clk_gate_en;
`ifdef GEMMORA_INT8_PROFILE
 assign observed_profile_error=npu_core_calc_start;
`else
 assign observed_profile_error=1'b0;
`endif
endmodule
'''
 return text.replace('npu_core_calc_start',label+'_start_signal')

mods={label:extract((OUT/f'{label}.sv').read_text(),label)for label in ['reference','current']}
for label,text in mods.items():(OUT/f'{label}_control.sv').write_text(text)
proofs=[]
for profile in [0,1]:
 for gate in [0,1]:
  commands=[]
  for label in ['reference','current']:
   options='-DGEMMORA_INT8_PROFILE=1 'if profile else''
   commands += [f'read_slang {options}--top control -GENABLE_CLOCK_GATING={gate} '+str(OUT/f'{label}_control.sv'),'prep -top control -flatten','async2sync','opt_clean',f'rename control {label}',f'design -stash {label}']
  commands+=['design -copy-from reference -as reference reference','design -copy-from current -as current current','equiv_make reference current equivalent','hierarchy -top equivalent','equiv_simple -seq 1','equiv_induct -seq 4','equiv_status -assert']
  script=OUT/f'formal_{profile}_{gate}.ys';script.write_text('\n'.join(commands)+'\n');log=script.with_suffix('.log')
  with log.open('w')as f:subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],stdout=f,stderr=subprocess.STDOUT,check=True,timeout=90)
  m=re.search(r'Of those cells (\d+) are proven and (\d+) are unproven',log.read_text());assert m and int(m[2])==0
  proofs.append({'profile':profile,'clock_gating':gate,'equivalent_bits':int(m[1]),'passed':True})
bench='''module tb;
 reg clk=0,rst_n=0;always #5 clk=~clk;
 reg calc_start_pulse=0,npu_sa_ready=0,npu_done_fire=0,npu_done_valid=0,npu_axi_idle=1,npu_busy=0;
 reg [31:0] seed=32'h394fd180;integer checks=0;
 function automatic [31:0] random_word;
 begin seed=seed^(seed<<13);seed=seed^(seed>>17);seed=seed^(seed<<5);random_word=seed;end
 endfunction
 function automatic four_value(input [1:0] value);
 case(value)0:four_value=0;1:four_value=1;2:four_value=1'bx;3:four_value=1'bz;endcase
 endfunction
 for(genvar gate=0;gate<2;gate++)begin:g_gate
 wire [8:0] reference_value,current_value;
 reference #(.ENABLE_CLOCK_GATING(gate)) reference_instance(.clk,.rst_n,.calc_start_pulse,.npu_sa_ready,.npu_done_fire,.npu_done_valid,.npu_axi_idle,.npu_busy,.observed_state(reference_value[5:0]),.observed_acceptance(reference_value[6]),.observed_clock_enable(reference_value[7]),.observed_profile_error(reference_value[8]));
 current #(.ENABLE_CLOCK_GATING(gate)) current_instance(.clk,.rst_n,.calc_start_pulse,.npu_sa_ready,.npu_done_fire,.npu_done_valid,.npu_axi_idle,.npu_busy,.observed_state(current_value[5:0]),.observed_acceptance(current_value[6]),.observed_clock_enable(current_value[7]),.observed_profile_error(current_value[8]));
 always @(negedge check_step)if(reference_value!==current_value)$fatal(1,"Control state mismatch");
 end
 reg check_step=0;
 initial begin
 repeat(2)@(negedge clk);
 for(integer sample=0;sample<100003;sample++)begin
 rst_n=(sample%113)!=0;
 calc_start_pulse=sample[0]?four_value(2'(random_word())):1'(random_word());
 npu_sa_ready=sample[0]?four_value(2'(random_word())):1'(random_word());
 npu_done_fire=sample[0]?four_value(2'(random_word())):1'(random_word());
 npu_done_valid=sample[0]?four_value(2'(random_word())):1'(random_word());
 npu_axi_idle=sample[0]?four_value(2'(random_word())):1'(random_word());
 npu_busy=sample[0]?four_value(2'(random_word())):1'(random_word());
 #1;check_step=1;#1;check_step=0;checks+=18;
 @(posedge clk);#1;check_step=1;#1;check_step=0;checks+=18;
 @(negedge clk);
 end
 #1;$display("PASS comparisons=%0d",checks);$finish;
 end
endmodule
'''
combined='\n'.join(text.replace('module control','module '+label)for label,text in mods.items())+bench
(OUT/'four_state.sv').write_text(combined)
for profile in [0,1]:
 binary=OUT/f'four_{profile}.vvp';log=OUT/f'four_{profile}.log'
 with (OUT/f'four_{profile}_build.log').open('w')as f:subprocess.run(['iverilog','-g2012','-s','tb',*(['-DGEMMORA_INT8_PROFILE=1']if profile else[]),'-o',str(binary),str(OUT/'four_state.sv')],stdout=f,stderr=subprocess.STDOUT,check=True)
 r=subprocess.run(['vvp',str(binary)],text=True,capture_output=True,timeout=90);log.write_text(r.stdout+r.stderr);r.check_returncode();assert 'PASS comparisons=3600108'in r.stdout
result={'passed':True,'proofs':proofs,'four_state_cycles':200006,'four_state_output_comparisons':7200216,'inputs_constrained':False,'reference':args.reference,'runner_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'source_sha256':{n:hashlib.sha256((OUT/f'{n}.sv').read_bytes()).hexdigest()for n in mods}}

# 使用实际时钟控制模块检查复位相位、等待就绪和请求消费。
gate_out=OUT/'clock_gate';gate_out.mkdir(exist_ok=True)
shells=[]
interface_sources=[args.source_root/'rtl/npu/top/npu_top.sv',args.source_root/'rtl/axi_top/npu_axil_reg_if.sv']
for source in interface_sources:
 text=source.read_text();end=re.search(r'^\);',text,re.M)
 if end is None:raise RuntimeError('Cannot locate child interface: '+str(source))
 target=gate_out/(source.stem+'_ports.sv');target.write_text(text[:end.end()]+'\nendmodule\n');shells.append(target)
bench=ROOT/'test/conv_dma/operand_drain/tb_clock_gate_reset.sv'
gate_sources=[args.source_root/'rtl/npu/conv/conv_im2col_pkg.sv',args.source_root/'rtl/npu/conv/vector_engine_pkg.sv',*shells,args.source_root/relative,bench]
with(gate_out/'build.log').open('w')as f:subprocess.run(['iverilog','-g2012','-s','tb_clock_gate_reset','-o',str(gate_out/'simulation.vvp'),*map(str,gate_sources)],stdout=f,stderr=subprocess.STDOUT,check=True)
r=subprocess.run(['vvp',str(gate_out/'simulation.vvp')],text=True,capture_output=True,timeout=60)
(gate_out/'run.log').write_text(r.stdout+r.stderr);r.check_returncode()
match=re.search(r'CLOCK_GATE_RESET_PASS edges=(\d+)',r.stdout)
if match is None:raise RuntimeError('Clock phase and request verification did not complete')
result['clock_gate']={'passed':True,'observed_edges':int(match[1]),'child_interfaces_only':True,'testbench_sha256':hashlib.sha256(bench.read_bytes()).hexdigest(),'simulation_log_sha256':hashlib.sha256((gate_out/'run.log').read_bytes()).hexdigest()}
result['runner_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
(OUT/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({'passed':True,'clock_edges':int(match[1])}))
