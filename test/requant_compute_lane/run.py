#!/usr/bin/env python3
"""检查独立量化通道的完整数值、使能暂停、尾列屏蔽与流水清空。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--verilator', default='verilator-modern')
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--variants', nargs='+', choices=('generic', 'fpga', 'mapped'), default=['generic', 'fpga'])
    parser.add_argument('--mapped', type=Path)
    args = parser.parse_args()
    if 'mapped' in args.variants and args.mapped is None:
        parser.error('--mapped is required for the mapped variant')
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    import pyosys
    library = Path(pyosys.__file__).parent / 'share/xilinx/cells_sim.v'
    library_text = library.read_text()
    primitive_names = ('DSP48E1', 'FDRE', 'FDCE', 'FDPE', 'FDSE', 'LUT1', 'LUT2',
                       'LUT3', 'LUT4', 'LUT5', 'LUT6', 'LUT6_2', 'CARRY4', 'MUXF7', 'MUXF8',
                       'IBUF', 'OBUF', 'BUFG', 'INV', 'SRL16E')
    models = [re.search(r'^module ' + name + r'\b.*?^endmodule', library_text, re.M | re.S)[0]
              for name in primitive_names]
    primitives = out / 'xilinx_primitives.sv'
    primitives.write_text('\n'.join(models) + '\n')
    rtl = [ROOT / 'rtl/npu/writeback/requant_compute_lane.sv',
           ROOT / 'rtl/npu/conv/vector_scalar_multiplier.sv',
           ROOT / 'rtl/common/parallel_prefix_add.sv',
           ROOT / 'rtl/npu/writeback/vec_requant.sv']
    summary = {'passed': False, 'latency_enabled_edges': 12,
               'source_sha256': {str(path.relative_to(ROOT)): digest(path) for path in rtl},
               'primitive_library_sha256': digest(library), 'cases': {}}
    for variant in args.variants:
        case = out / variant
        case.mkdir(exist_ok=True)
        sources = [args.mapped.resolve()] if variant == 'mapped' else rtl
        options = ['-DSYNTHESIS', '-DXILINX_FPGA'] if variant == 'fpga' else []
        command = [args.verilator, '--cc', '--exe', '--build', '--assert', '-Wno-fatal',
                   '--top-module', 'requant_compute_lane', '-j', str(args.jobs),
                   '--Mdir', str(case / 'obj'), '-CFLAGS', '-O2 -fsanitize=undefined -fno-sanitize-recover=all',
                   '-LDFLAGS', '-fsanitize=undefined', *options,
                   *map(str, sources), str(primitives), str(HERE / 'main.cpp')]
        (case / 'command.json').write_text(json.dumps(command, indent=2) + '\n')
        with (case / 'build.log').open('w') as stream:
            subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
        binary = case / 'obj/Vrequant_compute_lane'
        result = subprocess.run([str(binary)], capture_output=True, text=True)
        log = case / 'run.log'
        log.write_text(result.stdout + result.stderr)
        print(variant, result.stdout + result.stderr, end='', flush=True)
        match = re.search(r'REQUANT_LANE_PASS (.*)', result.stdout)
        if result.returncode or match is None:
            raise RuntimeError(f'Numeric comparison failed: {log}')
        summary['cases'][variant] = {'passed': True,
                                    'checks': {key: int(value) for key, value in re.findall(r'(\w+)=(\d+)', match[1])},
                                    'executable_sha256': digest(binary), 'log_sha256': digest(log)}
        if variant == 'mapped':
            summary['cases'][variant]['mapped_sha256'] = digest(args.mapped)
        if summary['source_sha256'] != {str(path.relative_to(ROOT)): digest(path) for path in rtl}:
            raise RuntimeError('The RTL sources changed during the test')
    summary['passed'] = True
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')


if __name__ == '__main__':
    main()
