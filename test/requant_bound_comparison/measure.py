#!/usr/bin/env python3
"""在固定器件映射条件下比较完整量化通道及生产配置量化模块。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = 'a235227e'
SOURCES = ['rtl/npu/writeback/requant_compute_lane.sv', 'rtl/npu/writeback/vec_requant.sv']
sys.path.insert(0, str(ROOT/'scripts/fpga'))
from netlist_metrics import connected_paths, register_origins


def run(command, log):
    with log.open('w') as stream:
        subprocess.run(list(map(str, command)), cwd=ROOT, stdout=stream,
                       stderr=subprocess.STDOUT, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference = []
    for relative in SOURCES:
        path = out/Path(relative).name
        path.write_bytes(subprocess.check_output(['git', 'show', f'{REFERENCE}:{relative}'], cwd=ROOT))
        reference.append(path)
    cases = {}
    for label in ('reference', 'candidate'):
        helpers = reference if label == 'reference' else [ROOT/name for name in SOURCES]
        for prefix, top, options in [
            ('lane', 'requant_compute_lane', ['-Gp_delayed_parameters=1']),
            ('vec', 'vec_requant', ['-GBUS_WIDTH=64', '-GVLEN=16', '-GMAX_IA_REUSE=32',
             '-GENABLE_S16=1', '-Gp_compute_lanes=2', '-Gp_input_rows=512', '-Gp_parameter_output=0'])]:
            cases[prefix+'_'+label] = {
                'top': top, 'sources': list(map(str, helpers)),
                'options': ['-DSYNTHESIS=1', '-DXILINX_FPGA=1', *options],
                'configuration': '完整量化模块的相同配置资源和实际寄存路径比较'}
    configuration = out/'cases.json'
    configuration.write_text(json.dumps(cases, ensure_ascii=False, indent=2)+'\n')
    result = {'reference_commit': REFERENCE, 'mapping': {'mode': 'physical-cost',
              'delay_target_ps': 6667, 'wire_delay_ps': 300, 'max_lut_inputs': 8}, 'cases': {}}
    for name, case in cases.items():
        pre = out/'pre_lut'/name
        mapped = out/(name+'_cost')
        run([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--case-config', configuration,
             '--cases', name, '--out', out/'pre_lut', '--through', 'pre_lut'], out/(name+'_pre.log'))
        run([sys.executable, ROOT/'scripts/fpga/remap_fpga_luts.py', '--source', pre,
             '--out', mapped, '--mode', 'physical-cost', '--delay-target-ps', '6667',
             '--wire-delay-ps', '300', '--max-lut-inputs', '8'], out/(name+'_map.log'))
        metrics = json.loads((mapped/'metrics.json').read_text())
        module = json.loads((mapped/'mapped.json').read_text())['modules'][case['top']]
        origins = register_origins(pre/'pre_lut.il', top=case['top'])
        for cell_name, cell in module['cells'].items():
            if cell_name in origins:
                cell.setdefault('attributes', {})['fpga_register_origin'] = origins[cell_name]
        if name.startswith('lane'):
            # 仅用于分析输入至寄存器的组合长度，测量标记不进入 RTL 或资源统计。
            bit = module['ports']['i_s16']['bits'][0]
            module['cells']['measurement_input_s16'] = {
                'type': 'FDRE', 'attributes': {'fpga_register_origin': 'i_s16'},
                'parameters': {}, 'connections': {'D': ['0'], 'Q': [bit], 'C': ['0'], 'CE': ['1'], 'R': ['0']},
                'port_directions': {'D': 'input', 'Q': 'output', 'C': 'input', 'CE': 'input', 'R': 'input'}}
        paths = {}
        for path_name, first, last in [('mode_to_round', 'i_s16' if name.startswith('lane') else 's16_mode', 'rounded_q'),
                                       ('tile_to_load', 'tile_row', 'load_offset')]:
            if name.startswith('lane') and path_name == 'tile_to_load':
                continue
            paths[path_name] = connected_paths(module, group_limit=8,
                root_filter=lambda n, c, p: first in c.get('attributes', {}).get('fpga_register_origin', ''),
                sink_filter=lambda n, c, p: last in c.get('attributes', {}).get('fpga_register_origin', ''))
        detail = {'resources': metrics['resources'],
                  'longest_register_path_cells': metrics['paths']['longest_register_path_cells'],
                  'paths': paths, 'manifest': json.loads((pre/'manifest.json').read_text()),
                  'mapped_sha256': hashlib.sha256((mapped/'mapped.json').read_bytes()).hexdigest()}
        result['cases'][name] = detail
        print(name, detail['resources']['logic_lut_cells'], detail['longest_register_path_cells'], flush=True)
    (out/'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    main()
