#!/usr/bin/env python3
"""测量完整权重加载器及其描述符选择、计数和比较路径。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts/fpga'))
from netlist_metrics import connected_paths, register_origins


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='548bda54')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    for name in ('kernel_loader', 'kernel_loader_ctrl'):
        (out/('reference_'+name+'.sv')).write_bytes(subprocess.check_output(
            ['git', 'show', args.reference+':rtl/npu/loaders/'+name+'.sv'], cwd=ROOT))
        (out/('current_'+name+'.sv')).write_bytes((ROOT/'rtl/npu/loaders'/(name+'.sv')).read_bytes())
    cases = {label: {'top': 'kernel_loader',
        'sources': [str(out/(label+'_'+name+'.sv')) for name in ('kernel_loader', 'kernel_loader_ctrl')],
        'options': ['-DSYNTHESIS=1', '-DXILINX_FPGA=1', '-GSIZE=16', '-GCOUNT_WIDTH=29', '-GBUS_WIDTH=64'],
        'configuration': '完整生产权重加载器'} for label in ('reference', 'current')}
    configuration = out/'cases.json'
    configuration.write_text(json.dumps(cases, indent=2)+'\n')
    subprocess.run([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py',
        '--case-config', configuration, '--cases', *cases, '--out', out/'mapping',
        '--through', 'pre_lut'], check=True, cwd=ROOT)
    records = {}
    for label in cases:
        source, cost = out/'mapping'/label, out/'cost'/label
        subprocess.run([sys.executable, ROOT/'scripts/fpga/remap_fpga_luts.py',
            '--source', source, '--out', cost, '--mode', 'physical-cost',
            '--delay-target-ps', '6667', '--wire-delay-ps', '300', '--max-lut-inputs', '8'], check=True, cwd=ROOT)
        module = json.loads((cost/'mapped.json').read_text())['modules']['kernel_loader']
        for name, origin in register_origins(source/'pre_lut.il', 'kernel_loader').items():
            if name in module['cells']:
                module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = origin
        next_bit = max(bit for cell in module['cells'].values() for values in cell['connections'].values()
                       for bit in values if isinstance(bit, int))+1
        # 分析终点表示端口边界，生产网表不增加寄存器或改变延迟。
        output = 'ext_dma_burst_len_m1'
        module['cells']['analysis_'+output] = {'type': 'FDRE', 'attributes': {}, 'parameters': {},
            'port_directions': {'D': 'input', 'Q': 'output'},
            'connections': {'D': module['ports'][output]['bits'], 'Q': [next_bit]}}
        record = {name: json.loads((cost/(name+'.json')).read_text()) for name in ('manifest', 'summary')}
        record['directed'] = {}
        for name, origin, endpoint in (
            ('prefetch_to_burst', 'prefetch_state', 'analysis_ext_dma_burst_len_m1'),
            ('count_to_pending', 'u_ctrl.issued_count', 'u_ctrl.load_pending_q'),
            ('position_to_match', 'u_ctrl.column_position_q', 'comparison_match_q'),
            ('row_step_to_address', 'u_ctrl.row_addr_step', 'u_ctrl.dma_address_q')):
            result = connected_paths(module, limit=1, group_limit=0,
                root_filter=lambda n, c, p, origin=origin:
                    (c.get('attributes', {}).get('fpga_register_origin') or '').split(' [')[0] == origin,
                sink_filter=lambda n, c, p, endpoint=endpoint:
                    n == endpoint or (c.get('attributes', {}).get('fpga_register_origin') or '').split(' [')[0] == endpoint)
            if not result['graph_complete']:
                raise RuntimeError('定向路径分析图不完整：'+name)
            record['directed'][name] = result
        records[label] = record
        print(label, record['summary']['resources']['logic_lut_cells'],
              {name: value['longest_register_path_cells'] for name, value in record['directed'].items()}, flush=True)
    (out/'measurement.json').write_text(json.dumps(records, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    main()
