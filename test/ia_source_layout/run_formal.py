#!/usr/bin/env python3
"""检查生产 DMA 数据排列下缓存及完整 IA 加载器的逐周期等价性。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'test/ia_timing'))
from run_interface import port_declarations
sys.path.insert(0, str(ROOT / 'test/ia_write_output_depth'))
from primitives import prepare_models

SOURCES = [ROOT / 'rtl/npu/loaders' / (name + '.sv') for name in
           ('ia_loader', 'ia_loader_ctrl', 'ia_loader_cache_mgr')]
SOURCES.append(ROOT / 'rtl/npu/compute/select_add.sv')
SOURCES += [ROOT / 'rtl/npu/loaders' / name for name in
            ('ia_ordered_coordinate_equal.sv', 'ia_ordered_coordinate_same.sv')]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_wrapper(module, path):
    source = (ROOT / 'rtl/npu/loaders' / (module + '.sv')).read_text()
    header = source[:source.index('\n);') + 3]
    header = re.sub(r'\bmodule\s+' + module, 'module source_layout', header)
    ports = port_declarations(source)
    parameters = ['DATA_WIDTH', 'SIZE', 'BUS_WIDTH', 'REG_WIDTH', 'CACHE_BLOCKS',
                  'COMPACT_S8', 'RAM_WORD_ADDR_WIDTH', 'p_dma_source_layout',
                  'p_shared_write_stage']
    if module == 'ia_loader':
        parameters += ['COUNT_WIDTH', 'ORDERED_JOB', 'PS_FRAME_COUNT']
        prefix = 'ext_dma_'
    else:
        parameters += ['p_compact_offset_width']
        prefix = ''
    column = prefix + 'wr_col_base'
    valid = prefix + 'wr_valid'
    use16 = prefix + 'wr_use_16bits'
    body = ['    logic [3:0] dma_column;', '    logic dma_valid [BUS_WIDTH/8];',
            f'    assign dma_column = {use16} ? {column} : {{{column}[3], 3\'d0}};',
            '    for (genvar lane = 0; lane < BUS_WIDTH/8; lane++) begin : g_valid',
            f'        assign dma_valid[lane] = {valid}[lane] && (lane < 4 || !{use16});',
            '    end', f'    {module} #(',
            ',\n'.join(f'        .{name}({name})' for name in parameters),
            '    ) u_dut (']
    body.append(',\n'.join(f'        .{name}(' +
        ('dma_column' if name == column else 'dma_valid' if name == valid else name) + ')'
        for _, _, name, _ in ports))
    body += ['    );', 'endmodule']
    path.write_text(header + '\n' + '\n'.join(body) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--cases', nargs='+', choices=('cache', 'loader'), default=['cache', 'loader'])
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    model, primitive_info = prepare_models(out, names=('DSP48E1',))
    common = sorted(path for path in (ROOT / 'rtl/common').glob('*') if path.suffix in ('.sv', '.v'))
    report = dict(passed=False, source_sha256={str(p.relative_to(ROOT)): digest(p) for p in SOURCES + common},
                  primitive_models=primitive_info,
                  dma_properties=['!wr_use_16bits -> wr_col_base[2:0] == 0',
                                  'wr_use_16bits -> wr_valid[7:4] == 0'], runs=[])
    for name in args.cases:
        module = 'ia_loader_cache_mgr' if name == 'cache' else 'ia_loader'
        wrapper = out / (name + '.sv')
        make_wrapper(module, wrapper)
        options = ['-D YOSYS=1', '-D VERIFIC=1', '-DXILINX_FPGA=1', '-GSIZE=16',
                   '-GBUS_WIDTH=64', '-GCACHE_BLOCKS=32',
                   '-GRAM_WORD_ADDR_WIDTH=12']
        options += (['-Gp_compact_offset_width=9'] if name == 'cache' else
                    ['-GCOUNT_WIDTH=29', '-GORDERED_JOB=1', '-GPS_FRAME_COUNT=16'])
        blacklist = out / (name + '_intermediate.txt')
        hierarchy = 'u_dut.' if name == 'cache' else 'u_dut.u_cache_mgr.'
        blacklist.write_text(hierarchy + 'g_external_ram.compact_shifted_bytes\n')
        commands = []
        for label, enabled in [('reference', 0), ('current', 1)]:
            commands += ['read_slang --top source_layout ' + ' '.join(options) +
                         f' -Gp_dma_source_layout={enabled} ' +
                         ' '.join(shlex.quote(str(p)) for p in SOURCES + common + [model, wrapper]),
                         'prep -top source_layout -flatten', 'memory_map', 'async2sync', 'opt_clean',
                         'rename source_layout ' + label, 'design -stash ' + label]
        commands += ['design -copy-from reference -as reference reference',
                     'design -copy-from current -as current current',
                     f'equiv_make -blacklist {shlex.quote(str(blacklist))} reference current equivalent',
                     'hierarchy -top equivalent', 'equiv_simple -seq 1', 'opt_clean',
                     'equiv_induct -seq 2', 'equiv_status -assert']
        script, log = out / (name + '.ys'), out / (name + '.log')
        script.write_text('\n'.join(commands) + '\n')
        with log.open('w') as stream:
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                     '--worker', str(script)], cwd=ROOT, stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=600)
        text = log.read_text()
        count = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', text)
        row = dict(name=name, equivalent_bits=int(count[1]) if count else None,
                   passed=result.returncode == 0 and 'Equivalence successfully proven' in text,
                   log_sha256=digest(log))
        report['runs'].append(row)
        (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(row), flush=True)
        if not row['passed']:
            raise RuntimeError('Source layout comparison did not complete: ' + str(log))
    if report['source_sha256'] != {str(p.relative_to(ROOT)): digest(p) for p in SOURCES + common}:
        raise RuntimeError('Sources changed during verification')
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
