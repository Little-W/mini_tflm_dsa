#!/usr/bin/env python3
"""证明向量算术模块的完整接口等价，并测量寄存器间的组合级数。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
SOURCES = [f'rtl/npu/conv/{name}.sv' for name in
           ('vector_pe', 'vector_round_shift', 'vector_scalar_multiplier')]
COMMON = 'rtl/common/parallel_prefix_add.sv'
DEFAULT_REFERENCE = 'dde5e7c9'


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_logged(command: list[str], log: Path, timeout: int = 180) -> str:
    with log.open('w') as stream:
        subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                       check=True, timeout=timeout)
    return log.read_text()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-ref', default=DEFAULT_REFERENCE)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference-root', type=Path)
    parser.add_argument('--modules', nargs='+', choices=('reduce', 'round', 'scalar'),
                        default=['reduce', 'round', 'scalar'])
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--synthesis', action='store_true')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source_root = args.source_root.resolve()
    reference = (str(args.reference_root.resolve()) if args.reference_root else
                 subprocess.check_output(['git', 'rev-parse', args.baseline_ref],
                                         cwd=ROOT, text=True).strip())
    inputs = out / 'inputs'
    hashes = {name: digest(source_root / name) for name in SOURCES + [COMMON]}
    original_hashes = {}
    for name in SOURCES:
        original = ((args.reference_root / name).read_bytes() if args.reference_root else
                    subprocess.check_output(['git', 'show', f'{reference}:{name}'], cwd=ROOT))
        original_hashes[name] = hashlib.sha256(original).hexdigest()
        for label, data in [('reference', original), ('current', (source_root / name).read_bytes())]:
            target = inputs / label / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    common = inputs / 'current' / COMMON
    common.parent.mkdir(parents=True, exist_ok=True)
    common.write_bytes((source_root / COMMON).read_bytes())

    profiles = [('reduce', 'vector_reduce_alu', SOURCES[0], {})]
    profiles += [(f'round_middle{middle}', 'vector_round_shift', SOURCES[1],
                  {'REGISTER_MIDDLE': middle}) for middle in (0, 1)]
    profiles += [(f'scalar_a{a}_b{b}', 'registered_multiplier_s32', SOURCES[2],
                  {'p_input_register': a, 'p_b_input_register': b})
                 for a in (0, 1) for b in (0, 1)]
    profiles = [profile for profile in profiles
                if any(profile[0].startswith(name) for name in args.modules)]
    runs = []
    for mode in ('fpga', 'asic'):
        for name, top, source_name, parameters in profiles:
            folder = out / 'formal' / f'{mode}_{name}'
            folder.mkdir(parents=True, exist_ok=True)
            commands = []
            define = 'XILINX_FPGA' if mode == 'fpga' else 'ASIC_SYNTHESIS'
            options = ' '.join(f'-G{key}={value}' for key, value in parameters.items())
            for label in ('reference', 'current'):
                source = inputs / label / source_name
                commands += [
                    f'read_slang -D SYNTHESIS=1 -D {define}=1 --top {top} {options} '
                    f'{shlex.quote(str(source))} {shlex.quote(str(common))}',
                    f'prep -top {top} -flatten', 'opt -full',
                    f'rename {top} {label}', f'design -stash {label}',
                ]
            commands += [
                'design -copy-from reference -as reference reference',
                'design -copy-from current -as current current',
                'equiv_make reference current comparison', 'hierarchy -top comparison',
                'equiv_simple -seq 2', 'opt_clean', 'equiv_induct -seq 3',
                'equiv_status -assert',
            ]
            script = folder / 'run.ys'
            script.write_text('\n'.join(commands) + '\n')
            log = folder / 'formal.log'
            output = run_logged([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                 '--worker', str(script)], log)
            if 'Equivalence successfully proven' not in output:
                raise RuntimeError(f'接口等价检查未完成：{log}')
            runs.append({'profile': name, 'mode': mode, 'parameters': parameters,
                         'passed': True, 'script_sha256': digest(script), 'log_sha256': digest(log)})
            print(json.dumps({'profile': name, 'mode': mode, 'passed': True}), flush=True)

    measurement_cases = {}
    wrappers = inputs / 'measure_top.sv'
    wrappers.write_bytes((HERE / 'measure_top.sv').read_bytes())
    for label in ('reference', 'current'):
        for name, top, source_name, parameters in [
            ('reduce', 'reduce_depth_top', SOURCES[0], {}),
            ('round', 'round_depth_top', SOURCES[1], {}),
            ('scalar', 'registered_multiplier_s32', SOURCES[2], {}),
        ]:
            if name not in args.modules:
                continue
            measurement_cases[f'{label}_{name}'] = {
                'top': top, 'sources': [str(inputs / label / source_name), str(wrappers)],
                'options': ['-D', 'SYNTHESIS=1', '-D', 'XILINX_FPGA=1'],
                'configuration': f'{name}：保留实际算术位宽和寄存器边界',
            }
    case_config = out / 'cases.json'
    case_config.write_text(json.dumps(measurement_cases, ensure_ascii=False, indent=2) + '\n')
    synthesis = None
    if args.synthesis:
        command = [sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                   '--source-root', str(inputs / 'current'), '--case-config', str(case_config),
                   '--cases', *measurement_cases, '--out', str(out / 'synthesis')]
        run_logged(command, out / 'synthesis.log', timeout=600)
        synthesis = json.loads((out / 'synthesis/summary.json').read_text())
    if hashes != {name: digest(source_root / name) for name in hashes}:
        raise RuntimeError('检查期间生产源码发生了变化')
    summary = {
        'passed': True, 'reference_revision': reference,
        'source_root': str(source_root), 'modules': args.modules,
        'source_sha256': hashes, 'reference_source_sha256': original_hashes,
        'input_constraints': [], 'all_public_outputs_compared': True,
        'formal_profiles': runs, 'synthesis': synthesis,
        'runner_sha256': digest(Path(__file__).resolve()),
        'measurement_wrapper_sha256': digest(HERE / 'measure_top.sv'),
    }
    (out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'passed': True, 'profiles': len(runs), 'synthesis': bool(synthesis)}))


if __name__ == '__main__':
    main()
