#!/usr/bin/env python3
"""测量读取保护器的固定源码、Xilinx 资源和组合逻辑深度。"""
import argparse
import collections
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = 'rtl/npu/conv/conv_axi_read_guard.sv'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-ref')
    parser.add_argument('--data-width', type=int, default=64)
    args = parser.parse_args()
    out = args.out.resolve()
    snapshot = out / 'sources'
    snapshot.mkdir(parents=True, exist_ok=True)
    content = (subprocess.check_output(['git', 'show', f'{args.reference_ref}:{SOURCE}'], cwd=ROOT)
               if args.reference_ref else (ROOT / SOURCE).read_bytes())
    source = snapshot / Path(SOURCE).name
    source.write_bytes(content)
    import pyosys
    library = Path(pyosys.__file__).parent / 'share/xilinx/cells_sim.v'
    primitive_model = snapshot / 'lut6_2.sv'
    primitive_model.write_text(re.search(r'^module LUT6_2\b.*?^endmodule', library.read_text(), re.M | re.S).group(0) + '\n')
    top = 'conv_axi_read_guard'
    mapped = out / 'mapped.json'
    script = out / 'run.ys'
    script.write_text(f'read_slang -D SYNTHESIS=1 --top {top} -GADDR_W=32 -GDATA_W={args.data_width} -GSPLIT_GEMM_4K=1 ' +
        shlex.quote(str(source)) + ' ' + shlex.quote(str(primitive_model)) + '\n' + f'hierarchy -check -top {top}\n' +
        f'synth_xilinx -top {top} -family xc7 -noiopad -noclkbuf -flatten\n' +
        'check -assert\nstat -tech xilinx\nwrite_json ' + shlex.quote(str(mapped)) + '\n')
    with (out / 'synthesis.log').open('w') as log:
        subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                        '--worker', str(script)], stdout=log, stderr=subprocess.STDOUT, check=True)
    sys.path.insert(0, str(ROOT / 'scripts/fpga'))
    spec = importlib.util.spec_from_file_location('fpga_synth', ROOT / 'scripts/fpga/open_fpga_synth.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    cells = json.loads(mapped.read_text())['modules'][top]['cells']
    counts = collections.Counter(cell['type'] for cell in cells.values())
    path = module.logic_depth(cells)
    result = {'scope': top, 'family': 'xc7', 'reference_ref': args.reference_ref,
              'source_sha256': {SOURCE: hashlib.sha256(content).hexdigest()},
              'primitive_library_sha256': hashlib.sha256(library.read_bytes()).hexdigest(),
              'source_snapshot': str(snapshot), 'ADDR_W': 32, 'DATA_W': args.data_width,
              'SPLIT_GEMM_4K': 1,
              'lut_cells': sum(n for cell, n in counts.items() if re.fullmatch(r'LUT(?:[1-6]|6_2)', cell)),
              'flip_flops': sum(n for cell, n in counts.items() if cell.startswith(('FDCE', 'FDPE', 'FDRE', 'FDSE'))),
              'carry4': counts['CARRY4'],
              'longest_combinational_path_cells': len(path),
              'longest_combinational_path': path, 'cell_counts': dict(sorted(counts.items()))}
    (out / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({key: result[key] for key in
                     ('lut_cells', 'flip_flops', 'carry4', 'longest_combinational_path_cells')}))


if __name__ == '__main__':
    main()
