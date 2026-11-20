#!/usr/bin/env python3
"""测量完整写回模块的地址共享及原生组合路径。"""
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
SOURCE = Path('rtl/npu/writeback/oa_writer.sv')
ADDRESS_STATE = ('tile_base_addr_cur', 'row_group_base_addr_cur', 'column_base_addr',
                 'next_address_base', 'next_address_step')
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
    parser.add_argument('--count-width', type=int, default=29)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    original = out / 'reference.sv'
    original.write_text(read_rtl_source(args.reference + ':' + str(SOURCE), cwd=ROOT, text=True))
    current = out / 'current.sv'
    current.write_bytes((ROOT / SOURCE).read_bytes())
    cases = {name: {'top': 'oa_writer',
                   'options': ['-D', 'SYNTHESIS=1', '-GVLEN=16', '-GBUS_WIDTH=64',
                               f'-GCOUNT_WIDTH={args.count_width}'],
                   'sources': [str(source)], 'configuration': '完整输出写回控制，原生算术映射'}
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
              'count_width': args.count_width, 'dsp_remapping': False,
              'physical_lut_packing': False,
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
synth_xilinx -top oa_writer -family xc7 -noiopad -noclkbuf -run finalize:
check -assert
write_json {shlex.quote(str(target))}
stat
''')
        stage = run_stage(script, folder / 'native_map.log', dict(os.environ))
        module = json.loads(target.read_text())['modules']['oa_writer']
        for cell, origin in register_origins(pre).items():
            if cell in module['cells']:
                module['cells'][cell].setdefault('attributes', {})['fpga_register_origin'] = origin
        report['mapping'][name] = {'resources': resources(module['cells']),
                                   'paths': connected_paths(module, limit=6, group_limit=128),
                                   'address_paths': connected_paths(module, limit=4, group_limit=8,
                                       sink_filter=lambda name, cell, port: any(state in
                                           cell.get('attributes', {}).get('fpga_register_origin', '')
                                           for state in ADDRESS_STATE)),
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
