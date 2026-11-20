#!/usr/bin/env python3
"""独立综合前端控制和地址运算，将缓存与预测器作为接口边界。"""
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

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-ref')
    parser.add_argument('--current-source', type=Path)
    parser.add_argument('--lanes', type=int, choices=(1, 2, 4), default=4)
    args = parser.parse_args()
    out = args.out.resolve()
    snapshot = out / 'sources'
    snapshot.mkdir(parents=True, exist_ok=True)
    names = ('rtl/npu/conv/conv_im2col_pkg.sv', 'rtl/npu/conv/conv_im2col_frontend.sv',
             'rtl/npu/dma/cache/conv_read_cache.sv', 'rtl/npu/dma/cache/conv_next_use_predictor.sv')
    sources, hashes = [], {}
    for name in names:
        content = (read_rtl_source(f'{args.reference_ref}:{name}', cwd=ROOT)
                   if args.reference_ref else
                   (args.current_source if args.current_source and name == names[1] else ROOT / name).read_bytes())
        hashes[name] = hashlib.sha256(content).hexdigest()
        path = snapshot / Path(name).name
        path.write_bytes(content)
        if name in names[2:]:
            header = content.decode().split(');', 1)[0] + ');\nendmodule\n'
            path = snapshot / (Path(name).stem + '_interface.sv')
            path.write_text(header)
        sources.append(path)
    helpers = [ROOT / name for name in ('rtl/common/onehot_check.sv', 'rtl/common/add_equal.sv', 'rtl/common/regfile.v')]
    sources.extend(helpers)
    for helper in helpers:
        hashes[str(helper.relative_to(ROOT))] = hashlib.sha256(helper.read_bytes()).hexdigest()
    sys.path.insert(0, str(ROOT / 'scripts/fpga'))
    import open_fpga_synth as module
    import pyosys
    primitive_options, primitive_manifest = module.primitive_models(
        out, [str(helper) for helper in helpers], Path(pyosys.__file__).parent / 'share/xilinx')
    top = 'conv_im2col_frontend'
    mapped = out / 'mapped.json'
    pre_lut = out / 'pre_lut.il'
    script = out / 'run.ys'
    script.write_text(f'read_slang --keep-hierarchy --top {top} -D XILINX_FPGA -GSIZE=16 -GBUS_WIDTH=64 -GLANES={args.lanes} {primitive_options} ' +
        ' '.join(shlex.quote(str(path)) for path in sources) + '\n' +
        'read_verilog -lib -specify -overwrite +/xilinx/cells_sim.v\n' +
        'blackbox conv_read_cache* conv_next_use_predictor*\n' +
        f'hierarchy -check -top {top}\n' +
        f'synth_xilinx -top {top} -family xc7 -noiopad -noclkbuf -flatten -run begin:map_luts\n' +
        'write_rtlil ' + shlex.quote(str(pre_lut)) + '\n' +
        f'synth_xilinx -top {top} -family xc7 -noiopad -noclkbuf -flatten -run map_luts:\n' +
        'check -assert\nstat -tech xilinx\nwrite_json ' + shlex.quote(str(mapped)) + '\n')
    with (out / 'synthesis.log').open('w') as log:
        subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                        '--worker', str(script)], stdout=log, stderr=subprocess.STDOUT, check=True)
    cells = json.loads(mapped.read_text())['modules'][top]['cells']
    cache = [cell for cell in cells.values() if cell['type'].startswith('conv_read_cache')]
    predictor = [cell for cell in cells.values() if cell['type'].startswith('conv_next_use_predictor')]
    assert len(cache) == 1 and len(predictor) == 1
    assert len(cache[0]['connections']['rdata']) == 64
    assert len(cache[0]['connections']['req_addr']) == 32
    counts = collections.Counter(cell['type'] for cell in cells.values())
    path = module.logic_depth(cells)
    connected_report = out / 'paths.json'
    subprocess.run([sys.executable, str(ROOT / 'test/conv_frontend/tools/measure_descriptor_paths.py'),
                    '--mapped', str(mapped), '--pre-lut', str(pre_lut), '--out', str(connected_report)],
                   cwd=ROOT, check=True, capture_output=True, text=True)
    connected = json.loads(connected_report.read_text())
    internal = connected['internal_paths']
    assert internal['graph_complete']
    result = {'scope': 'conv_im2col_frontend; cache and predictor are black boxes', 'family': 'xc7',
              'reference_ref': args.reference_ref, 'source_sha256': hashes, 'source_snapshot': str(snapshot),
              'primitive_models': primitive_manifest,
              'pre_lut_netlist': str(pre_lut),
              'configuration': {'SIZE': 16, 'BUS_WIDTH': 64, 'LANES': args.lanes,
                                'CACHE_SETS': 128, 'CACHE_WAYS': 2, 'LINE_BYTES': 16},
              'lut_cells': sum(n for cell, n in counts.items() if re.fullmatch(r'LUT[1-6](?:_2)?', cell)),
              'flip_flops': sum(n for cell, n in counts.items() if cell.startswith(('FDCE', 'FDPE', 'FDRE', 'FDSE'))),
              'dsp': counts['DSP48E1'], 'carry4': counts['CARRY4'],
              'longest_combinational_path_cells': internal['longest_register_path_cells'],
              'longest_combinational_path': internal['register_to_register_paths'][0],
              'connected_path_metrics': str(connected_report),
              'path_method': internal['path_method'], 'coarse_cell_graph_depth': len(path),
              'maximum_resident_kib': resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
              'cell_counts': dict(sorted(counts.items()))}
    (out / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({key: result[key] for key in
                     ('lut_cells', 'flip_flops', 'dsp', 'carry4', 'longest_combinational_path_cells', 'maximum_resident_kib')}))


if __name__ == '__main__':
    main()
