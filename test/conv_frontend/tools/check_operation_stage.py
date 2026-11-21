#!/usr/bin/env python3
"""证明描述符操作类型对应的坐标、地址及核位置运算。"""
import argparse,hashlib,json,shlex,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
PORTS='''input logic incoming_next_position_fast,incoming_next_tile_fast,incoming_skip_tap,incoming_q_equal,incoming_tap_wrap,
input logic incoming_position_previous_row,incoming_position_forward_tap,incoming_position_backward_tap,incoming_position_same_tap,row_wrap,
input logic [31:0] tap0,window_next_tap,row_base_pixel,next_row_pixel,window_next_pixel,tap_pair_pixels,
input logic signed [32:0] tap_wrap_pixels,row_wrap_dx,tap_wrap_dx,
input logic signed [COORD_W-1:0] row_base_ix,row_base_iy,window_next_ix,window_next_iy,tap_pair_dx,
input logic [15:0] kx0_q,ky0_q,window_next_kx,window_next_ky,dilation_w,dilation_h,stride_w,stride_h,
input logic [31:0] row_base_addr,row_group_base,window_next_addr,window_next_group_base,next_row_addr,next_row_group_base,
input logic [31:0] tap_step_bytes,tap_wrap_bytes,tap_pair_bytes,
'''
DECL='''typedef struct packed { logic [15:0] dilation_w,dilation_h,stride_w,stride_h; } cfg_t;
cfg_t c;
assign c='{dilation_w,dilation_h,stride_w,stride_h};
wire [31:0] kx0={16'd0,kx0_q},ky0={16'd0,ky0_q};
logic [9:0] prepared_word_select,committing_operation;
logic [8:0] prepared_padding_select;
logic signed [COORD_W-1:0] prepared_coordinate_x,prepared_coordinate_y,prepared_coordinate_dx,prepared_coordinate_dy;
logic [1:0] prepared_coordinate_carry;
logic signed [COORD_W-1:0] committing_coordinate_dx,committing_coordinate_dy;
logic [1:0] committing_coordinate_carry;
logic [31:0] prepared_tap_base,prepared_kernel_x_base,prepared_kernel_y_base,prepared_pixel_base,prepared_pixel_delta;
logic signed [2:0] prepared_tap_delta,prepared_kernel_x_delta,prepared_kernel_y_delta;
logic prepared_pixel_carry;
logic signed [2:0] committing_tap_delta,committing_kernel_x_delta,committing_kernel_y_delta;
logic [31:0] committing_pixel_delta,committing_kernel_x_base;
logic committing_pixel_carry;
logic [31:0] committing_tap,committing_kernel_x,committing_kernel_y,committing_pixel;
logic [1:0][31:0] prepared_address;
logic [31:0] prepared_address_delta,committing_address_delta;
logic prepared_address_carry,committing_address_carry;
logic [9:0][1:0][31:0] prepared_address_candidate;
logic [9:0][31:0] prepared_address_delta_candidate;
logic [9:0] prepared_address_carry_candidate;
logic [6:0][1:0][31:0] incoming_address_left,incoming_address_right;
logic [6:0] incoming_address_carry;
typedef struct packed {
 logic [31:0] tap,kernel_x,kernel_y,pixel;
 logic signed [2:0] tap_delta,kernel_x_delta,kernel_y_delta;
 logic [31:0] pixel_delta;
 logic pixel_carry;
 logic [9:0] operation;
 logic row_wrap;
} tile_t;
tile_t prepared_tile_q;
for(genvar candidate=0;candidate<7;candidate++)begin
 assign incoming_address_carry[candidate]=candidate==5||candidate==6;
 for(genvar base=0;base<2;base++)begin
  assign incoming_address_left[candidate][base]=candidate<4 ?
    (base==0?row_base_addr:row_group_base):(base==0?window_next_addr:window_next_group_base);
  assign incoming_address_right[candidate][base]=candidate==1?tap_wrap_bytes:candidate==3?tap_pair_bytes:
    candidate==2?tap_step_bytes<<1:candidate==5?~tap_step_bytes:candidate==6?~tap_pair_bytes:tap_step_bytes;
 end
end
'''
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def extract(text,start,stop):
 i=text.index(start);j=text.index(stop,i);return text[i:j]
