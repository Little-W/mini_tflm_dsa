#!/usr/bin/env python3
"""在无输入约束下证明完整偏置组状态与行索引逐周期等价。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

from extract_control import ROOT, TOP, control_region, module_source

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

PROFILES = ((1, 1, 32), (4, 1, 32), (16, 4, 32), (16, 32, 32),
            (16, 64, 32), (32, 1, 32), (32, 32, 16), (32, 64, 64))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='e5ae51f1')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = (ROOT / TOP).read_text()
    reference = read_rtl_source(args.reference + ':' + str(TOP), cwd=ROOT, text=True)
    import pyosys
    library = Path(pyosys.__file__).parent / 'share/xilinx/cells_sim.v'
    model_text = re.search(r'^module LUT6_2\b.*?^endmodule', library.read_text(), re.M | re.S)[0]
    model = out / 'lut6_2.sv'
    model.write_text(re.sub(r'\bspecify\b.*?\bendspecify\b', '', model_text, flags=re.S) + '\n')
    snapshots = {}
    for label, content in [('reference', reference), ('current', current)]:
        snapshots[label] = out / (label + '.sv')
        snapshots[label].write_text(module_source(content))
    report = {
        'reference': args.reference,
        'source_sha256': {str(TOP): digest(ROOT / TOP)},
        'reference_source_sha256': hashlib.sha256(reference.encode()).hexdigest(),
        'region_sha256': {label: hashlib.sha256(control_region(content).encode()).hexdigest()
                          for label, content in [('reference', reference), ('current', current)]},
        'snapshot_sha256': {label: digest(path) for label, path in snapshots.items()},
        'primitive_library_sha256': digest(library),
        'primitive_model_sha256': digest(model),
        'inputs_constrained': False,
        'profiles': [],
    }
    for size, groups, width in PROFILES:
        for fpga in (True, False):
            folder = out / f's{size}_g{groups}_r{width}_{"fpga" if fpga else "generic"}'
            folder.mkdir(exist_ok=True)
            commands = []
            define = '-D XILINX_FPGA -D VERIFIC' if fpga else '-D ASIC_SYNTHESIS'
            for label, snapshot in snapshots.items():
                commands += [
                    f'read_slang --top bias_row_control -GSIZE={size} '
                    f'-GBIAS_GROUP_BLOCKS_MAX={groups} -GREG_WIDTH={width} {define} '
                    + ' '.join(shlex.quote(str(p)) for p in (snapshot, model, ROOT / 'rtl/common/unsigned_compare.sv')),
                    'prep -top bias_row_control -flatten', 'async2sync', 'opt -full',
                    f'rename bias_row_control {label}', f'design -stash {label}',
                ]
            commands += ['design -copy-from reference -as reference reference',
                         'design -copy-from current -as current current',
                         'equiv_make reference current equivalent', 'hierarchy -top equivalent',
                         'equiv_simple -seq 1', 'opt_clean', 'equiv_induct -seq 1',
                         'equiv_status -assert']
            script, log = folder / 'run.ys', folder / 'formal.log'
            script.write_text('\n'.join(commands) + '\n')
            with log.open('w') as stream:
                result = subprocess.run(
                    [sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'), '--worker', str(script)],
                    cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, timeout=180)
            text = log.read_text()
            match = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', text)
            assert result.returncode == 0 and 'Equivalence successfully proven' in text, log
            run = {'SIZE': size, 'BIAS_GROUP_BLOCKS_MAX': groups, 'REG_WIDTH': width,
                   'fpga': fpga, 'passed': True, 'equivalent_bits': int(match[1]),
                   'script_sha256': digest(script), 'log_sha256': digest(log)}
            report['profiles'].append(run)
            print(json.dumps(run), flush=True)
    assert digest(ROOT / TOP) == report['source_sha256'][str(TOP)]
    report['passed'] = True
    report['equivalent_bits'] = sum(run['equivalent_bits'] for run in report['profiles'])
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
