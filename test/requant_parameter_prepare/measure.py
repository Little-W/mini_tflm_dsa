#!/usr/bin/env python3
"""测量完整量化模块的原生算术映射和寄存器路径。"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/writeback/vec_requant.sv')
PARAMETER_STATE = ('pt_multiplier_r', 'pt_shift_r', 'pt_product_multiplier_r',
                   'pt_product_amount_r', 'mul_base_r', 'sh_base_r', 's16_mode')
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
sys.path.insert(0, str(ROOT / 'test'))
from netlist_metrics import connected_paths, register_origins, resources
from open_fpga_synth import run_stage
from rtl_reference import read_rtl_source


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='2297cb12')
    parser.add_argument('--lanes', type=int, default=2)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    original = out / 'reference.sv'
    original.write_text(read_rtl_source(args.reference + ':' + str(SOURCE), cwd=ROOT, text=True))
    current = out / 'current.sv'
    current.write_bytes((ROOT / SOURCE).read_bytes())
    dependencies = [ROOT / name for name in (
        'rtl/npu/writeback/requant_compute_lane.sv',
        'rtl/npu/writeback/requant_group_buffer.sv',
        'rtl/npu/conv/vector_scalar_multiplier.sv',
        'rtl/common/regfile.v')]
    cases = {name: {'top': 'vec_requant_full',
                   'options': ['-D', 'SYNTHESIS=1', '-GBUS_WIDTH=64', '-GVLEN=16',
                               '-GMAX_IA_REUSE=32', '-GENABLE_S16=1',
                               f'-Gp_compute_lanes={args.lanes}', '-Gp_input_rows=512'],
                   'sources': [str(source), *map(str, dependencies)],
                   'configuration': '完整量化接口、512行缓存、原生算术映射'}
             for name, source in (('reference', original), ('current', current))}
    configuration = out / 'cases.json'
    configuration.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + '\n')
    with (out / 'prepare.log').open('w') as log:
        subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                        '--case-config', str(configuration), '--cases', 'reference', 'current',
                        '--out', str(out / 'native'), '--through', 'pre_lut'],
                       cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    cost = out / 'unit_lut_cost.lut'
    cost.write_text(''.join(f'{width} 1 1\n' for width in range(1, 7)))
    report = {'source_sha256': digest(current), 'reference': args.reference,
              'compute_lanes': args.lanes, 'dsp_remapping': False,
              'physical_lut_packing': False,
              'dependency_sha256': {str(p.relative_to(ROOT)): digest(p) for p in dependencies},
              'mapping': {}}
    for name in ('reference', 'current'):
        folder = out / 'native' / name
        pre = folder / 'pre_lut.il'
        target = folder / 'mapped.json'
        script = folder / 'native_map.ys'
        script.write_text(f'''read_rtlil {shlex.quote(str(pre))}
read_verilog -lib -specify -overwrite +/xilinx/cells_sim.v
read_verilog -lib -overwrite +/xilinx/cells_xtra.v
opt_expr -mux_undef -noclkinv
read_verilog -icells -lib -specify +/xilinx/abc9_model.v
scratchpad -set abc9.xaiger 1
scratchpad -set abc9.verify 1
abc9 -W 500 -lut {shlex.quote(str(cost))} -D 6667
clean
techmap -map +/xilinx/lut_map.v -map +/xilinx/cells_map.v -D LUT_WIDTH=6
xilinx_dffopt
opt_lut_ins -tech xilinx
synth_xilinx -top vec_requant_full -family xc7 -noiopad -noclkbuf -run finalize:
check -assert
write_json {shlex.quote(str(target))}
stat
''')
        stage = run_stage(script, folder / 'native_map.log', dict(os.environ))
        module = json.loads(target.read_text())['modules']['vec_requant_full']
        for cell, origin in register_origins(pre).items():
            if cell in module['cells']:
                module['cells'][cell].setdefault('attributes', {})['fpga_register_origin'] = origin
        report['mapping'][name] = {'resources': resources(module['cells']),
                                   'paths': connected_paths(module, limit=6, group_limit=128),
                                   'parameter_paths': connected_paths(module, limit=4, group_limit=8,
                                       root_filter=lambda name, cell, port: any(state in
                                           cell.get('attributes', {}).get('fpga_register_origin', '')
                                           for state in PARAMETER_STATE)),
                                   'mapped_json_sha256': digest(target), 'stage': stage}
        for path in (target, pre, folder / 'elaborated.il'):
            with path.open('rb') as source, gzip.open(str(path) + '.gz', 'wb') as dest:
                shutil.copyfileobj(source, dest)
            path.unlink()
    if digest(current) != digest(ROOT / SOURCE):
        raise RuntimeError('测量期间 RTL 内容发生变化')
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({name: {'lut': row['resources']['logic_lut_cells'],
                            'ff': row['resources']['flip_flops'],
                            'maximum_depth': row['paths']['longest_register_path_cells']}
                      for name, row in report['mapping'].items()}, indent=2), flush=True)


if __name__ == '__main__':
    main()
