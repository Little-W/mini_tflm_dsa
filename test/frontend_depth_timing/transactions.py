#!/usr/bin/env python3
"""使用独立数值模型验证前端描述符、缓存请求和输出事务，并记录执行周期。"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import runpy
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
TEST = ROOT / 'test/conv_frontend'


def run(command, log, timeout=300):
    with log.open('w') as stream:
        subprocess.run([str(arg) for arg in command], cwd=TEST, stdout=stream,
                       stderr=subprocess.STDOUT, check=True, timeout=timeout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--register-cache-request', type=int, choices=(0, 1), default=1)
    parser.add_argument('--register-descriptor', type=int, choices=(0, 1))
    parser.add_argument('--cache-response-depth', type=int)
    parser.add_argument('--lanes', type=int, default=4)
    parser.add_argument('--cache-line-bytes', type=int, default=16)
    parser.add_argument('--cache-sets', type=int, default=16)
    parser.add_argument('--cases', nargs='+', choices=('s4', 's8', 's16', 'window'),
                        default=['s4', 's8', 's16', 'window'])
    parser.add_argument('--verilator', default=shutil.which('verilator') or 'verilator')
    args = parser.parse_args()
    source_root = args.source_root.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    runner = runpy.run_path(str(TEST / 'tools/run_rtl.py'))
    sources = [Path(path) for path in runner['FILES'] if not str(path).startswith('tests/')]
    sources = [source_root / path.relative_to(ROOT)
               if path.is_relative_to(ROOT) and path.relative_to(ROOT).parts[0] == 'rtl' else path
               for path in sources]
    bench_text = (TEST / 'tests/tb_conv_im2col_frontend.sv').read_text()
    parameters = [".REGISTER_CACHE_REQUEST(1'b" + str(args.register_cache_request) + ")"]
    if args.register_descriptor is not None:
        parameters.append(".REGISTER_DESCRIPTOR(1'b" + str(args.register_descriptor) + ")")
    if args.cache_response_depth is not None:
        parameters.append('.CACHE_RESPONSE_DEPTH(' + str(args.cache_response_depth) + ')')
    bench_text = bench_text.replace('conv_im2col_frontend #(.SIZE(SIZE),',
        'conv_im2col_frontend #(' + ','.join(parameters) + ',.SIZE(SIZE),', 1)
    frontend = (source_root / 'rtl/npu/conv/conv_im2col_frontend.sv').read_text()
    if 'p_saved_group_lanes' in frontend:
        checks = '''    // 保存的通道范围必须在每个使用周期对应完整十七位差值。
    if (LANES<=8) begin : g_saved_channel_range_check
      always @(posedge clk) if (rst_n) begin
        for(int boundary=0;boundary<=dut.p_saved_group_lanes;boundary++) begin
          if(dut.group_range_q[boundary] !==
              (17'(boundary)<({1'b0,dut.c.group_c}-{1'b0,dut.ch_q})))
            $fatal(1,"saved channel range mismatch");
          if(dut.tile_prepared_valid && dut.prepared_tile_q.fast &&
             dut.prepared_tile_q.channel_range[boundary] !==
              (17'(boundary)<({1'b0,dut.c.group_c}-{1'b0,dut.prepared_tile_q.channel[15:0]})))
            $fatal(1,"prepared channel range mismatch");
        end
      end
    end
'''
        bench_text = bench_text.replace('    // 对停顿、行切换和归约尾部检查', checks +
                                       '    // 对停顿、行切换和归约尾部检查', 1)
    if 'typedef enum logic [21:0]' in frontend:
        checks = '''    always @(posedge clk) begin
      if (rst_n && !$onehot(dut.state))
        $fatal(1,"frontend state encoding mismatch");
    end
'''
        bench_text = bench_text.replace('    // 对停顿、行切换和归约尾部检查', checks +
                                       '    // 对停顿、行切换和归约尾部检查', 1)
        observer_index = next(index for index, path in enumerate(sources)
                              if path.name == 'conv_im2col_frontend_observer.sv')
        observer = sources[observer_index].read_text()
        observer = observer.replace('localparam logic [4:0] OBS_IDLE = 5\'d0, OBS_WAIT_WORD = 5\'d19, OBS_ZERO_STREAM = 5\'d21;',
            "localparam logic [21:0] OBS_IDLE = 22'h000001, OBS_WAIT_WORD = 22'h080000, OBS_ZERO_STREAM = 22'h200000;")
        observer = observer.replace('state_cycles[conv_im2col_frontend.state]++',
                                    'state_cycles[$clog2(conv_im2col_frontend.state)]++')
        observer_path = out / 'conv_im2col_frontend_observer.sv'
        observer_path.write_text(observer)
        sources[observer_index] = observer_path
    if 'logic [8:0] padding_select, padding_value;' in frontend:
        checks = '''    always @(posedge clk) begin
      if(rst_n && dut.tile_capture) begin
        if((|(dut.preparing_tile.padding_select & dut.preparing_tile.padding_value)) !== dut.incoming_padding)
          $fatal(1,"prepared padding selection mismatch");
        if((|(dut.preparing_tile.word_select & dut.preparing_tile.word_value)) !== dut.incoming_word_hit)
          $fatal(1,"prepared word selection mismatch");
      end
    end
'''
        if 'logic signed [COORD_W-1:0] coordinate_dx, coordinate_dy;' in frontend:
            checks += '''    logic signed [34:0] expected_prepared_x,expected_prepared_y;
    logic expected_prepared_padding,expected_prepared_hit;
    always @(posedge clk) begin
      if(rst_n && dut.tile_capture) begin
        expected_prepared_x <= dut.incoming_ix;
        expected_prepared_y <= dut.incoming_iy;
        expected_prepared_padding <= dut.incoming_padding;
        expected_prepared_hit <= dut.incoming_word_hit;
      end
      if(rst_n && dut.REGISTER_CACHE_REQUEST && dut.tile_commit) begin
        if(dut.committing_tile.input_x !== expected_prepared_x ||
           dut.committing_tile.input_y !== expected_prepared_y ||
           dut.committing_tile.padding !== expected_prepared_padding ||
           dut.committing_tile.word_hit !== expected_prepared_hit)
          $fatal(1,"prepared descriptor value mismatch");
      end
    end
'''
        if 'committing_live_word_hit' in frontend:
            checks = checks.replace('dut.committing_tile.word_hit !== expected_prepared_hit',
                '(dut.committing_tile.word_hit !== (expected_prepared_hit || '
                '(dut.state[$clog2(dut.WAIT_WORD)] && dut.finishing_tile && '
                'dut.prepared_tile_q.address[31:dut.p_word_shift] == dut.addr[31:dut.p_word_shift])))')
        bench_text = bench_text.replace('    // 对停顿、行切换和归约尾部检查', checks +
                                       '    // 对停顿、行切换和归约尾部检查', 1)
    if 'logic window_forward_allowed_q' in frontend:
        checks = '''    // 预先保存的范围与历史差值在使用周期应等于完整表达式。
    always @(posedge clk) begin
      if (rst_n && dut.window_next_valid) begin
        if (dut.window_forward_allowed_q !== (dut.window_next_kx < dut.last_kernel_col_q) ||
            dut.window_backward_allowed_q !== (dut.window_next_kx != 16'd0) ||
            dut.window_previous_allowed_q !== (dut.c.kernel_w == 16'd3 &&
              dut.window_next_kx == 16'd0 && dut.window_next_ky != 16'd0))
          $fatal(1,"saved window range mismatch");
      end
      if (rst_n && dut.configured) begin
        if (dut.p_wrap_target_q !== (dut.last_output_col_q + dut.c.output_w))
          $fatal(1,"saved position wrap target mismatch");
        for(int boundary=1;boundary<=4;boundary++)
          if(dut.group_at_least_q[boundary] !== (dut.c.group_c >= 16'(boundary)))
            $fatal(1,"saved channel threshold mismatch");
      end
      if(rst_n && dut.REGISTER_CACHE_REQUEST && dut.state == dut.P_DECODE &&
          dut.p_history_delta_q !== 16'(dut.p_decode-dut.last_p))
        $fatal(1,"saved position delta mismatch");
    end
'''
        bench_text = bench_text.replace('    // 对停顿、行切换和归约尾部检查', checks +
                                       '    // 对停顿、行切换和归约尾部检查', 1)
    if 'logic addr_word_hit_q, current_word_hit;' in frontend:
        checks = '''    // 地址及缓存字变化后，保存的命中状态必须与完整比较一致。
    always @(posedge clk) begin
      if (rst_n && dut.addr_word_hit_q !== (dut.word_valid &&
          dut.word_addr == {dut.addr[31:dut.p_word_shift],{dut.p_word_shift{1'b0}}}))
        $fatal(1,"saved word hit mismatch");
    end
'''
        bench_text = bench_text.replace('    // 对停顿、行切换和归约尾部检查', checks +
                                       '    // 对停顿、行切换和归约尾部检查', 1)
    if 'logic [31:0] tap_pair_pixels, tap_pair_bytes;' in frontend:
        checks = '''    // 配置准备完成时检查保存步长与完整位宽定义一致。
    always @(posedge clk) begin
      if (rst_n && dut.tile_ready && dut.configured) begin
        if (dut.tap_pair_dx !== ($signed(35'(dut.tap_wrap_dx)) + $signed(35'(dut.c.dilation_w))))
          $fatal(1,"saved kernel coordinate step mismatch");
        if (dut.tap_pair_pixels !== (32'(dut.tap_wrap_pixels) + 32'(dut.c.dilation_w)))
          $fatal(1,"saved kernel pixel step mismatch");
        if (dut.tap_pair_bytes !== (dut.tap_wrap_bytes + dut.tap_step_bytes))
          $fatal(1,"saved kernel byte step mismatch");
      end
    end
'''
        bench_text = bench_text.replace('    // 对停顿、行切换和归约尾部检查', checks +
                                       '    // 对停顿、行切换和归约尾部检查', 1)
    if 'parameter bit REGISTER_DESCRIPTOR' in frontend:
        bench_text = bench_text.replace('dut.REGISTER_CACHE_REQUEST', 'dut.REGISTER_DESCRIPTOR')
    bench = out / 'tb_conv_im2col_frontend.sv'
    bench.write_text(bench_text)
    spec = importlib.util.spec_from_file_location('frontend_compare', TEST / 'tools/compare_frontend.py')
    comparison = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(comparison)
    configurations = {'s4': (4, 32, 0), 's8': (8, 64, 0), 's16': (16, 64, 0), 'window': (16, 64, 1)}
    compile_options = ['--output-groups', '0', '--output-split', '12000', '-CFLAGS', '-std=c++20 -O1',
        '-MAKEFLAGS', 'OPT_FAST=-O1 OPT_SLOW=-O0 VK_PCH_I_FAST= VK_PCH_I_SLOW= CFG_CXXFLAGS_PCH=-E']
    results = []
    for name in args.cases:
        size, width, window = configurations[name]
        case = out / name
        case.mkdir(exist_ok=True)
        vectors = case / 'vectors.txt'
        run([sys.executable, TEST / 'tests/gen_rtl_vectors.py', '--size', size, '--out', vectors], case / 'vectors.log')
        hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in [*sources, bench]}
        run([args.verilator, '--binary', '--timing', '--assert', '-DNPU_SIM_ASSERT', '-DCONV_ASSERT',
             '-Wno-fatal', '--top-module', 'tb_conv_im2col_frontend', f'-GSIZE={size}',
             f'-GBUS_WIDTH={width}', f'-GLANES={args.lanes}', f'-GCACHE_SETS={args.cache_sets}',
             f'-GLINE_BYTES={args.cache_line_bytes}',
             f"-GWINDOWED=1'b{window}", f"-GPREFETCH=1'b{window}", '--Mdir', case / 'obj', '-j', '2',
             *compile_options, *sources, bench], case / 'build.log')
        warnings = comparison.reviewed_warnings(case / 'build.log')
        run([case / 'obj/Vtb_conv_im2col_frontend', f'+VECTORS={vectors}'], case / 'run.log')
        lines = [line for line in (case / 'run.log').read_text().splitlines() if line.startswith('RTL_FRONTEND_PASS')]
        if not lines:
            raise RuntimeError('前端数值测试未完成: ' + name)
        for path, digest in hashes.items():
            if hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest:
                raise RuntimeError('测试期间源码发生变化: ' + path)
        result = {'case': name, 'SIZE': size, 'BUS_WIDTH': width, 'LANES': args.lanes, 'LINE_BYTES': args.cache_line_bytes,
                  'CACHE_SETS': args.cache_sets, 'REGISTER_CACHE_REQUEST': args.register_cache_request,
                  'REGISTER_DESCRIPTOR': args.register_descriptor, 'CACHE_RESPONSE_DEPTH': args.cache_response_depth,
                  'windowed_prefetch': window, 'passed': True, 'summary': lines,
                  'source_sha256': hashes, 'warnings': warnings}
        results.append(result)
        print('FRONTEND_TRANSACTION_PASS', name, lines, flush=True)
    (out / 'summary.json').write_text(json.dumps({'passed': True,
        'REGISTER_CACHE_REQUEST': args.register_cache_request, 'configurations': results},
        indent=2, ensure_ascii=False) + '\n')


if __name__ == '__main__':
    main()
