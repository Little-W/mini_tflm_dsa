#!/usr/bin/env python3
"""比较共享存储返回选择器的全部输入组合。"""
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
SOURCE = Path('rtl/npu/buffers/ia_ps_shared_ram.sv')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', default='653477ed')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    import pyosys
    text = (Path(pyosys.__file__).parent / 'share/xilinx/cells_sim.v').read_text()
    blocks = []
    for name in ('LUT6', 'MUXF7', 'MUXF8'):
        block = re.search(r'^module ' + name + r'\b.*?^endmodule', text, re.M | re.S).group(0)
        blocks.append(re.sub(r'\bspecify\b.*?\bendspecify\b', '', block, flags=re.S))
    model = out / 'primitives.sv'
    model.write_text('\n'.join(blocks) + '\n')
    original = read_rtl_source(f'{args.reference}:{SOURCE}', cwd=ROOT)
    reference = out / 'reference.sv'
    reference.write_bytes(original)
    summary = {'reference': args.reference, 'source_sha256': hashlib.sha256((ROOT / SOURCE).read_bytes()).hexdigest(),
               'reference_sha256': hashlib.sha256(original).hexdigest(), 'runs': []}
    for inputs, select_bits in ((5, 3), (7, 3), (8, 3), (9, 4), (16, 4), (7, 5)):
        label = f'inputs{inputs}_select{select_bits}'
        options = f'-Gp_width=5 -Gp_inputs={inputs} -Gp_select_width={select_bits}'
        commands = []
        for variant, source in (('reference', reference), ('current', ROOT / SOURCE)):
            commands += [f'read_slang --top shared_ram_read_mux -D SYNTHESIS=1 {options} '
                         + shlex.quote(str(source)) + ' ' + shlex.quote(str(model)),
                         'prep -top shared_ram_read_mux -flatten',
                         f'rename shared_ram_read_mux {variant}', f'design -stash {variant}']
        commands += ['design -copy-from reference -as reference reference',
                     'design -copy-from current -as current current',
                     'miter -equiv -flatten -make_outputs reference current equivalent',
                     'hierarchy -top equivalent', 'sat -verify -prove trigger 0 -show-inputs -show-outputs']
        script = out / (label + '.ys')
        script.write_text('\n'.join(commands) + '\n')
        log_path = out / (label + '.log')
        with log_path.open('w') as log:
            completed = subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                        '--worker', str(script)], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        passed = completed.returncode == 0 and 'no model found: SUCCESS!' in log_path.read_text()
        row = {'inputs': inputs, 'select_bits': select_bits, 'data_bits': 5, 'passed': passed}
        summary['runs'].append(row)
        print(json.dumps(row), flush=True)
        if not passed:
            raise RuntimeError(f'Selector verification did not complete: {log_path}')
    summary['passed'] = True
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')


if __name__ == '__main__':
    main()
