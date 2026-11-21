#!/usr/bin/env python3
"""证明并行字边界和预测器配置取整的完整位宽等价性。"""
import argparse
import hashlib
import json
import re
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = 'rtl/npu/conv/conv_im2col_frontend.sv'
PREDICTOR = 'rtl/npu/dma/cache/conv_next_use_predictor.sv'


def word_unit(source):
    start = re.search(r'  if \(LANES[^\n]+\) begin : g_short_word_advance', source).start()
    end = source.index('  // 连续读取只在耗尽当前缓存字时发起', start) if '  // 连续读取只在耗尽当前缓存字时发起' in source else source.index('  assign stream_context=', start)
    select_start = source.index('  assign chunk_selected[0]')
    select_end = source.index('  logic incoming_request,', select_start)
    body = '''module word_comparison #(parameter int LANES=4,p_word_shift=2,
 parameter int CHUNK_COUNT_W=$clog2(LANES+1),p_cache_read_bytes=1<<p_word_shift)(
input conv_im2col_pkg::conv_cfg_t c,input logic[31:0] addr,word_addr,
input logic word_valid,waiting,input logic[LANES-1:0] chunk_lane_allowed,
output logic equivalent);
localparam logic WAIT_WORD=1'b1;
logic state;
logic[CHUNK_COUNT_W-1:0] chunk_count;
logic[LANES:0] chunk_selected,step_word_boundary,step_saved_hit;
logic[p_word_shift+1:0] byte_offset_sum;
logic[31:0] next_byte_addr;
logic word_boundary,next_byte_saved_hit;
logic expected_boundary,expected_hit;
assign state=waiting;
always_comb begin
 chunk_count='0;
 for(int lane=0;lane<LANES;lane++)
  if(chunk_lane_allowed[lane]) chunk_count=CHUNK_COUNT_W'(lane+1);
end
assign next_byte_addr=addr+(32'(chunk_count)<<c.input_s16);
assign byte_offset_sum={2'b0,addr[p_word_shift-1:0]}+
 ((p_word_shift+2)'(chunk_count)<<c.input_s16);
''' + source[select_start:select_end] + source[start:end] + '''
assign expected_boundary=byte_offset_sum>=(p_word_shift+2)'(p_cache_read_bytes);
assign expected_hit=waiting ? next_byte_addr[31:p_word_shift]==addr[31:p_word_shift] :
 word_valid && word_addr=={next_byte_addr[31:p_word_shift],{p_word_shift{1'b0}}};
assign equivalent=word_boundary==expected_boundary && next_byte_saved_hit==expected_hit;
endmodule
'''
    if 'state[19]' in source[start:end] or 'state[$clog2(WAIT_WORD)]' in source[start:end]:
        body = body.replace("localparam logic WAIT_WORD=1'b1;\nlogic state;",
                            "localparam logic[21:0] WAIT_WORD=22'h080000;\nlogic[21:0] state;")
        body = body.replace('assign state=waiting;', "assign state=waiting ? WAIT_WORD : 22'h000001;")
    return body


def predictor_unit(source):
    start = source.index('  logic [32:0] cfg_block_round')
    end = source.index('  assign cfg_r_shift', start)
    saved = source.find('  // 配置乘法等待期间保存取整和', start, end)
    if saved >= 0:
        end = saved
    return '''module predictor_comparison(input logic[31:0] cfg_points_q,block_rows_q,
output logic equivalent);
''' + source[start:end] + '''
assign equivalent=cfg_block_round==({1'b0,cfg_points_q}+{1'b0,block_rows_q}-33'd1);
endmodule
'''


