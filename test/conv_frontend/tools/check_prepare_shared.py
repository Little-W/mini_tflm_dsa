#!/usr/bin/env python3
"""检查通道余量计算、窗口保存关系与配置核列边界。"""
import argparse
from pathlib import Path
import re
import shlex
import hashlib
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]


def run(name, source, proof, out, source_root):
    sv, ys, log = [out / (name + suffix) for suffix in ('.sv', '.ys', '.log')]
    sv.write_text(source)
    ys.write_text('read_slang --top proof ' + shlex.join([str(sv), str(source_root / 'rtl/common/add_equal.sv')]) + '\n'
                  'prep -top proof -flatten\nasync2sync\nopt\ncheck -assert\n' + proof)
    with log.open('w') as stream:
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                 '--worker', str(ys)], stdout=stream,
                                stderr=subprocess.STDOUT, timeout=90)
    text = log.read_text()
    if result.returncode or 'SUCCESS!' not in text:
        raise RuntimeError(str(log))
    return dict(name=name, passed=True, source_sha256=hashlib.sha256(sv.read_bytes()).hexdigest())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out, source_root = args.out.resolve(), args.source_root.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current_path = source_root / 'rtl/npu/conv/conv_im2col_frontend.sv'
    reference_path = args.reference_root.resolve() / 'rtl/npu/conv/conv_im2col_frontend.sv'
    current, reference = current_path.read_text(), reference_path.read_text()
    current_sha = hashlib.sha256(current_path.read_bytes()).hexdigest()
    reference_sha = hashlib.sha256(reference_path.read_bytes()).hexdigest()
    fragments = []
    for name, source in [('current', current), ('reference', reference)]:
        start = source.index('  for (genvar source = 0; source < 2; source++) begin : g_tile_group_range')
        stop = source.index('\n  assign incoming_tap_wrap', start)
        fragments.append(f'''module {name} #(parameter int SIZE=16, RW=$clog2(SIZE+1))(
 input logic [15:0] group_c,window_next_ch,ch0_q,
 input logic [RW-1:0] tile_cols,
 output logic [1:0] incoming_tile_group_fits);
 localparam int TILE_COUNT_W=$clog2(SIZE+1);
 typedef struct packed {{logic[15:0]group_c;}} cfg_t;
 cfg_t c;
 logic[16:0]initial_group_remaining,window_group_remaining_q;
 assign c.group_c=group_c;
 assign initial_group_remaining={{1'b0,group_c}}-{{1'b0,ch0_q}};
 assign window_group_remaining_q={{1'b0,group_c}}-{{1'b0,window_next_ch}};
''' + source[start:stop] + '\nendmodule\n')
    rows = []
    cases = [(size, (size+1-1).bit_length()) for size in
             (1,2,3,4,7,8,16,31,255,256,32767,32768,65535,65536)]
    cases += [(16,1),(16,17),(256,16)]
    for size, width in cases:
        proof = f'''module proof(input logic[15:0] group_c,window_next_ch,ch0_q,
 input logic[{width-1}:0]tile_cols,output logic equivalent);
 logic[1:0]result_current,result_reference;
 current #(.SIZE({size}),.RW({width}))u_current(.*,.incoming_tile_group_fits(result_current));
 reference #(.SIZE({size}),.RW({width}))u_reference(.*,.incoming_tile_group_fits(result_reference));
 assign equivalent=result_current==result_reference;
 endmodule\n'''
        rows.append(run(f'range_s{size}_rw{width}', ''.join(fragments)+proof,
                        'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n', out, source_root))
    window_start = current.index('  always_ff @(posedge clk or negedge rst_n) begin',
                                 current.index('// 每个空间位置的首个有效卷积核位置'))
    window_stop = current.index('\n  end\n', window_start) + len('\n  end\n')
    window = current[window_start:window_stop]
    # 保留实际更新条件和参与不变量的寄存器赋值。
    window = re.sub(r'^      (?!window_next_valid\b|window_next_ch\b|window_group_remaining_q\b)\w+\s*<=.*?;\n',
                    '', window, flags=re.M)
    sequential = '''module proof(input logic clk,rst_n,cfg_valid,cfg_ready,
 input logic row_base_valid,coordinate_address_valid,next_position_o_equal,
 input logic[21:0]state,input logic[4:0]rows_q,
 input logic[31:0]next_position,position_count,input logic[15:0]ch0_q,
 input logic[15:0]cfg_group_c,cfg_kernel_w,
 output logic equivalent);
 localparam int TILE_COUNT_W=5;
 localparam logic[21:0]FETCH=22'h040000,WAIT_WORD=22'h080000,STREAM=22'h100000,ZERO_STREAM=22'h200000;
 typedef struct packed {logic[15:0]group_c,kernel_w;} cfg_t;
 cfg_t c;
 logic window_next_valid,configured;
 logic[15:0]window_next_ch,last_kernel_col_q;
 logic[16:0]initial_group_remaining,window_group_remaining_q;
 assign initial_group_remaining={1'b0,c.group_c}-{1'b0,ch0_q};
 always_ff @(posedge clk or negedge rst_n) begin
   if(!rst_n)begin c<='0;configured<=0;last_kernel_col_q<=0;end
   else if(cfg_valid&&cfg_ready)begin
     c.group_c<=cfg_group_c;c.kernel_w<=cfg_kernel_w;
     last_kernel_col_q<=cfg_kernel_w-16'd1;configured<=1;
   end
 end
''' + window + '''
 assign equivalent=(!window_next_valid || window_group_remaining_q==({1'b0,c.group_c}-{1'b0,window_next_ch})) &&
                   (!configured || last_kernel_col_q==(c.kernel_w-16'd1));
endmodule\n'''
    rows.append(run('saved_configuration', sequential,
                    'sat -seq 2 -set-at 1 rst_n 0 -set-def-inputs -set-init-def -prove-skip 1 -prove equivalent 1 -verify\n'
                    'sat -seq 1 -tempinduct-inductonly -maxsteps 1 -prove equivalent 1 -verify\n', out, source_root))
    if current_sha != hashlib.sha256(current_path.read_bytes()).hexdigest() or reference_sha != hashlib.sha256(reference_path.read_bytes()).hexdigest():
        raise RuntimeError('Source changed during verification')
    report = dict(passed=True, runs=rows, range_inputs_unconstrained=True,
                  sequential_reset_steps=2, sequential_induction_steps=1,
                  source_sha256=current_sha,
                  reference_sha256=reference_sha)
    (out/'summary.json').write_text(json.dumps(report, indent=2)+'\n')
    print('PREPARATION_SHARE_PASS',len(rows),out/'summary.json')


if __name__ == '__main__':
    main()
