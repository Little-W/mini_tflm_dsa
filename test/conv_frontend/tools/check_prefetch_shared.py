#!/usr/bin/env python3
"""证明预取横坐标共用与配置像素步长的完整位宽结果。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]


def extract(text, start, stop):
    first = text.index(start)
    return text[first:text.index(stop, first)]


PORTS = '''input logic windowed,pf_window_row_valid_q,
 input logic[15:0]input_c,input_w,input_h,group_c,kernel_w,kernel_h,dilation_w,dilation_h,stride_w,stride_h,output_w,
 input logic[31:0]pfa_rows,pfa_cols,pfa_output_x,prefetch_next_x,prefetch_wrapped_x,pf_y_base_q,pf_y_wrapped_q,
 input logic[31:0]pf_kernel_advance_q,pf_step_q,pf_distance_q,
 input logic[15:0]last_output_col_q,second_last_col_q,
 input logic signed[COORD_W-1:0]pfa_x,pfa_y,
 input logic signed[32:0]pf_window_dx_q,pf_fragment_dx_q,
 input logic[16:0]pf_window_dy_q,
'''


def prefetch_module(text, name):
    extra = ''
    if 'assign pf_horizontal_sum' in text:
        extra = extract(text, '  assign pf_window_ahead =',
                        '  // 较大通道数按缓存行预测后续像素')
    body = extract(text, '    pf_step=pf_step_q;', '    pf_channel=epoch_o_sum[4];')
    return f'''module {name} #(parameter int COORD_W=35)(
{PORTS}output logic[68:0]result);
 typedef struct packed {{logic windowed;logic[15:0]input_c,input_w,input_h,group_c,kernel_w,kernel_h,dilation_w,dilation_h,stride_w,stride_h,output_w;}} cfg_t;
 cfg_t c;
 assign c={{windowed,input_c,input_w,input_h,group_c,kernel_w,kernel_h,dilation_w,dilation_h,stride_w,stride_h,output_w}};
 logic pf_stream_lookahead,pf_window_ahead,pf_ahead_two,pf_wrap_once,pf_wrap_twice,pf_coordinate_valid;
 logic[31:0]pf_x,pf_y,pf_step,pf_distance;
 logic signed[COORD_W-1:0]pf_wrap_x,pf_window_x,pf_window_y,pf_horizontal_sum,pf_horizontal_delta;
 assign pf_stream_lookahead=c.windowed&&c.input_c>=16'd16;
{extra}
 always_comb begin
{body}
 end
 assign result={{pf_x,pf_y,pf_coordinate_valid,pf_window_ahead,pf_ahead_two,pf_wrap_once,pf_wrap_twice}};
endmodule
'''


def run(name, source, out):
    sv, ys, log = (out/(name+extension) for extension in ('.sv','.ys','.log'))
    sv.write_text(source)
    ys.write_text('read_slang --top proof '+shlex.quote(str(sv))+
                  '\nprep -top proof -flatten\ncheck -assert\n'
                  'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
    with log.open('w') as stream:
        result=subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),
                               '--worker',str(ys)],stdout=stream,stderr=subprocess.STDOUT,timeout=180)
    if result.returncode or 'SUCCESS!' not in log.read_text():
        raise RuntimeError(str(log))
    return {'name':name,'passed':True,'source_sha256':hashlib.sha256(sv.read_bytes()).hexdigest(),
            'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,required=True)
    parser.add_argument('--reference-root',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    paths=[root/'rtl/npu/conv/conv_im2col_frontend.sv' for root in (args.source_root,args.reference_root)]
    current,reference=[path.read_text() for path in paths]
    hashes=[hashlib.sha256(path.read_bytes()).hexdigest() for path in paths]
    pair=prefetch_module(current,'current')+prefetch_module(reference,'reference')
    rows=[]
    for width in (33,35,40):
        wrapper=f'''module proof # (parameter int COORD_W={width})({PORTS}output logic equivalent);
 logic[68:0]current_result,reference_result;
 current #(.COORD_W(COORD_W))u_current(.*,.result(current_result));
 reference #(.COORD_W(COORD_W))u_reference(.*,.result(reference_result));
 assign equivalent=current_result==reference_result;
endmodule
'''
        rows.append(run('prefetch_w'+str(width),pair+wrapper,args.out))
        equations=[]
        for original,result in [('row_pair_dx','row_pair_dx_sum'),('row_wrap_pixels','row_wrap_pixel_sum'),('tap_wrap_pixels','tap_wrap_pixel_sum')]:
            block=extract(reference,'      if (address_step_phase==2)', '      end else if (address_step_phase==1)')
            rhs=re.search(r'\b'+original+r'\s*<=\s*([^;]+);',block).group(1)
            assignment=re.search(r'  assign '+result+r'\s*=.*?;',current,re.S).group()
            equations += [assignment, f'wire signed[32:0]old_{result}={rhs};']
        arithmetic=f'''module proof #(parameter int COORD_W={width})(
 input logic signed[32:0]row_wrap_dx,tap_wrap_dx,row_y_pixels,tap_y_pixels,
 input logic[15:0]stride_w,output logic equivalent);
 typedef struct packed {{logic[15:0]stride_w;}}cfg_t;
 cfg_t c;assign c.stride_w=stride_w;
 logic signed[32:0]row_pair_dx_sum,row_wrap_pixel_sum,tap_wrap_pixel_sum;
'''+ '\n'.join(equations)+'''
 assign equivalent={row_pair_dx_sum,row_wrap_pixel_sum,tap_wrap_pixel_sum}==
                   {old_row_pair_dx_sum,old_row_wrap_pixel_sum,old_tap_wrap_pixel_sum};
endmodule
'''
        rows.append(run('configuration_sum_w'+str(width),arithmetic,args.out))
    if hashes!=[hashlib.sha256(path.read_bytes()).hexdigest() for path in paths]:
        raise RuntimeError('Source changed during verification')
    report={'passed':True,'runs':rows,'source_sha256':hashes[0],'reference_sha256':hashes[1],
            'input_constraints':[],'coordinate_widths':[33,35,40],
            'prefetch_compared_bits':69,'configuration_compared_bits':99}
    (args.out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print('PREFETCH_SHARED_PASS',len(rows),args.out/'summary.json')


if __name__=='__main__':main()
