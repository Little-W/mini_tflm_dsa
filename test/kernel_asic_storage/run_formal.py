#!/usr/bin/env python3
"""按完整矩阵元素对应关系证明 ASIC 权重缓存的同步列存储。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/loaders/kernel_loader_buffer.sv')


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--reference-root', type=Path, required=True)
    parser.add_argument('--profiles', nargs='+', default=['3:8', '4:16', '16:16'])
    parser.add_argument('--fpga', action='store_true')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    roots = {'reference': args.reference_root.resolve(), 'current': args.source_root.resolve()}
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources, hashes = {}, {}
    for label, root in roots.items():
        sources[label], hashes[label] = [], {}
        for relative in (SOURCE, Path('rtl/common/regfile.v')):
            target = out / 'inputs' / label / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((root / relative).read_bytes())
            sources[label].append(target)
            hashes[label][str(relative)] = digest(target)
    reports = []
    for profile in args.profiles:
        size, width = map(int, profile.split(':'))
        if size >= 16:
            partition = out / profile.replace(':', '_')
            command = [sys.executable, str(ROOT / 'test/kernel_row_storage/run_partitioned.py'),
                       '--source-root', str(out / 'inputs/current'),
                       '--reference-root', str(out / 'inputs/reference'),
                       '--size', str(size), '--width', str(width),
                       '--reference-layout', 'parameter',
                       '--source-layout', 'parameter' if args.fpga else 'column',
                       '--define', 'XILINX_FPGA=1' if args.fpga else 'ASIC_SYNTHESIS=1',
                       '--out', str(partition)]
            with (out / (profile.replace(':', '_') + '_partitioned.log')).open('w') as stream:
                subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, check=True)
            summary = json.loads((partition / 'summary.json').read_text())
            if not summary['passed'] or not summary['all_state_and_outputs']:
                raise RuntimeError('权重输出分组证明未完整完成')
            reports.append({'SIZE': size, 'DATA_WIDTH': width, 'passed': True,
                            'matrix_storage_bits': summary['matrix_storage_bits'],
                            'equivalent_bits': summary['equivalent_bits'],
                            'output_groups': len(summary['groups']),
                            'summary_sha256': digest(partition / 'summary.json')})
            print(json.dumps(reports[-1]), flush=True)
            continue
        commands = []
        for label in roots:
            definitions = '-DXILINX_FPGA=1' if args.fpga else '-DASIC_SYNTHESIS=1'
            commands += [
                f'read_slang -DSYNTHESIS=1 {definitions} --top kernel_loader_buffer '
                f'-GSIZE={size} -GDATA_WIDTH={width} ' + shlex.join(map(str, sources[label])),
                'prep -top kernel_loader_buffer -flatten', 'memory_map', 'async2sync',
                'opt_clean', 'cd kernel_loader_buffer',
            ]
            row_storage = size > 1 and (size & (size - 1)) == 0 and (label == 'reference' or args.fpga)
            for slot in range(3):
                for row in range(size):
                    for column in range(size):
                        if row_storage:
                            old = f'g_row_storage.g_row[{row}].mem[{slot*size+column}]'
                        else:
                            old = f'g_column_storage.g_column_ram[{column}].u_column.mem[{slot*size+row}]'
                        new = f'storage_slot_{slot}_row_{row}_column_{column}'
                        commands.append(f'rename \\{old} \\{new}')
            commands += ['cd ..', f'rename kernel_loader_buffer {label}', f'design -stash {label}']
        commands += ['design -copy-from reference -as reference reference',
                     'design -copy-from current -as current current',
                     'equiv_make reference current comparison', 'hierarchy -top comparison',
                     'equiv_simple -short -seq 1', 'opt_clean', 'equiv_induct -seq 4',
                     'equiv_status -assert']
        script, log = out / (profile.replace(':', '_') + '.ys'), out / (profile.replace(':', '_') + '.log')
        script.write_text('\n'.join(commands) + '\n')
        with log.open('w') as stream:
            completed = subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                        '--worker', str(script)], stdout=stream,
                                       stderr=subprocess.STDOUT, timeout=600)
        text = log.read_text()
        matched = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', text)
        if completed.returncode or matched is None or int(matched[2]):
            raise RuntimeError('权重存储状态证明未完成: ' + str(log))
        reports.append({'SIZE': size, 'DATA_WIDTH': width, 'passed': True,
                        'matrix_storage_bits': 3 * size * size * width,
                        'equivalent_bits': int(matched[1]), 'log_sha256': digest(log)})
        print(json.dumps(reports[-1]), flush=True)
    for label, root in roots.items():
        for relative, expected in hashes[label].items():
            if digest(root / relative) != expected:
                raise RuntimeError('验证期间源代码发生变化')
    report = {'passed': True, 'source_sha256': hashes, 'external_inputs_constrained': False,
              'mode': 'FPGA' if args.fpga else 'ASIC', 'profiles': reports,
              'compared': 'all public outputs, common control state and every physical matrix element'}
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
