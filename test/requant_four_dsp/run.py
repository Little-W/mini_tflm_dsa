#!/usr/bin/env python3
"""验证四 DSP 标量接口、全部输入寄存组合及实际综合网表的完整乘积。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--source', type=Path, default=ROOT / 'rtl/npu/conv/vector_scalar_multiplier.sv')
    parser.add_argument('--reference-rev', default='5d148afe')
    parser.add_argument('--verilator', default='verilator-modern')
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--mapped-reference', type=Path)
    parser.add_argument('--mapped-candidate', type=Path)
    parser.add_argument('--mapped-mode', type=int, choices=range(4), default=3)
    args = parser.parse_args()
    if bool(args.mapped_reference) != bool(args.mapped_candidate):
        parser.error('Both mapped source files are required for mapped comparison')
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = args.source.resolve()
    old = read_rtl_source(args.reference_rev + ':rtl/npu/conv/vector_scalar_multiplier.sv', cwd=ROOT, text=True)
    module_names = re.findall(r'^module\s+(\w+)', old, re.MULTILINE)
    reference = out / 'reference.sv'
    reference.write_text(re.sub(r'\b(' + '|'.join(map(re.escape, module_names)) + r')\b',
                                r'\1_reference', old))
    sources = [source, reference, HERE / 'tb_four_dsp.sv']
    options = []
    if args.mapped_candidate:
        for name, path in [('reference', args.mapped_reference), ('candidate', args.mapped_candidate)]:
            mapped = out / ('mapped_' + name + '.sv')
            text, count = re.subn(r'\bmodule\s+registered_multiplier_s32\b',
                                  'module mapped_' + name, path.read_text())
            if count != 1:
                raise RuntimeError('Mapped source must contain registered_multiplier_s32')
            mapped.write_text(text)
            sources.append(mapped)
        options = ['-DCHECK_MAPPED', '-DMAPPED_MODE=' + str(args.mapped_mode)]

    import pyosys
    library = Path(pyosys.__file__).parent / 'share/xilinx/cells_sim.v'
    models = []
    for name in ('DSP48E1', 'FDRE', 'IBUF', 'OBUF', 'BUFG'):
        models.append(re.search(r'^module ' + name + r'\b.*?^endmodule',
                                library.read_text(), re.M | re.S)[0])
    primitive_models = out / 'xilinx_primitives.sv'
    primitive_models.write_text('\n'.join(models) + '\n')
    sources.append(primitive_models)
    hashes = {str(path): digest(path) for path in sources}
    command = [args.verilator, '--binary', '--timing', '--assert', '-Wno-fatal',
               '--top-module', 'tb_four_dsp', '-j', str(args.jobs),
               '--Mdir', str(out / 'obj'), *options, *map(str, sources)]
    with (out / 'build.log').open('w') as stream:
        subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
    binary = out / 'obj/Vtb_four_dsp'
    run = subprocess.run([str(binary)], cwd=ROOT, capture_output=True, text=True)
    log = out / 'run.log'
    log.write_text(run.stdout + run.stderr)
    print(run.stdout + run.stderr, end='', flush=True)
    if run.returncode:
        raise RuntimeError('Complete product comparison failed')
    marker = re.search(r'FOUR_DSP_PASS checks=(\d+) enabled=(\d+) held=(\d+) modes=(\d+)', run.stdout)
    if not marker or hashes != {str(path): digest(path) for path in sources}:
        raise RuntimeError('Verification summary or source identity is incomplete')
    summary = {
        'passed': True,
        'reference_revision': args.reference_rev,
        'source_sha256': hashes,
        'primitive_library_sha256': digest(library),
        'public_scalar_interface_checked': True,
        'mapped_mode': args.mapped_mode if args.mapped_candidate else None,
        'cycles': dict(zip(('checks', 'enabled', 'held', 'modes'), map(int, marker.groups()))),
        'executable_sha256': digest(binary),
        'log_sha256': digest(log),
    }
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')


if __name__ == '__main__':
    main()
