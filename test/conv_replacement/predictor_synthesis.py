#!/usr/bin/env python3
"""记录下一次访问预测器的固定源码、Xilinx 资源和组合逻辑级数。"""
import argparse
import collections
import hashlib
import json
from pathlib import Path
import re
import resource
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-ref')
    args = parser.parse_args()
    out = args.out.resolve()
    snapshot = out / 'sources'
    snapshot.mkdir(parents=True, exist_ok=True)
    names = ('rtl/npu/conv/conv_im2col_pkg.sv',
             'rtl/npu/dma/cache/conv_next_use_predictor.sv')
    sources = []
    hashes = {}
    for name in names:
        content = (read_rtl_source(f'{args.reference_ref}:{name}', cwd=ROOT)
                   if args.reference_ref else (ROOT / name).read_bytes())
        hashes[name] = hashlib.sha256(content).hexdigest()
        path = snapshot / Path(name).name
        path.write_bytes(content)
        sources.append(path)
    helper = ROOT / 'rtl/common/onehot_check.sv'
    sources.append(helper)
    hashes[str(helper.relative_to(ROOT))] = hashlib.sha256(helper.read_bytes()).hexdigest()
    sys.path.insert(0, str(ROOT / 'scripts/fpga'))
    import open_fpga_synth as module
    import pyosys
    primitive_options, primitive_manifest = module.primitive_models(
        out, [str(helper)], Path(pyosys.__file__).parent / 'share/xilinx')
    top = 'conv_next_use_predictor'
    mapped = out / 'mapped.json'
    pre_lut = out / 'pre_lut.il'
    script = out / 'run.ys'
    script.write_text(f'read_slang --top {top} -D XILINX_FPGA {primitive_options} ' +
        ' '.join(shlex.quote(str(path)) for path in sources) + '\n' +
        'read_verilog -lib -specify -overwrite +/xilinx/cells_sim.v\n' +
        f'hierarchy -check -top {top}\n' +
        f'synth_xilinx -top {top} -family xc7 -noiopad -noclkbuf -flatten -run begin:map_luts\n' +
        'write_rtlil ' + shlex.quote(str(pre_lut)) + '\n' +
        f'synth_xilinx -top {top} -family xc7 -noiopad -noclkbuf -flatten -run map_luts:\n' +
        'check -assert\nstat -tech xilinx\nwrite_json ' + shlex.quote(str(mapped)) + '\n')
    with (out / 'synthesis.log').open('w') as log:
        subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                        '--worker', str(script)], stdout=log, stderr=subprocess.STDOUT, check=True)
    from netlist_metrics import analyze, connected_paths, register_origins
    design = json.loads(mapped.read_text())['modules'][top]
    cells = design['cells']
    for name, origin in register_origins(pre_lut).items():
        if name in cells:
            cells[name].setdefault('attributes', {})['fpga_register_origin'] = origin
    metrics = analyze(design)
    coordinate_paths = connected_paths(design, limit=20, group_limit=20,
        root_filter=lambda name, cell, port: cell['type'] == 'DSP48E1',
        sink_filter=lambda name, cell, port:
            cell.get('attributes', {}).get('fpga_register_origin') == 'coordinate_good_s1')
    if not metrics['paths']['graph_complete'] or not coordinate_paths['graph_complete']:
        raise RuntimeError('Incomplete predictor register path graph')
    counts = collections.Counter(cell['type'] for cell in cells.values())
    path = module.logic_depth(cells)
    result = {'scope': top, 'family': 'xc7', 'reference_ref': args.reference_ref,
              'source_sha256': hashes, 'source_snapshot': str(snapshot),
              'primitive_models': primitive_manifest,
              'lut_cells': sum(n for cell, n in counts.items() if re.fullmatch(r'LUT[1-6](?:_2)?', cell)),
              'flip_flops': sum(n for cell, n in counts.items() if cell.startswith(('FDCE', 'FDPE', 'FDRE', 'FDSE'))),
              'dsp': counts['DSP48E1'], 'carry4': counts['CARRY4'],
              'longest_combinational_path_cells': len(path),
              'longest_combinational_path': path, 'cell_counts': dict(sorted(counts.items())),
              'resources': metrics['resources'], 'paths': metrics['paths'],
              'dsp_to_coordinate_good_paths': coordinate_paths,
              'maximum_resident_kib': resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
              'mapped_sha256': hashlib.sha256(mapped.read_bytes()).hexdigest(),
              'pre_lut_sha256': hashlib.sha256(pre_lut.read_bytes()).hexdigest()}
    (out / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({key: result[key] for key in
                     ('lut_cells', 'flip_flops', 'dsp', 'carry4', 'longest_combinational_path_cells')}))
    print(json.dumps({'longest_register_path_cells': metrics['paths']['longest_register_path_cells'],
                      'dsp_to_coordinate_good_cells': coordinate_paths['longest_register_path_cells']}))


if __name__ == '__main__':
    main()
