#!/usr/bin/env python3
"""比较32/64位读取保护器在每个周期的全部公开输出。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
SOURCE = 'rtl/npu/conv/conv_axi_read_guard.sv'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-ref', default='aa2ef9a3')
    parser.add_argument('--verilator', default='verilator')
    parser.add_argument('--fpga', action='store_true')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference = out / 'reference.sv'
    content = subprocess.check_output(['git', 'show', f'{args.reference_ref}:{SOURCE}'], cwd=ROOT, text=True)
    reference.write_text(content.replace('module conv_axi_read_guard', 'module reference_conv_axi_read_guard'))
    sources = [ROOT / SOURCE, reference, HERE / 'tb_guard_compare.sv']
    options = []
    primitive_library_sha256 = None
    if args.fpga:
        import pyosys
        library = Path(pyosys.__file__).parent / 'share/xilinx/cells_sim.v'
        model = out / 'lut6_2.sv'
        model.write_text(re.search(r'^module LUT6_2\b.*?^endmodule', library.read_text(), re.M | re.S).group(0) + '\n')
        sources.append(model)
        options.append('-DSYNTHESIS=1')
        primitive_library_sha256 = hashlib.sha256(library.read_bytes()).hexdigest()
    hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    obj = out / 'obj'
    command = [shutil.which(args.verilator) or args.verilator, '--binary', '--timing', '--assert',
               '-Wno-fatal', '--top-module', 'tb_guard_compare', '--Mdir', str(obj), '-j', '2', *options, *map(str, sources)]
    with (out / 'build.log').open('w') as log:
        subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    with (out / 'run.log').open('w') as log:
        subprocess.run([str(obj / 'Vtb_guard_compare')], cwd=ROOT, stdout=log,
                       stderr=subprocess.STDOUT, check=True, timeout=60)
    output = (out / 'run.log').read_text()
    if 'GUARD_COMPARE_PASS cycles=50000 configurations=4' not in output:
        raise AssertionError('comparison success marker missing')
    if output.count('GUARD_COMPARE_CASE_PASS') != 4:
        raise AssertionError('comparison coverage missing')
    for path, digest in hashes.items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest:
            raise AssertionError(f'source changed during comparison: {path}')
    result = {'passed': True, 'reference_ref': args.reference_ref, 'source_sha256': hashes,
              'fpga': args.fpga, 'primitive_library_sha256': primitive_library_sha256,
              'cycles_per_configuration': 50000,
              'configurations': [{'DATA_W': width, 'SPLIT_GEMM_4K': split}
                                 for width in (32, 64) for split in (0, 1)],
              'summary': output.strip()}
    (out / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    print(output.strip())


if __name__ == '__main__':
    main()
