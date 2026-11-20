#!/usr/bin/env python3
"""随机驱动完整缓存接口，逐周期比较通用和生产数据排列的全部公开输出。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'test/ia_timing'))
from run_interface import port_declarations

SOURCE = ROOT / 'rtl/npu/loaders/ia_loader_cache_mgr.sv'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def testbench(cycles):
    ports = port_declarations(SOURCE.read_text())
    lines = ['module tb_source_layout;',
             '    localparam int DATA_WIDTH=16, SIZE=16, BUS_WIDTH=64, REG_WIDTH=32;',
             '    localparam int CACHE_BLOCKS=32, COMPACT_S8=1, SLOT_BLOCKS=64;',
             '    localparam bit EXTERNAL_RAM=1;',
             '    localparam int RAM_WORD_ADDR_WIDTH=12, p_compact_offset_width=9;']
    for direction, kind, name, unpacked in ports:
        names = [name] if direction == 'input' else ['reference_' + name, 'current_' + name]
        lines += [f'    {kind} {signal} {unpacked};' for signal in names]
    parameters = ['DATA_WIDTH', 'SIZE', 'BUS_WIDTH', 'REG_WIDTH', 'CACHE_BLOCKS',
                  'COMPACT_S8', 'EXTERNAL_RAM', 'RAM_WORD_ADDR_WIDTH', 'p_compact_offset_width']
    for label, enabled in [('reference', 0), ('current', 1)]:
        lines += ['    ia_loader_cache_mgr #(',
                  ',\n'.join(f'        .{name}({name})' for name in parameters) +
                  f",\n        .p_dma_source_layout(1'b{enabled})",
                  f'    ) u_{label} (',
                  ',\n'.join(f'        .{name}({label + "_" if direction == "output" else ""}{name})'
                            for direction, _, name, _ in ports), '    );']
    lines += ["    initial clk = 1'b0;", '    always #5 clk = ~clk;',
              '    initial begin', "        rst_n = 1'b0;",
              f'        for (int cycle = 0; cycle < {cycles}; cycle++) begin',
              '            @(negedge clk);',
              "            rst_n = cycle > 3 && (cycle % 4093 != 0);",
              '            compact_mode = $urandom_range(0, 1);',
              '            compact_offset = 16\'($urandom);',
              '            cfg_cache_blocks = (cycle & 1) ? 32 : 16;',
              '            slot_base = 6\'($urandom);',
              '            wr_slot = 6\'($urandom);',
              '            wr_row = 4\'($urandom);',
              '            wr_col_base = 4\'($urandom);',
              '            wr_use_16bits = $urandom_range(0, 1);',
              "            if (!wr_use_16bits) wr_col_base[2:0] = 3'd0;",
              '            for (int lane = 0; lane < 8; lane++) begin',
              '                wr_data[lane] = 16\'($urandom);',
              '                wr_valid[lane] = $urandom_range(0, 1) && (lane < 4 || !wr_use_16bits);',
              '            end',
              '            for (int port_index = 0; port_index < 2; port_index++)',
              '                ram_port_rd_data[port_index] = {$urandom, $urandom, $urandom, $urandom};',
              '            l1_start = $urandom_range(0, 7) == 0;',
              '            l1_slot_start = 6\'($urandom);',
              '            l1_slot_end = l1_slot_start + 6\'($urandom_range(0, 3));',
              '            l1_is_init = $urandom_range(0, 1);',
              '            l1_calc_done = $urandom_range(0, 1);',
              '            for (int slot_index = 0; slot_index < SLOT_BLOCKS; slot_index++)',
              '                slot_rows[slot_index] = 5\'($urandom_range(1, 16));',
              '            @(posedge clk);', '            #1;']
    outputs = [name for direction, _, name, _ in ports if direction == 'output']
    lines += [f'            assert (reference_{name} === current_{name}) else '
              f'$fatal(1, "Source layout output differs: {name}, cycle=%0d", cycle);'
              for name in outputs]
    lines += ['        end',
              f'        $display("IA_SOURCE_LAYOUT_PASS cycles={cycles} outputs={len(outputs)} comparisons={cycles*len(outputs)}");',
              '        $finish;', '    end', 'endmodule']
    return '\n'.join(lines) + '\n', outputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--verilator', default='verilator-modern')
    parser.add_argument('--cycles', type=int, default=200000)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    text, outputs = testbench(args.cycles)
    tb = out / 'tb_source_layout.sv'
    tb.write_text(text)
    sources = [SOURCE, ROOT / 'rtl/npu/compute/select_add.sv',
               ROOT / 'rtl/common/regfile.v', ROOT / 'rtl/common/pseudo_dual_port_ram.v', tb]
    hashes = {str(p): digest(p) for p in sources}
    command = [args.verilator, '--binary', '--timing', '--assert', '-Wno-fatal', '-j', '1',
               '--top-module', 'tb_source_layout', '--Mdir', str(out / 'obj'), *map(str, sources)]
    with (out / 'compile.log').open('w') as stream:
        subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
    result = subprocess.run([str(out / 'obj/Vtb_source_layout')], cwd=ROOT, capture_output=True, text=True)
    (out / 'run.log').write_text(result.stdout + result.stderr)
    match = re.search(r'IA_SOURCE_LAYOUT_PASS (.*)', result.stdout)
    if result.returncode or not match:
        raise RuntimeError(result.stdout + result.stderr)
    if hashes != {str(p): digest(p) for p in sources}:
        raise RuntimeError('Sources changed during verification')
    report = {key: int(value) for key, value in re.findall(r'(\w+)=(\d+)', match[1])}
    report.update(passed=True, source_sha256=hashes, compared_outputs=outputs,
                  binary_sha256=digest(out / 'obj/Vtb_source_layout'))
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
