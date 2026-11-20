#!/usr/bin/env python3
"""检查计算单元在两种权重装载模式下的完整寄存状态和输出。"""
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
SOURCE = Path('rtl/npu/compute/ws_systolic_cell.sv')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', default='653477ed')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    import pyosys
    library = Path(pyosys.__file__).parent / 'share/xilinx/cells_sim.v'
    primitive = re.search(r'^module LUT6_2\b.*?^endmodule', library.read_text(), re.MULTILINE | re.DOTALL).group(0)
    model = out / 'LUT6_2.sv'
    model.write_text(re.sub(r'\bspecify\b.*?\bendspecify\b', '', primitive, flags=re.DOTALL) + '\n')
    reference = out / 'reference.sv'
    reference.write_bytes(read_rtl_source(f'{args.reference}:{SOURCE}', cwd=ROOT))
    current = out / 'current.sv'
    current.write_bytes((ROOT / SOURCE).read_bytes())
    summary = {'reference': args.reference, 'source_sha256': hashlib.sha256(current.read_bytes()).hexdigest(),
               'reference_sha256': hashlib.sha256(reference.read_bytes()).hexdigest(), 'runs': []}
    for data_width, weight_width, sum_width in ((1, 1, 2), (8, 8, 32), (16, 8, 32), (16, 16, 32), (17, 17, 40)):
        for exchange in (0, 1):
            label = f'd{data_width}_w{weight_width}_a{sum_width}_e{exchange}'
            folder = out / label
            folder.mkdir(exist_ok=True)
            options = (f'-GDATA_IN_WIDTH={data_width} -GWEIGHT_WIDTH={weight_width} '
                       f'-GACC_WIDTH={sum_width} -Gp_exchange_weights={exchange}')
            commands = []
            for variant, source in (('reference', reference), ('current', current)):
                commands += [f'read_slang --top ws_systolic_cell -D SYNTHESIS=1 {options} '
                             + shlex.quote(str(source)) + ' ' + shlex.quote(str(model)),
                             'proc', 'opt', f'rename ws_systolic_cell {variant}', f'design -stash {variant}']
            commands += ['design -copy-from reference -as reference reference',
                         'design -copy-from current -as current current',
                         'equiv_make reference current equivalent', 'hierarchy -top equivalent',
                         'opt_clean', 'equiv_simple -undef -seq 2', 'equiv_induct -undef -seq 2', 'equiv_status -assert']
            script = folder / 'run.ys'
            script.write_text('\n'.join(commands) + '\n')
            log_path = folder / 'formal.log'
            with log_path.open('w') as log:
                completed = subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                            '--worker', str(script)], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
            log_text = log_path.read_text()
            count = re.search(r'Of those cells (\d+) are proven and 0 are unproven', log_text)
            passed = completed.returncode == 0 and count is not None
            row = {'data_width': data_width, 'weight_width': weight_width, 'sum_width': sum_width,
                   'exchange_weights': bool(exchange), 'proven_bits': int(count[1]) if count else 0, 'passed': passed}
            summary['runs'].append(row)
            print(json.dumps(row), flush=True)
            if not passed:
                raise RuntimeError(f'Equivalence check did not complete: {log_path}')
    if current.read_bytes() != (ROOT / SOURCE).read_bytes():
        raise RuntimeError('RTL changed during verification')
    summary['passed'] = True
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')


if __name__ == '__main__':
    main()