def predictor_coordinate_unit(source):
    start = source.index('  // 坐标减法保持完整三十四位')
    end = source.index('  assign ny_s0', start)
    return '''module predictor_coordinate_comparison(
input logic [32:0] y_pad_q,x_pad_q,input logic [31:0] mul_y_s0,mul_x_s0,y_limit_q,x_limit_q,
output logic equivalent);
logic [1:0][32:0] coordinate_pad;
logic [1:0][31:0] coordinate_product;
logic [1:0][33:0] coordinate_difference,expected_difference;
logic [1:0] expected_before;
''' + source[start:end] + '''
assign expected_difference[0]={1'b0,y_pad_q}-{2'b0,mul_y_s0};
assign expected_difference[1]={1'b0,x_pad_q}-{2'b0,mul_x_s0};
assign expected_before[0]=expected_difference[0]<{2'b0,y_limit_q};
assign expected_before[1]=expected_difference[1]<{2'b0,x_limit_q};
assign equivalent=coordinate_difference==expected_difference && coordinate_before_limit==expected_before;
endmodule
'''


def epoch_unit(source):
    start = source.index('  for (genvar candidate = 0; candidate < 5; candidate++) begin : g_epoch_candidate')
    end = source.index('  assign stream_channel_i_a', start)
    select_start = source.index('  assign chunk_selected[0]')
    select_end = source.index('  logic incoming_request,', select_start)
    return '''module epoch_comparison #(parameter int LANES=4,CHUNK_COUNT_W=$clog2(LANES+1))(
input conv_im2col_pkg::conv_cfg_t c,input logic[15:0] ch_q,
input logic[LANES-1:0] chunk_lane_allowed,
input logic[4:0][31:0] epoch_i_a,epoch_i_b,output logic equivalent);
logic [LANES:0] chunk_selected;
logic [4:0][31:0] epoch_o_sum;
logic [4:0] unused_epoch_carry;
logic epoch_i_carry;
logic [CHUNK_COUNT_W-1:0] chunk_count;
assign epoch_i_carry=1'b0;
always_comb begin
 chunk_count='0;
 for(int lane=0;lane<LANES;lane++)
  if(chunk_lane_allowed[lane]) chunk_count=CHUNK_COUNT_W'(lane+1);
end
''' + source[select_start:select_end] + source[start:end] + '''
assign equivalent=epoch_o_sum[3]==(32'(c.group_offset)+32'(ch_q)+32'(chunk_count));
endmodule
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,default=ROOT)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    source_root=args.source_root.resolve();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    frontend=(source_root/FRONTEND).read_text();predictor=(source_root/PREDICTOR).read_text()
    cases=[(f'word_l{lanes}_b{bits}','word_comparison',word_unit(frontend),
            [f'-GLANES={lanes}',f'-Gp_word_shift={bits}']) for lanes in (1,2,4,5,7,8) for bits in (2,3,4)]
    cases.append(('predictor_round','predictor_comparison',predictor_unit(predictor),[]))
    if '  // 坐标减法保持完整三十四位' in predictor:
        cases.append(('predictor_coordinate','predictor_coordinate_comparison',
                      predictor_coordinate_unit(predictor),[]))
    if 'begin : g_stream_steps' in frontend:
        cases.extend((f'epoch_l{lanes}','epoch_comparison',epoch_unit(frontend),[f'-GLANES={lanes}'])
                     for lanes in (1,2,4,5,7,8))
    results=[]
    for name,top,body,options in cases:
        target=out/(name+'.sv');target.write_text(body)
        paths=[source_root/'rtl/npu/conv/conv_im2col_pkg.sv',source_root/'rtl/common/add_equal.sv',
               source_root/'rtl/common/parallel_prefix_add.sv',target]
        script=out/(name+'.ys');log=out/(name+'.log')
        script.write_text('read_slang --top '+top+' '+' '.join(options)+' '+
            ' '.join(shlex.quote(str(p)) for p in paths)+'\nprep -top '+top+
            ' -flatten\nsat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],
                           cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True)
        results.append({'case':name,'passed':True,'log':str(log)})
        print('FRONTEND_CONTROL_EQUIVALENCE_PASS',name,flush=True)
    (out/'summary.json').write_text(json.dumps({'passed':True,'cases':results,
        'source_sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in
         [source_root/FRONTEND,source_root/PREDICTOR,source_root/'rtl/common/parallel_prefix_add.sv']}},
        ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':
    main()
