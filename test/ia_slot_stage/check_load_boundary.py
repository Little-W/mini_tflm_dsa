#!/usr/bin/env python3
"""证明 IA 下一游标的保存关系，并检查行数并行比较。"""
import argparse,hashlib,json,re,shlex,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
p=argparse.ArgumentParser();p.add_argument('--tool-root',type=Path,default=ROOT);p.add_argument('--source-root',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
source=a.source_root/'rtl/npu/loaders/ia_loader_ctrl.sv';text=source.read_text();digest=hashlib.sha256(source.read_bytes()).hexdigest();runs=[]
def between(start,end):
 i=text.index(start);return text[i:text.index(end,i)]
def proof(name,content,opts,commands):
 sv=a.out/(name+'.sv');ys=a.out/(name+'.ys');log=a.out/(name+'.log');sv.write_text(content)
 ys.write_text('read_slang --top proof -DSYNTHESIS=1 -DXILINX_FPGA=1 '+opts+' '+shlex.quote(str(sv))+'\nprep -top proof -flatten\nasync2sync\nopt\ncheck -assert\n'+commands)
 with log.open('w')as f:r=subprocess.run([sys.executable,str(a.tool_root.resolve()/'scripts/fpga/open_fpga_synth.py'),'--worker',str(ys)],stdout=f,stderr=subprocess.STDOUT,timeout=90)
 if r.returncode or 'SUCCESS!'not in log.read_text():raise RuntimeError(str(log))
 runs.append({'name':name,'passed':True,'source_sha256':hashlib.sha256(sv.read_bytes()).hexdigest(),'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()})
start=text.index('  // load_ia_cursor 与 load_tiles_done 管理');start=text.index('  always_ff',start);stop=text.index('  // slot 指针管理',start);counter=text[start:stop];counter=counter[:counter.rfind('  // =====================================================================')]
for target in ('load_cursor_row_base','load_cursor_p0','load_l2_is_last'):
 counter=re.sub(r'\b'+target+r'\s*<=.*?;','',counter)
look_end='    localparam int p_boundary_groups' if '    localparam int p_boundary_groups' in text else '    assign load_last_equal_o_regular'
look=between('    logic [LOAD_CNT_W-1:0] cursor_after_q;',look_end)
module='''module proof #(parameter int LOAD_CNT_W=7)(
 input logic clk,rst_n,retirement_l1,prefetch_active,prefetch_entering,tl_tile_done,
 input logic[2:0]state,output logic equivalent);
 localparam logic[2:0]S_INIT=1,S_LOAD=2,S_SEND=3;
 logic[LOAD_CNT_W-1:0]load_ia_cursor,load_tiles_done;
 wire[LOAD_CNT_W-1:0]load_ia_cursor_cnt=load_ia_cursor;
'''+counter+look+'''assign equivalent=cursor_after_q==(load_ia_cursor+LOAD_CNT_W'(1));
endmodule
'''
for w in range(1,10):proof('cursor_w'+str(w),module,'-GLOAD_CNT_W='+str(w),'sat -seq 2 -set-at 1 rst_n 0 -prove-skip 1 -prove equivalent 1 -verify\nsat -seq 1 -tempinduct-inductonly -maxsteps 1 -prove equivalent 1 -verify\n')
rows=between('  if (p_saved_load_boundary) begin : g_parallel_rows_match','  assign request_rows = load_rows_cur;')
rowmodule='''module row_compare #(parameter int SIZE=16,REG_WIDTH=32,parameter bit p_saved_load_boundary=1)(
 input logic load_is_last_row_tile,input logic[REG_WIDTH-1:0]rsp_rows_last_tile,
 input logic[$clog2(SIZE+1)-1:0]request_rows_target,output logic equivalent);
 localparam int ROW_CNT_W=$clog2(SIZE+1);
 logic request_rows_matches;
 wire[REG_WIDTH-1:0]load_rows_cur=load_is_last_row_tile?rsp_rows_last_tile:REG_WIDTH'(SIZE);
'''+rows+'''assign equivalent=request_rows_matches===(request_rows_target==load_rows_cur[ROW_CNT_W-1:0]);
endmodule
'''
for size,rw in ((2,8),(4,16),(8,16),(16,32),(32,32),(16,64)):
 content=rowmodule+f'''module proof(input logic load_is_last_row_tile,input logic[{rw-1}:0]rsp_rows_last_tile,input logic[{size.bit_length()-1}:0]request_rows_target,output logic equivalent);
 row_compare #(.SIZE({size}),.REG_WIDTH({rw}))dut(.*);endmodule
'''
 proof(f'rows_s{size}_r{rw}',content,'','sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
sv=a.out/'rows_event.sv';sv.write_text(rowmodule);tb=a.out/'rows_four_state.sv';tb.write_text('''module tb;
 logic last_row;logic[63:0]rows;logic[5:0]target;wire[5:0]equal_bits;
'''+''.join(f'row_compare #(.SIZE({s}),.REG_WIDTH({w}),.p_saved_load_boundary(0))u{i}(.load_is_last_row_tile(last_row),.rsp_rows_last_tile(rows[{w-1}:0]),.request_rows_target(target[{s.bit_length()-1}:0]),.equivalent(equal_bits[{i}]));\n'for i,(s,w)in enumerate(((2,8),(4,16),(8,16),(16,32),(32,32),(16,64))))+'''initial begin
 for(integer sample=0;sample<24000;sample++)begin
 last_row=$random;rows={$random,$random};target=$random;
 if(sample%3==0)last_row=1'bx;
 if(sample%5==0)rows[sample%64]=1'bz;
 if(sample%7==0)target[sample%6]=1'bx;
 #1;if(equal_bits!==6'b111111)$fatal(1,"row equality propagation");
 end
 $display("IA_ROW_FOUR_STATE_PASS checks=144000");$finish;
end endmodule
''')
binary=a.out/'rows_event.vvp';subprocess.run(['/home/agent/.local/bin/iverilog','-g2012','-s','tb','-o',str(binary),str(sv),str(tb)],check=True,capture_output=True)
r=subprocess.run(['/home/agent/.local/bin/vvp',str(binary)],check=True,capture_output=True,text=True);(a.out/'rows_event.log').write_text(r.stdout+r.stderr);assert 'checks=144000'in r.stdout
assert hashlib.sha256(source.read_bytes()).hexdigest()==digest
report={'passed':True,'source_sha256':digest,'runs':runs,'binary_input_constraints':[],'cursor_relation':'Saved counter equals current cursor plus one modulo LOAD_CNT_W on every cycle.','reset_steps':2,'unbounded_induction_steps':1,'four_state_comparisons':144000,'event_path':'Original row selection followed by equality.'};(a.out/'summary.json').write_text(json.dumps(report,indent=2)+'\n');print({'passed':True,'proofs':len(runs),'four_state_comparisons':144000})
