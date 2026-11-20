#!/usr/bin/env python3
"""测量组首触发信号到实际存储地址端口的组合路径。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from netlist_metrics import connected_paths, register_origins


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mapped', type=Path, required=True)
    parser.add_argument('--pre-lut', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    module = json.loads(args.mapped.read_text())['modules']['bias_loader_buffer']
    for name, origin in register_origins(args.pre_lut).items():
        if name in module['cells']:
            module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = origin
    spare = max(bit for net in module['netnames'].values() for bit in net['bits']
                if isinstance(bit, int)) + 1
    trigger = module['ports']['send_ia_trigger']['bits']
    module['cells']['analysis_send_ia_trigger'] = {
        'type': 'FDRE', 'parameters': {}, 'attributes': {},
        'port_directions': {'D': 'input', 'Q': 'output'},
        'connections': {'D': [spare], 'Q': trigger},
    }
    root = lambda name, cell, port: name == 'analysis_send_ia_trigger'
    sink = lambda name, cell, port: cell['type'].startswith('RAMB') and port.startswith('ADDR')
    paths = connected_paths(module, limit=1, group_limit=0, root_filter=root, sink_filter=sink)
    if not paths['graph_complete']:
        raise RuntimeError('Mapped connectivity graph is incomplete')
    report = {'mapped_sha256': hashlib.sha256(args.mapped.read_bytes()).hexdigest(),
              'pre_lut_sha256': hashlib.sha256(args.pre_lut.read_bytes()).hexdigest(),
              'trigger_to_memory_address': paths}
    args.out.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'trigger_to_memory_address_cells': paths['longest_register_path_cells']}))


if __name__ == '__main__':
    main()
