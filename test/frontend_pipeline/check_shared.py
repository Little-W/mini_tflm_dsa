#!/usr/bin/env python3
"""证明实际运算输入选择与窗口归约差值关系。"""
from pathlib import Path
from source_sections import read_module, declarations, dependencies
import argparse
import hashlib
import json
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source-root', type=Path, default=ROOT)
parser.add_argument('--out', type=Path, default=ROOT/'build/frontend_pipeline/shared_formal')
args = parser.parse_args()
SOURCE, rtl = read_module(args.source_root, 'geometry')
OUT = args.out.resolve()
OUT.mkdir(parents=True, exist_ok=True)
start = rtl.index('  always_comb begin\n    coordinate_a[0]')
end = rtl.index('  assign coordinate_product_sum[0]', start)
shared = rtl[start:end]
blocks = re.findall(r'^  always_comb begin\n.*?^  end\n', shared, re.M | re.S)
coordinate, channel = blocks
model = '''module comparison #(parameter int MODE=0)(
 input conv_im2col_pkg::conv_cfg_t c,cfg,
 input logic [15:0] ox_q,oy_q,kx_q,ky_q,
 input logic [34:0] iy,
 input logic [31:0] cfg_input_hw,cfg_kernel_taps,pixel_index,pf1_pixel,pf0_y,
 input logic [32:0] row_wrap_pixels,tap_wrap_pixels,
 output logic equivalent
);
localparam logic [22:0] ADDRESS=23'h2000;
logic [22:0] state;
logic cfg_valid,cfg_ready;
logic [2:0] cfg_prepare_phase;
logic [1:0] address_step_phase;
logic [3:0] prefetch_phase;
logic [3:0][15:0] coordinate_a,coordinate_b;
logic [1:0][31:0] channel_a;
logic [1:0][15:0] channel_b;
assign cfg_valid=MODE==0;
assign cfg_ready=MODE==0;
assign cfg_prepare_phase=MODE==0?3'd1:MODE==1?3'd2:MODE==2?3'd3:3'd0;
assign address_step_phase=MODE==7?2'd1:2'd0;
assign prefetch_phase=MODE==5?4'd5:MODE==6?4'd6:4'd0;
assign state=MODE==4?ADDRESS:23'h400;
COORDINATE
CHANNEL
always_comb begin
 equivalent=1'b0;
 case(MODE)
 0: equivalent=coordinate_a[0]==c.input_h&&coordinate_b[0]==c.input_w&&
     coordinate_a[1]==c.kernel_h&&coordinate_b[1]==c.kernel_w&&
     coordinate_a[2]==c.output_h&&coordinate_b[2]==c.output_w&&
     coordinate_a[3]==c.stride_h&&coordinate_b[3]==c.input_w;
 1: equivalent=coordinate_a[0]==c.output_w&&coordinate_b[0]==c.stride_w&&
     coordinate_a[1]==c.kernel_w&&coordinate_b[1]==c.dilation_w&&
     coordinate_a[2]==c.dilation_h&&coordinate_b[2]==c.input_w&&
     coordinate_a[3]==c.stride_w&&coordinate_b[3]==c.input_c&&
     channel_a[0]==cfg_input_hw&&channel_b[0]==c.input_c&&
     channel_a[1]==cfg_kernel_taps&&channel_b[1]==c.group_c;
 2: equivalent=coordinate_a[3]==c.dilation_w&&coordinate_b[3]==c.input_c;
 3: equivalent=coordinate_a[0]==ox_q&&coordinate_b[0]==c.stride_w&&
     coordinate_a[1]==oy_q&&coordinate_b[1]==c.stride_h&&
     coordinate_a[2]==kx_q&&coordinate_b[2]==c.dilation_w&&
     coordinate_a[3]==ky_q&&coordinate_b[3]==c.dilation_h&&
     channel_a[0]==pixel_index&&channel_b[0]==c.input_c;
 4: equivalent=coordinate_a[0]==iy[15:0]&&coordinate_b[0]==c.input_w;
 5: equivalent=channel_a[1]==pf0_y&&channel_b[1]==c.input_w&&
     channel_a[0]==pixel_index&&channel_b[0]==c.input_c;
 6: equivalent=channel_a[1]==pf1_pixel&&channel_b[1]==c.input_c&&
     channel_a[0]==pixel_index&&channel_b[0]==c.input_c;
 7: equivalent=channel_a[0]==row_wrap_pixels[31:0]&&channel_b[0]==c.input_c&&
     channel_a[1]==tap_wrap_pixels[31:0]&&channel_b[1]==c.input_c;
 default:;
 endcase
end
endmodule
'''.replace('COORDINATE', coordinate).replace('CHANNEL', channel)
(OUT / 'operand_selection.sv').write_text(model)
WINDOW_SOURCE, rtl = read_module(args.source_root, 'descriptor')
start = rtl.index('  assign negative_group =')
end = rtl.index('  assign position_i_configure =', start)
window = declarations(rtl, ('negative_group', 'target_difference', 'target_difference_match'))+rtl[start:end]
window = window.replace('c.group_c', 'group_c')
window_model = '''module comparison(
 input logic clk,configure,window_write,
 input logic [15:0] input_group,
 input logic [31:0] q0,tile_q0,
 output logic equivalent
);
logic valid;
logic [15:0] group_c,last_group_channel_q;
logic [31:0] window_next_q;
logic [2:0][32:0] reference_targets;
logic [3:0] incoming_tap_match_o_equal;
localparam bit REGISTER_DESCRIPTOR=1'b1;
logic [2:0] target_prepared_match;
wire rst_n=1'b1;
wire window_prepare_write=window_write&&!configure;
wire group_nonzero_q=|group_c;
always_ff @(posedge clk)begin
 if(configure)begin
  group_c<=input_group;
  last_group_channel_q<=input_group-16'd1;
  valid<=1'b0;
 end else if(window_write)begin
  valid<=1'b1;
  window_next_q<=q0;
  reference_targets[0]<={1'b0,q0}+{17'd0,group_c};
  reference_targets[1]<={1'b0,q0}-{17'd0,group_c};
  reference_targets[2]<={1'b0,q0}-{16'd0,group_c,1'b0};
 end
end
WINDOW
logic saved_relation;
assign saved_relation = last_group_channel_q == group_c - 16'd1 && (!valid ||
 (reference_targets[0]=={1'b0,window_next_q}+{17'd0,group_c}&&
  reference_targets[1]=={1'b0,window_next_q}-{17'd0,group_c}&&
  reference_targets[2]=={1'b0,window_next_q}-{16'd0,group_c,1'b0}));
assign equivalent=saved_relation && (!valid ||
 (incoming_tap_match_o_equal[1]==({1'b0,tile_q0}==reference_targets[0])&&
  incoming_tap_match_o_equal[2]==({1'b0,tile_q0}==reference_targets[1])&&
  incoming_tap_match_o_equal[3]==({1'b0,tile_q0}==reference_targets[2])));
endmodule
'''.replace('WINDOW', window)
# 配置始终先于有效窗口，组末值的复位编码与生产寄存器相同。
window_model = window_model.replace('logic [15:0] group_c,last_group_channel_q;',
    "logic [15:0] group_c,last_group_channel_q;\ninitial last_group_channel_q=16'hffff;")
