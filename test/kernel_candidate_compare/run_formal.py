#!/usr/bin/env python3
"""证明加载请求资格、遍历更新及调度器宽算术的完整状态和输出等价。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCES = {
    'kernel_loader': Path('rtl/npu/loaders/kernel_loader.sv'),
    'kernel_loader_ctrl': Path('rtl/npu/loaders/kernel_loader_ctrl.sv'),
    'ps_window_scheduler': Path('rtl/npu/control/ps_window_scheduler.sv'),
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference-root', type=Path, required=True)
    parser.add_argument('--module', choices=SOURCES, required=True)
    parser.add_argument('--profiles', nargs='+', required=True,
                        help='加载器为 SIZE:COUNT_WIDTH:BUS_WIDTH，调度器为 SIZE:FRAME_COUNT:MAX_REUSE_TILES')
    parser.add_argument('--fpga', action='store_true')
    parser.add_argument('--seq', type=int, default=4)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    hashes = {}
    source_sets = {}
    for label, folder in [('reference', args.reference_root.resolve()),
                          ('current', args.source_root.resolve())]:
        sources = [folder / SOURCES[args.module]]
        if args.module == 'kernel_loader':
            sources += [folder / 'rtl/npu/loaders' / name for name in
                        ('kernel_loader_ctrl.sv', 'kernel_loader_buffer.sv')]
        sources += sorted(path for path in (folder / 'rtl/common').glob('*')
                          if path.suffix in ('.sv', '.v'))
        source_sets[label] = []
        for source in sources:
            hashes[str(source)] = digest(source)
            copy = out / 'inputs' / label / source.relative_to(folder)
            copy.parent.mkdir(parents=True, exist_ok=True)
            text = source.read_text()
            copy.write_text(text)
            source_sets[label].append(copy)
    profiles = []
    for profile in args.profiles:
        size, second, third = map(int, profile.split(':'))
        parameters = {'SIZE': size}
        if args.module == 'ps_window_scheduler':
            parameters.update(FRAME_COUNT=second, MAX_REUSE_TILES=third)
        else:
            parameters['COUNT_WIDTH'] = second
            if args.module == 'kernel_loader':
                parameters.update(BUS_WIDTH=third, DATA_WIDTH=16)
        flags = '-D SYNTHESIS=1 -D XILINX_FPGA=1' if args.fpga else '-D ASIC_SYNTHESIS=1'
        flags += ' ' + ' '.join(f'-G{name}={value}' for name, value in parameters.items())
        commands = []
        for label, sources in source_sets.items():
            commands += [f'read_slang {flags} --top {args.module} ' + shlex.join(map(str, sources)),
                         f'prep -top {args.module} -flatten', 'memory_map', 'async2sync', 'opt_clean',
                         f'rename {args.module} {label}', f'design -stash {label}']
        commands += ['design -copy-from reference -as reference reference',
                     'design -copy-from current -as current current',
                     'equiv_make reference current equivalent', 'hierarchy -top equivalent',
                     'equiv_simple -seq 1', 'opt_clean', f'equiv_induct -seq {args.seq}',
                     'equiv_status -assert']
        stem = profile.replace(':', '_')
        script, log = out / (stem + '.ys'), out / (stem + '.log')
        script.write_text('\n'.join(commands) + '\n')
        with log.open('w') as stream:
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                     '--worker', str(script)], cwd=ROOT, stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=600)
        text = log.read_text()
        match = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', text)
        if result.returncode or match is None or int(match[2]) != 0:
            raise RuntimeError(f'完整状态证明未通过：{log}')
        row = {'parameters': parameters, 'passed': True, 'equivalent_bits': int(match[1]),
               'script_sha256': digest(script), 'log_sha256': digest(log), 'log': str(log)}
        profiles.append(row)
        print(json.dumps(row), flush=True)
    if hashes != {name: digest(Path(name)) for name in hashes}:
        raise RuntimeError('验证期间源文件发生变化')
    report = {'passed': True, 'module': args.module, 'source_sha256': hashes,
              'inputs_constrained': False, 'fpga': args.fpga,
              'state_and_outputs_every_cycle': True, 'profiles': profiles,
              'equivalent_bits': sum(row['equivalent_bits'] for row in profiles)}
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
