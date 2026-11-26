#!/usr/bin/env python3
"""成对测量共享通道的资源与请求到物理 RAM 读取使能的路径。"""
from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
spec = spec_from_file_location('shared_read_measurement', ROOT / 'test/ps_shared_read_control/measure.py')
support = module_from_spec(spec)
spec.loader.exec_module(support)
support.REFERENCE = '584233d8'
support.PROFILES = {'shared': support.PROFILES['shared']}
base_paths = support.targeted_paths


def targeted_paths(module, pre, profile):
    results = base_paths(module, pre, profile)
    spare = max(bit for net in module['netnames'].values() for bit in net['bits']
                if isinstance(bit, int)) + 100
    for name, net in list(module['netnames'].items()):
        if name == 'ps_read_select' or name.startswith('ps_read_select['):
            for index, bit in enumerate(net['bits']):
                module['cells'][f'analysis_read_selection_{name}_{index}'] = dict(
                    type='FDRE', parameters={}, attributes={}, port_directions={'D': 'input', 'Q': 'output'},
                    connections={'D': [bit], 'Q': [spare]})
                spare += 1
    targets = {
        'fixed_read_enable': lambda name, cell, port: 'g_fixed_channel' in name and port == 'ENBWREN',
        'read_selection': lambda name, cell, port: name.startswith('analysis_read_selection_'),
        'return_selection': lambda name, cell, port: 'ps_return_select_q' in
            cell.get('attributes', {}).get('fpga_register_origin', ''),
    }
    for start in ['i_ps_read_en', 'i_access_enable']:
        for end, sink in targets.items():
            result = support.connected_paths(module, limit=4, group_limit=4,
                root_filter=lambda name, cell, port, start=start: name.startswith('analysis_input_' + start + '_'),
                sink_filter=sink)
            if not result['graph_complete']:
                raise RuntimeError('共享读取路径分析未完成')
            results[start + '_to_' + end] = result
    return results


if __name__ == '__main__':
    support.targeted_paths = targeted_paths
    support.main()
    index = sys.argv.index('--out')
    result_path = Path(sys.argv[index + 1]).resolve() / 'measurement.json'
    result = json.loads(result_path.read_text())
    result['runner_sha256'] = support.digest(Path(__file__))
    result['measurement_support_sha256'] = support.digest(ROOT / 'test/ps_shared_read_control/measure.py')
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
