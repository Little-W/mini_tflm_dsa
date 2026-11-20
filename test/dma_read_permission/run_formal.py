#!/usr/bin/env python3
"""比较实际读取保护器和复用器的全部端口、寄存状态及模式切换行为。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCES = ('rtl/npu/dma/axi_dual_block_dma.sv',
           'rtl/npu/conv/conv_axi_read_guard.sv', 'rtl/npu/conv/conv_axi_read_mux.sv')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', default='dcef8d89')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    inputs = out / 'inputs'
    subprocess.run([sys.executable, str(ROOT / 'test/dma_read_permission/prepare_measurement.py'),
                    '--reference', args.reference, '--out', str(inputs)], cwd=ROOT, check=True)
    hashes = {name: digest(ROOT / name) for name in SOURCES}
    remaining = {}
    for label in ('reference', 'current'):
        source = (inputs / label / 'axi_dual_block_dma.sv').read_text()
        begin = source.index('        conv_axi_read_guard #(')
        declaration = source.find('        logic read_mux_i_arvalid, read_mux_o_arvalid;')
        if declaration >= 0:
            begin = declaration
        end = source.index('    end else begin : g_linear_only', begin)
        remaining[label] = source[:begin] + source[end:]
    if remaining['reference'] != remaining['current']:
        raise RuntimeError('DMA code outside the measured read connection differs')

    import pyosys
    library = Path(pyosys.__file__).parent / 'share/xilinx/cells_sim.v'
    model = out / 'lut6_2.sv'
    text = re.search(r'^module LUT6_2\b.*?^endmodule', library.read_text(), re.M | re.S)[0]
    model.write_text(re.sub(r'\bspecify\b.*?\bendspecify\b', '', text, flags=re.S) + '\n')
    # 这些组合信号由仲裁模式限定；全部接口输出和保存状态继续逐位比较。
    mode_qualified = ('u_read_mux.a_arvalid', 'u_read_mux.m_arvalid', 'u_read_mux.select_b')
    report = {'passed': False, 'reference': args.reference, 'source_sha256': hashes,
              'inputs_constrained': False, 'outside_read_connection_unchanged': True,
              'mode_qualified_internal_signals': mode_qualified,
              'primitive_library_sha256': digest(library), 'runs': []}
    for bus in (32, 64):
        for fpga in (False, True):
            name = ('fpga' if fpga else 'generic') + '_bus' + str(bus)
            options = f'-GBUS_WIDTH={bus} ' + ('-DSYNTHESIS=1 -DXILINX_FPGA=1' if fpga else '-DASIC_SYNTHESIS=1')
            commands = []
            for label in ('reference', 'current'):
                folder = inputs / label
                sources = [folder / 'read_pair.sv', folder / 'conv_axi_read_guard.sv',
                           folder / 'conv_axi_read_mux.sv', model]
                commands += ['read_slang --top read_ready_top ' + options + ' ' +
                             ' '.join(shlex.quote(str(path)) for path in sources),
                             'prep -top read_ready_top -flatten', 'memory_map', 'async2sync', 'opt_clean',
                             'rename -hide ' + ' '.join('w:' + wire for wire in mode_qualified),
                             'rename -hide w:*.s1 w:*.s2 w:*.s3 w:*.s4 w:*.s5 w:*.s5_0 w:*.s5_1',
                             'rename read_ready_top ' + label, 'design -stash ' + label]
            commands += ['design -copy-from reference -as reference reference',
                         'design -copy-from current -as current current',
                         'equiv_make reference current equivalent', 'hierarchy -top equivalent',
                         'opt_merge', 'equiv_simple -short -seq 1', 'opt_clean',
                         'equiv_induct -seq 2', 'equiv_status -assert']
            script, log = out / (name + '.ys'), out / (name + '.log')
            script.write_text('\n'.join(commands) + '\n')
            with log.open('w') as stream:
                subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                '--worker', str(script)], cwd=ROOT, stdout=stream,
                               stderr=subprocess.STDOUT, check=True, timeout=180)
            text = log.read_text()
            match = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', text)
            if not match or int(match[2]) != 0 or 'Equivalence successfully proven' not in text:
                raise RuntimeError('Connected read modules did not complete equivalence')
            row = {'name': name, 'bus_width': bus, 'fpga': fpga, 'passed': True,
                   'equivalent_bits': int(match[1]), 'log_sha256': digest(log)}
            report['runs'].append(row)
            report['passed'] = len(report['runs']) == 4
            (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
            print(json.dumps(row), flush=True)
    if hashes != {name: digest(ROOT / name) for name in SOURCES}:
        raise RuntimeError('Read sources changed during comparison')


if __name__ == '__main__':
    main()
