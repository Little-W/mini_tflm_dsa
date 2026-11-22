#!/usr/bin/env python3
"""检查加载末项比较与行数选择的完整输入组合关系。"""
import argparse,hashlib,json,re,shlex,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--tool-root',type=Path,default=ROOT);p.add_argument('--source-root',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
source=a.source_root/'rtl/npu/loaders/ia_loader_ctrl.sv';text=source.read_text();digest=hashlib.sha256(source.read_bytes()).hexdigest()
def between(start,end):
 i=text.index(start);return text[i:text.index(end,i)]
compare=between('    localparam int p_boundary_groups','  end else begin : g_current_load_boundary')
selected=between('  if (p_saved_load_boundary) begin : g_selected_load_boundary','  logic load_is_last_col_tile;')
rows=between('  if (p_saved_load_boundary) begin : g_parallel_rows_match','  assign request_rows = load_rows_cur;')
module='''module proof #(parameter int LOAD_CNT_W=7,SIZE=16,REG_WIDTH=32,parameter bit p_saved_load_boundary=1)(
 input logic[LOAD_CNT_W-1:0]cursor_after_q,load_last_equal_i_regular,load_last_equal_i_tail,load_last_equal_i_prefetch,
 input logic load_l2_is_last,prefetch_active,is_last_l2_group,
 input logic[$clog2(SIZE+1)-1:0]request_rows_target,input logic[REG_WIDTH-1:0]rsp_rows_last_tile,
 output logic equivalent);
 localparam int ROW_CNT_W=$clog2(SIZE+1);
 logic load_last_equal_o_regular,load_last_equal_o_tail,load_last_equal_o_prefetch;
 logic load_is_last_row_tile,request_rows_matches;
 wire reference_last=load_l2_is_last&&(prefetch_active?(cursor_after_q==load_last_equal_i_prefetch):
  (is_last_l2_group?(cursor_after_q==load_last_equal_i_tail):(cursor_after_q==load_last_equal_i_regular)));
 wire[REG_WIDTH-1:0]reference_rows=reference_last?rsp_rows_last_tile:REG_WIDTH'(SIZE);
 wire[REG_WIDTH-1:0]load_rows_cur=load_is_last_row_tile?rsp_rows_last_tile:REG_WIDTH'(SIZE);
'''+compare+selected+rows+'''
 assign equivalent=(load_is_last_row_tile===reference_last)&&
  (request_rows_matches===(request_rows_target==reference_rows[ROW_CNT_W-1:0]));
endmodule
'''
sv=a.out/'boundary_selection.sv';sv.write_text(module);runs=[]
for w,size,reg in[(x,16,32)for x in range(1,11)]+[(7,x,64)for x in(2,4,8,32,64)]:
 name=f'w{w}_s{size}_r{reg}';ys=a.out/(name+'.ys');log=a.out/(name+'.log');ys.write_text('read_slang --top proof -DSYNTHESIS=1 -DXILINX_FPGA=1 '+f'-GLOAD_CNT_W={w} -GSIZE={size} -GREG_WIDTH={reg} '+shlex.quote(str(sv))+'\nprep -top proof -flatten\ncheck -assert\nsat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
 with log.open('w')as f:r=subprocess.run([sys.executable,str(a.tool_root.resolve()/'scripts/fpga/open_fpga_synth.py'),'--worker',str(ys)],stdout=f,stderr=subprocess.STDOUT,timeout=60)
 assert r.returncode==0 and'SUCCESS!'in log.read_text(),log
 runs.append({'name':name,'passed':True,'width':w,'size':size,'reg_width':reg,'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()})
bench=a.out/'boundary_event.sv';bench.write_text('''module tb;
 logic[9:0]cursor_after_q,load_last_equal_i_regular,load_last_equal_i_tail,load_last_equal_i_prefetch;
 logic load_l2_is_last,prefetch_active,is_last_l2_group;
 logic[5:0]request_rows_target;logic[63:0]rsp_rows_last_tile;wire equivalent;
 proof #(.LOAD_CNT_W(10),.SIZE(32),.REG_WIDTH(64),.p_saved_load_boundary(0))dut(.*);
 initial begin
 for(integer sample=0;sample<50000;sample++)begin
 cursor_after_q=$random;load_last_equal_i_regular=$random;load_last_equal_i_tail=$random;load_last_equal_i_prefetch=$random;
 load_l2_is_last=$random;prefetch_active=$random;is_last_l2_group=$random;
 request_rows_target=$random;rsp_rows_last_tile={$random,$random};
 if(sample%2==0)load_last_equal_i_regular=cursor_after_q;
 if(sample%3==0)load_last_equal_i_tail=cursor_after_q;
 if(sample%5==0)load_last_equal_i_prefetch=cursor_after_q;
 if(sample%7==0)prefetch_active=1'bx;
 if(sample%11==0)is_last_l2_group=1'bz;
 if(sample%13==0)cursor_after_q[sample%10]=1'bx;
 if(sample%17==0)request_rows_target[sample%6]=1'bz;
 if(sample%19==0)rsp_rows_last_tile[sample%64]=1'bx;
 #1;if(equivalent!==1'b1)$fatal(1,"boundary propagation sample=%0d",sample);
 end
 $display("IA_BOUNDARY_EVENT_PASS comparisons=100000");$finish;
 end
endmodule
''')
binary=a.out/'boundary_event.vvp';subprocess.run(['/home/agent/.local/bin/iverilog','-g2012','-s','tb','-o',str(binary),str(sv),str(bench)],check=True,capture_output=True)
r=subprocess.run(['/home/agent/.local/bin/vvp',str(binary)],check=True,capture_output=True,text=True);(a.out/'boundary_event.log').write_text(r.stdout+r.stderr);assert 'comparisons=100000'in r.stdout
assert hashlib.sha256(source.read_bytes()).hexdigest()==digest
report={'passed':True,'source_sha256':digest,'runs':runs,'binary_input_constraints':[],'four_state_comparisons':100000,'event_path':'Direct conditional boundary and row selection.'};(a.out/'summary.json').write_text(json.dumps(report,indent=2)+'\n');print({'passed':True,'proofs':len(runs),'four_state_comparisons':100000})