(OUT / 'window_difference.sv').write_text(window_model)
cases = []


def run(name, model_path, options='', sequential=False):
    script = OUT / (name + '.ys')
    log = OUT / (name + '.log')
    sources = dependencies(args.source_root, [args.source_root/'rtl/npu/conv/conv_im2col_pkg.sv',OUT/model_path])
    script.write_text(f'read_slang -D SYNTHESIS=1 --top comparison {options} '+
                     shlex.join(map(str,sources))+'\n'
                     'prep -top comparison -flatten\n' +
                     ('sat -seq 2 -maxsteps 4 -timeout 30 -set-init-zero -tempinduct -verify -prove equivalent 1\n'
                      if sequential else 'sat -verify -prove equivalent 1\n'))
    with log.open('w') as output:
        result = subprocess.run([sys.executable, str(ROOT/'scripts/fpga/open_fpga_synth.py'),
                                 '--worker', str(script)], stdout=output, stderr=subprocess.STDOUT)
    assert result.returncode == 0, log
    cases.append({'name': name, 'passed': True,
                  'script_sha256': hashlib.sha256(script.read_bytes()).hexdigest(),
                  'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest()})


for mode in range(8):
    run(f'operands_{mode}', 'operand_selection.sv', f'-GMODE={mode}')
run('window_difference', 'window_difference.sv', sequential=True)
summary = {'passed': True, 'source_sha256': hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
           'window_source_sha256': hashlib.sha256(WINDOW_SOURCE.read_bytes()).hexdigest(),
           'cases': cases}
(OUT/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
print(json.dumps({'passed': True, 'cases': len(cases), 'source_sha256': summary['source_sha256']}))
