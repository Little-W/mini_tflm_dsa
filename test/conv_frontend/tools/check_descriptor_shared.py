#!/usr/bin/env python3
"""证明描述符共享运算及有效坐标历史条目的数据关系。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
SHARED_HEADER = """module proof(
input logic incoming_next_position_fast,incoming_next_tile_fast,incoming_skip_tap,incoming_q_equal,incoming_tap_wrap,
input logic incoming_position_previous_row,incoming_position_forward_tap,incoming_position_backward_tap,incoming_position_same_tap,
input logic [31:0] tap0,window_next_tap,row_base_pixel,next_row_pixel,window_next_pixel,tap_pair_pixels,
input logic signed [32:0] tap_wrap_pixels,
input logic [15:0] kx0_q,ky0_q,window_next_kx,window_next_ky,dilation_w,
output logic equivalent);
typedef struct packed { logic [15:0] dilation_w; } cfg_t;
cfg_t c;
assign c.dilation_w=dilation_w;
wire [31:0] kx0={16'd0,kx0_q};
wire [31:0] ky0={16'd0,ky0_q};
logic [31:0] incoming_tap,incoming_kx,incoming_ky,incoming_pixel;
logic [4:0][31:0] incoming_pixel_candidate;
logic [31:0] incoming_pixel_delta,incoming_pixel_next;
logic [16:0] incoming_pixel_low;
logic [15:0] incoming_pixel_high_zero,incoming_pixel_high_one;
logic unused_incoming_pixel_high_zero_carry,unused_incoming_pixel_high_one_carry;
logic [9:0] prepared_word_select;
logic [8:0] prepared_padding_select;
logic [31:0] prepared_tap_base,prepared_kernel_x_base,prepared_kernel_y_base,prepared_pixel_base,prepared_pixel_delta;
logic signed [2:0] prepared_tap_delta,prepared_kernel_x_delta,prepared_kernel_y_delta;
logic prepared_pixel_carry;
logic [31:0] committing_tap,committing_kernel_x,committing_kernel_y,committing_pixel;
"""
HISTORY_HEADER = """module history_proof (
 input logic clk,rst_n,cfg_valid,cfg_ready,tile_commit,p_fast_valid,
 input logic [4:0] state_index,
 input logic [1:0] p_cache_select,
 input logic [31:0] p0,p_fast_y,p_fast_x,decode_index,decode_outer,decode_inner,
 output logic equivalent
);
 localparam logic[21:0] P_DECODE=22'h000002,P_WAIT=22'h000008;
 logic[21:0]state;
 logic[63:0]p_cache_data[4],p_cache_write_data,reference_data[4];
 logic p_cache_write_enable;
 logic[3:0]valid,entries_equal;
 assign state=22'b1<<state_index;
"""
HISTORY_TAIL = """ always_ff @(posedge clk) begin
  if(!rst_n) begin
   valid<=0;
   for(int i=0;i<4;i++)reference_data[i]<=0;
  end else if(cfg_valid&&cfg_ready)valid<=0;
  else if(!tile_commit) begin
   if(state[$clog2(P_DECODE)]&&p_fast_valid)begin
    valid[p_cache_select]<=1;
    reference_data[p_cache_select]<={p0,16'(p_fast_y),16'(p_fast_x)};
   end else if(state[$clog2(P_WAIT)]&&decode_index==p0)begin
    valid[p_cache_select]<=1;
    reference_data[p_cache_select]<={p0,16'(decode_outer),16'(decode_inner)};
   end
  end
 end
 for(genvar i=0;i<4;i++) assign entries_equal[i]=!valid[i]||p_cache_data[i]==reference_data[i];
 assign equivalent=&entries_equal;
endmodule
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = root / 'rtl/npu/conv/conv_im2col_frontend.sv'
    text = source.read_text()
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    start = text.index('  always_comb begin\n    incoming_tap=tap0;')
    stop = text.index('\n  // 每个字节', start)
    direct = re.sub(r'\bincoming_(?!(?:tap|kx|ky|pixel)\s*=)[\w]+\s*=[^;]*;', '', text[start:stop])
    start = text.index('  assign incoming_pixel_delta =')
    stop = text.index('\n', text.index('    incoming_pixel_low[15:0]};', start)) + 1
    pixel = text[start:stop]
    pixel += '\n'.join(re.findall(r'  assign incoming_pixel_candidate\[\d\][^;]*;', text))
    start = text.index('  always_comb begin\n    prepared_padding_select =')
    stop = text.index('  always_comb begin\n    prepared_tap_base =', start)
    select = text[start:stop]
    start = stop
    stop = text.index('  // 描述符寄存级保存已选择的两个基地址', start)
    shared = text[start:stop]
    for field in ('tap_delta', 'kernel_x_delta', 'kernel_y_delta', 'pixel_delta', 'pixel_carry'):
        shared = shared.replace('prepared_tile_q.' + field, 'prepared_' + field)
    for field in ('tap', 'kernel_x', 'kernel_y', 'pixel'):
        shared = shared.replace('prepared_tile_q.' + field, 'prepared_' + field + '_base')
    shared_file = out / 'shared_descriptor.sv'
    shared_file.write_text(SHARED_HEADER + pixel + '\n' + direct + select + shared +
        'assign equivalent={incoming_tap,incoming_kx,incoming_ky,incoming_pixel}==' +
        '{committing_tap,committing_kernel_x,committing_kernel_y,committing_pixel};\nendmodule\n')
    start = text.index('  assign p_cache_write_enable =')
    stop = text.index('\n  end', text.index('  always_ff @(posedge clk)', start)) + len('\n  end')
    history_file = out / 'history.sv'
    history_file.write_text(HISTORY_HEADER + text[start:stop] + '\n' + HISTORY_TAIL)
    cases = {
        'shared_descriptor': ('proof', shared_file,
            'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n'),
        'history': ('history_proof', history_file,
            'sat -seq 2 -set-at 1 rst_n 0 -set-def-inputs -set-init-def -prove-skip 1 -prove equivalent 1 -verify\n'
            'sat -seq 1 -tempinduct-inductonly -maxsteps 1 -set-def-inputs -set-init-def -prove equivalent 1 -verify\n'),
    }
    rows = []
    for name, (top, proof, commands) in cases.items():
        script, log = out / (name + '.ys'), out / (name + '.log')
        script.write_text('read_slang --top ' + top + ' ' + shlex.quote(str(proof)) + '\n' +
            'prep -top ' + top + ' -flatten\nmemory_map\nopt\ncheck -assert\n' + commands)
        with log.open('w') as stream:
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                '--worker', str(script)], stdout=stream, stderr=subprocess.STDOUT, timeout=90)
        log_text = log.read_text()
        if result.returncode or 'SAT proof finished - no model found: SUCCESS!' not in log_text:
            raise RuntimeError('Descriptor proof did not complete: ' + str(log))
        if name == 'history' and 'Induction step proven: SUCCESS!' not in log_text:
            raise RuntimeError('History induction did not complete: ' + str(log))
        rows.append(dict(name=name, passed=True, proof_sha256=hashlib.sha256(proof.read_bytes()).hexdigest()))
    if digest != hashlib.sha256(source.read_bytes()).hexdigest():
        raise RuntimeError('Frontend source changed during verification')
    report = dict(passed=True, source_sha256=digest, runs=rows,
        shared_result_bits=128, descriptor_inputs_constrained=False,
        history_entries=4, history_payload_bits=64, history_valid_entries_only=True,
        history_state_encoding='onehot from arbitrary state index',
        history_reset_base_steps=2, history_induction_steps=1)
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print('DESCRIPTOR_SHARED_PASS', out / 'summary.json', flush=True)


if __name__ == '__main__':
    main()
