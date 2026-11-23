#!/usr/bin/env python3
"""证明读取保护器完整状态和公开输出的逐周期等价性。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]
SOURCE = 'rtl/npu/conv/conv_axi_read_guard.sv'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-ref', default='cd0455b')
    parser.add_argument('--fpga', action='store_true')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    original = read_rtl_source(f'{args.reference_ref}:{SOURCE}', cwd=ROOT)
    current = (ROOT / SOURCE).read_bytes()
    reference = out / 'reference.sv'
    candidate = out / 'current.sv'
    reference.write_bytes(original)
    candidate.write_bytes(current)
    primitive_options = ' -D ASIC_SYNTHESIS=1'
    primitive_library_sha256 = None
    if args.fpga:
        import pyosys
        library = Path(pyosys.__file__).parent / 'share/xilinx/cells_sim.v'
        model = out / 'lut6_2.sv'
        model.write_text(re.search(r'^module LUT6_2\b.*?^endmodule', library.read_text(), re.M | re.S).group(0) + '\n')
        primitive_options = ' -D SYNTHESIS=1 ' + shlex.quote(str(model))
        primitive_library_sha256 = hashlib.sha256(library.read_bytes()).hexdigest()
    cases = [(32, width, split) for width in (32, 64) for split in (0, 1)]
    cases += [(16, 16, 1), (33, 128, 1), (40, 256, 1)]
    runs = []
    dependencies = runpy.run_path(str(ROOT / 'scripts/rtl/source_files.py'))['with_dependencies']
    for address_width, data_width, split in cases:
        folder = out / f'a{address_width}_d{data_width}_s{split}'
        folder.mkdir(exist_ok=True)
        options = f'-GADDR_W={address_width} -GDATA_W={data_width} -GSPLIT_GEMM_4K={split}'
        commands = []
        for name, source in (('reference', reference), ('current', candidate)):
            sources = dependencies([source], ROOT)
            commands.extend([
                f'read_slang --top conv_axi_read_guard {options} {shlex.join(map(str, sources))}{primitive_options}',
                'prep -top conv_axi_read_guard -flatten', 'memory_map', 'async2sync', 'opt_clean',
                f'rename conv_axi_read_guard {name}', f'design -stash {name}',
            ])
        commands.extend([
            'design -copy-from reference -as reference reference',
            'design -copy-from current -as current current',
            'equiv_make reference current equivalent', 'hierarchy -top equivalent',
            'equiv_simple -seq 1', 'opt_clean', 'equiv_induct -seq 2', 'equiv_status -assert',
        ])
        script = folder / 'run.ys'
        script.write_text('\n'.join(commands) + '\n')
        log = folder / 'formal.log'
        with log.open('w') as stream:
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                     '--worker', str(script)], cwd=ROOT, stdout=stream,
                                    stderr=subprocess.STDOUT)
        text = log.read_text()
        match = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', text)
        passed = result.returncode == 0 and 'Equivalence successfully proven' in text
        entry = {'ADDR_W': address_width, 'DATA_W': data_width, 'SPLIT_GEMM_4K': split,
                 'passed': passed, 'equivalent_bits': int(match[1]) if match else None,
                 'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest()}
        runs.append(entry)
        print(json.dumps(entry), flush=True)
        if not passed:
            raise RuntimeError(text[-9000:])
    if (ROOT / SOURCE).read_bytes() != current:
        raise RuntimeError('RTL source changed during verification')
    summary = {'passed': True, 'reference_ref': args.reference_ref, 'inputs_constrained': False,
               'fpga': args.fpga, 'primitive_library_sha256': primitive_library_sha256,
               'source_sha256': hashlib.sha256(current).hexdigest(),
               'reference_sha256': hashlib.sha256(original).hexdigest(), 'runs': runs}
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')


if __name__ == '__main__':
    main()
