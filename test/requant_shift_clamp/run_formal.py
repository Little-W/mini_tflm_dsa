#!/usr/bin/env python3
"""证明量化移位商的饱和输出、固定延迟与任意暂停行为。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-rev', default='2f06471c')
    parser.add_argument('--worker', type=Path)
    args = parser.parse_args()
    if args.worker:
        from pyosys import libyosys
        libyosys.run_pass('script ' + shlex.quote(str(args.worker)))
        return

    import pyosys
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = ROOT / 'rtl/npu/writeback/vec_requant.sv'
    reference = out / 'reference.sv'
    reference.write_bytes(read_rtl_source(args.reference_rev + ':rtl/npu/writeback/vec_requant.sv', cwd=ROOT))
    library = Path(pyosys.__file__).parent / 'share/xilinx/cells_sim.v'
    model = out / 'xilinx_lut6_2.sv'
    model.write_text(re.search(r'^module LUT6_2\b.*?^endmodule', library.read_text(), re.M | re.S).group(0) + '\n')
    arithmetic = ROOT / 'test/requant_pipeline/shift_formal.sv'
    scripts = {}
    for name, defines in [('fpga_math', '-D SYNTHESIS'), ('generic_math', '-D SYNTHESIS -D ASIC_SYNTHESIS')]:
        scripts[name] = (
            'read_slang --top shift_formal ' + defines + ' ' +
            ' '.join(shlex.quote(str(p)) for p in (source, arithmetic, model)) + '\n'
            'prep -top shift_formal -flatten\nasync2sync\nchformal -lower\n'
            'memory_map\nopt_clean\n'
            'sat -seq 1 -tempinduct -initsteps 8 -maxsteps 10 -prove-asserts -verify -set i_en 1\n')
    scripts['state_equivalence'] = ''
    for name, rtl in [('gold', reference), ('gate', source)]:
        scripts['state_equivalence'] += (
            'read_slang --top requant_shift_pipeline -D SYNTHESIS ' +
            ' '.join(shlex.quote(str(p)) for p in (rtl, model)) + '\n'
            'prep -top requant_shift_pipeline -flatten\nmemory_map\nopt_clean\n'
            f'rename requant_shift_pipeline {name}\ndesign -stash {name}\n')
    scripts['state_equivalence'] += (
        'design -copy-from gold -as gold gold\n'
        'design -copy-from gate -as gate gate\n'
        'equiv_make gold gate equiv\nhierarchy -top equiv\n'
        'equiv_simple\nequiv_induct -undef -seq 2\nequiv_status -assert\n')

    result = {
        'reference_rev': args.reference_rev,
        'reference_sha256': digest(reference),
        'source_sha256': digest(source),
        'primitive_library_sha256': digest(library),
        'latency_enabled_edges': 7,
        'product_bits': 64,
        'amount_bits': 7,
        'state_clock_enable_constrained': False,
        'runs': [],
    }
    for name, commands in scripts.items():
        script = out / (name + '.ys')
        log = out / (name + '.log')
        script.write_text(commands)
        with log.open('w') as stream:
            run = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--out', str(out),
                                  '--worker', str(script)], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
        text = log.read_text()
        marker = 'Equivalence successfully proven!' if name == 'state_equivalence' else 'Induction step proven'
        passed = run.returncode == 0 and marker in text
        result['runs'].append({'name': name, 'passed': passed, 'log_sha256': digest(log)})
        if not passed:
            print(text[-12000:])
            raise RuntimeError(name + ' did not complete successfully')
    result['passed'] = True
    (out / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
