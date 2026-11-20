#!/usr/bin/env python3
"""验证普通 im2col 的寄存启动、事务完成及中止和复位行为。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import subprocess


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def wrapper(source):
    header = source[:re.search(r'^\s*\);', source, re.M).end()]
    header = header.replace('module axi_dual_block_dma', 'module dma_registered_tb', 1)
    header = re.sub(r'\babort\b', 'i_abort', header)
    header = header.replace("input  conv_im2col_pkg::conv_cfg_t conv_cfg = '0,",
                            'input logic [31:0] config_words [16],')
    header = header.replace('output logic wr_error\n', '''output logic wr_error,
    output logic observe_pending, observe_active, observe_accept, observe_linear_accept,
    output logic observe_linear_finish,
    output logic observe_frontend_valid, observe_frontend_ready, observe_frontend_fire,
    output logic [31:0] observe_p0, observe_q0, observe_group,
    output logic [31:0] observe_rows, observe_cols, observe_slot, observe_configuration
''')
    parameters = re.findall(r'parameter\s+int\s+unsigned\s+(\w+)\s*=', header)
    connections = ', '.join(f'.{name}({name})' for name in parameters)
    return header + f'''
    conv_im2col_pkg::conv_cfg_t conv_cfg;
    always_comb begin
        conv_cfg = '0;
        conv_cfg.input_base = config_words[0];
        conv_cfg.input_h = 16'(config_words[1]);
        conv_cfg.input_w = 16'(config_words[2]);
        conv_cfg.input_c = 16'(config_words[3]);
        conv_cfg.group_c = 16'(config_words[3]);
        conv_cfg.kernel_h = 16'(config_words[4]);
        conv_cfg.kernel_w = 16'(config_words[5]);
        conv_cfg.output_h = 16'(config_words[6]);
        conv_cfg.output_w = 16'(config_words[7]);
        conv_cfg.stride_h = 16'(config_words[8]);
        conv_cfg.stride_w = 16'(config_words[9]);
        conv_cfg.pad_top = 16'(config_words[10]);
        conv_cfg.pad_left = 16'(config_words[11]);
        conv_cfg.input_offset = 16'(config_words[12]);
        conv_cfg.dilation_h = 16'd1;
        conv_cfg.dilation_w = 16'd1;
        conv_cfg.windowed = config_words[13][0];
        conv_cfg.prefetch_enable = config_words[14][0];
        conv_cfg.bypass_cache = config_words[15][0];
    end
    axi_dual_block_dma #({connections}) dut (.abort(i_abort), .*);
    assign observe_pending = dut.conv_pending;
    assign observe_active = dut.conv_active;
    assign observe_accept = dut.accept_image;
    assign observe_linear_accept = dut.accept_linear;
    assign observe_linear_finish = dut.linear_finish;
    assign observe_frontend_valid = dut.frontend_i_tile_valid;
    assign observe_frontend_ready = dut.fe_tile_ready;
    assign observe_frontend_fire = dut.frontend_i_tile_valid && dut.fe_tile_ready;
    assign observe_p0 = dut.frontend_i_tile_p0;
    assign observe_q0 = dut.frontend_i_tile_q0;
    assign observe_group = dut.frontend_i_tile_group;
    assign observe_rows = 32'(dut.frontend_i_tile_rows);
    assign observe_cols = 32'(dut.frontend_i_tile_cols);
    assign observe_slot = 32'(dut.frontend_i_tile_slot);
    assign observe_configuration = 32'({{
        dut.g_im2col.u_frontend.configured, dut.g_im2col.u_frontend.error,
        dut.g_im2col.u_frontend.cfg_ok, dut.g_im2col.u_frontend.cfg_basic_saved,
        dut.g_im2col.u_frontend.cfg_prepare_phase,
        dut.g_im2col.u_frontend.pred_busy, dut.g_im2col.u_frontend.pred_cfg_busy,
        dut.g_im2col.u_frontend.pred_cfg_pending, dut.g_im2col.u_frontend.cache_cfg_pending,
        dut.g_im2col.u_frontend.cache_hint_pending, dut.g_im2col.u_frontend.address_step_phase,
        dut.g_im2col.u_frontend.state}});

    // 接收、前端消费和配置使用各自明确的时钟边沿。
    always @(posedge clk) if (rst_n) begin
        assert (!dut.conv_pending || dut.conv_active);
        assert (!(dut.conv_pending && dut.accept_image));
        assert (!(dut.conv_pending && dut.conv_cfg_ready));
        assert (!(dut.accept_image && i_abort));
        if (dut.conv_pending) begin
            assert (dut.frontend_i_tile_valid);
            assert (!dut.win_payload_select);
        end
    end
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--bus-width', type=int, choices=(32, 64), default=64)
    parser.add_argument('--cache-blocks', type=int, choices=(1, 64), default=64)
    parser.add_argument('--verilator', default='verilator')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    target = out / 'dma_registered_tb.sv'
    target.write_text(wrapper((ROOT / 'rtl/npu/dma/axi_dual_block_dma.sv').read_text()))
    sources = [ROOT / 'rtl/npu/conv/conv_im2col_pkg.sv', ROOT / 'rtl/npu/conv/vector_engine_pkg.sv']
    sources += [p for p in sorted((ROOT / 'rtl/npu/conv').glob('*.sv')) if p not in sources]
    sources += sorted((ROOT / 'rtl/npu/dma').rglob('*.sv'))
    sources += [target, HERE / 'main.cpp']
    sources = runpy.run_path(str(ROOT / 'test/monitors/sources.py'))['with_observers'](sources)
    import pyosys
    library = Path(pyosys.__file__).parent / 'share/xilinx/cells_sim.v'
    model = out / 'xilinx_models.sv'
    model.write_text('\n\n'.join(re.search(r'^module ' + name + r'\b.*?^endmodule',
        library.read_text(), re.M | re.S).group(0)
        for name in ('LUT1', 'LUT6', 'LUT6_2', 'MUXF7', 'MUXF8', 'DSP48E1')) + '\n')
    sources.append(model)
    hashes = {str(p): digest(p) for p in [Path(__file__).resolve(), *sources]}
    rules = out / 'compile_rules.mk'
    rules.write_text('%.o: %.cpp\n\t$(OBJCACHE) $(CXX) $(CXXFLAGS) $(CPPFLAGS) $(OPT_FAST) -c -o $@ $<\n'
                    '$(VK_OBJS_FAST): %.o: %.cpp\n\t$(OBJCACHE) $(CXX) $(CXXFLAGS) $(CPPFLAGS) $(OPT_FAST) -c -o $@ $<\n'
                    '$(VK_OBJS_SLOW): %.o: %.cpp\n\t$(OBJCACHE) $(CXX) $(CXXFLAGS) $(CPPFLAGS) $(OPT_SLOW) -c -o $@ $<\n'
                    '$(VK_GLOBAL_OBJS): %.o: %.cpp\n\t$(OBJCACHE) $(CXX) $(CXXFLAGS) $(CPPFLAGS) $(OPT_GLOBAL) -c -o $@ $<\n')
    flags = f'-std=c++20 -O1 -fsanitize=undefined -fno-sanitize-recover=all -DTEST_BUS_WIDTH={args.bus_width} -DTEST_CACHE_BLOCKS={args.cache_blocks}'
    command = [args.verilator, '--cc', '--exe', '--build', '--assert', '-j', '1',
        '--top-module', 'dma_registered_tb', '-Wno-fatal', '-Wno-PINMISSING', '-DSYNTHESIS',
        f'-GBUS_WIDTH={args.bus_width}', '-GSIZE=64', '-GIM2COL_SIZE=16',
        f'-GCACHE_BLOCKS={args.cache_blocks}', '-GCONV_CACHE_SETS=128',
        '--Mdir', str(out / 'obj'), '--output-groups', '0', '--output-split', '10000',
        '--output-split-cfuncs', '1000', '-CFLAGS', flags, '-LDFLAGS', '-fsanitize=undefined',
        '-MAKEFLAGS', f'OPT_FAST=-O1 OPT_SLOW=-O0 OPT_GLOBAL=-O0 VM_DEFAULT_RULES=0 -f {rules}',
        *map(str, sources)]
    with (out / 'compile.log').open('w') as log:
        subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    binary = out / 'obj/Vdma_registered_tb'
    with (out / 'run.log').open('w') as log:
        subprocess.run([str(binary)], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    assert all(digest(Path(p)) == value for p, value in hashes.items())
    result = json.loads((out / 'run.log').read_text().strip().splitlines()[-1])
    assert result['passed']
    result.update(source_sha256=hashes, binary_sha256=digest(binary), compile_command=command,
                  primitive_library_sha256=digest(library), fpga=True,
                  parameters={'BUS_WIDTH': args.bus_width, 'SIZE': 64, 'IM2COL_SIZE': 16,
                              'CACHE_BLOCKS': args.cache_blocks, 'CONV_CACHE_SETS': 128},
                  undefined_behavior_sanitizer=True)
    (out / 'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k not in ('source_sha256', 'compile_command')}))


if __name__ == '__main__':
    main()