def build(text,label,old):
 select=extract(text,'  always_comb begin\n    prepared_padding_select =','  always_comb begin\n    prepared_tap_base =')
 if old:
  coord=extract(text,'  always_comb begin\n    prepared_coordinate_x =','  for (genvar axis = 0; axis < 2; axis++) begin : g_commit_coordinate')
  geo=extract(text,'  always_comb begin\n    prepared_tap_base =','  // 描述符寄存级保存已选择的两个基地址')
  address=extract(text,'  assign prepared_address_candidate[0]','  for (genvar address_port = 0;')
 else:
  coord=extract(text,'  always_comb begin\n    prepared_coordinate_x =','  for (genvar axis = 0; axis < 2; axis++) begin : g_commit_coordinate')
  geo=extract(text,'  always_comb begin\n    prepared_tap_base =','  // 两个地址共用同一来源')
  address=extract(text,'  // 两个地址共用同一来源','  for (genvar address_port = 0;')
 lines=[f'module {label} #(parameter int COORD_W=35)(',PORTS,'output logic [192+2*COORD_W:0] result);',DECL,coord,select,geo,address,
 "always_comb begin prepared_tile_q='0;",
 ' prepared_tile_q.tap=prepared_tap_base;prepared_tile_q.kernel_x=prepared_kernel_x_base;prepared_tile_q.kernel_y=prepared_kernel_y_base;prepared_tile_q.pixel=prepared_pixel_base;']
 if old:
  lines += [' prepared_tile_q.tap_delta=prepared_tap_delta;prepared_tile_q.kernel_x_delta=prepared_kernel_x_delta;prepared_tile_q.kernel_y_delta=prepared_kernel_y_delta;',
    ' prepared_tile_q.pixel_delta=prepared_pixel_delta;prepared_tile_q.pixel_carry=prepared_pixel_carry;']
 else:lines += [' prepared_tile_q.operation=prepared_word_select;prepared_tile_q.row_wrap=row_wrap;']
 lines+=['end','logic [COORD_W-1:0] coordinate_x,coordinate_y;logic [31:0] address,group_address;']
 prefix='prepared' if old else 'committing'
 lines += [f'assign coordinate_x=prepared_coordinate_x+{prefix}_coordinate_dx+COORD_W\'({prefix}_coordinate_carry[0]);',
  f'assign coordinate_y=prepared_coordinate_y+{prefix}_coordinate_dy+COORD_W\'({prefix}_coordinate_carry[1]);',
  f'assign address=prepared_address[0]+{prefix}_address_delta+32\'({prefix}_address_carry);',
  f'assign group_address=prepared_address[1]+{prefix}_address_delta+32\'({prefix}_address_carry);',
  "assign result={((prepared_word_select&(prepared_word_select-10'd1))==0&&prepared_word_select!=0),coordinate_x,coordinate_y,address,group_address,committing_tap,committing_kernel_x,committing_kernel_y,committing_pixel};",
  'endmodule']
 return '\n'.join(lines)
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--source-root',type=Path,required=True);ap.add_argument('--reference-root',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);a=ap.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=True)
 current=a.source_root/'rtl/npu/conv/conv_im2col_frontend.sv';reference=a.reference_root/'rtl/npu/conv/conv_im2col_frontend.sv'
 hashes={'current':digest(current),'reference':digest(reference)}
 source=out/'operation.sv';source.write_text(build(reference.read_text(),'reference',True)+'\n'+build(current.read_text(),'current',False)+f'''\nmodule proof #(parameter int COORD_W=35)(
{PORTS}output logic equivalent);
logic [192+2*COORD_W:0] reference_result,current_result;
reference #(.COORD_W(COORD_W)) ref_i(.result(reference_result),.*);
current #(.COORD_W(COORD_W)) new_i(.result(current_result),.*);
assign equivalent=(reference_result==current_result)&&reference_result[192+2*COORD_W];
endmodule
''')
 runs=[]
 for width in (33,35,40):
  script=out/f'w{width}.ys';log=out/f'w{width}.log';script.write_text(f'read_slang --top proof -GCOORD_W={width} '+shlex.quote(str(source))+'\nprep -top proof -flatten\nsat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
  with log.open('w')as f:r=subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],stdout=f,stderr=subprocess.STDOUT,timeout=180)
  passed=r.returncode==0 and'no model found: SUCCESS!'in log.read_text();runs.append({'coordinate_width':width,'passed':passed,'result_bits':192+2*width,'log_sha256':digest(log)})
  if not passed:raise RuntimeError(str(log))
 if hashes!={'current':digest(current),'reference':digest(reference)}:raise RuntimeError('Source changed')
 report={'passed':True,'source_sha256':hashes,'runs':runs,'operation_onehot':True,'binary_inputs_constrained':False,'configuration_scope':'Capture and commit use the same task coefficients'}
 (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n');print(report)
if __name__=='__main__':main()
