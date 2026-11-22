#!/usr/bin/env python3
"""测量完整 FIFO 的寄存状态到输出阻塞接口的组合路径。"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from netlist_metrics import connected_paths, register_origins


def read_payload(path: Path) -> bytes:
    if path.exists():
        return path.read_bytes()
    return gzip.decompress(path.with_name(path.name + '.gz').read_bytes())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--current', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = {}
    for label, folder in (('reference', args.reference), ('current', args.current)):
        payload = read_payload(folder / 'mapped.json')
        module = json.loads(payload)['modules']['vec_s8_to_fifo']
        origins = folder / 'pre_lut.il'
        if not origins.exists():
            origins = origins.with_name(origins.name + '.gz')
        for name, origin in register_origins(origins).items():
            if name in module['cells']:
                module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = origin
        bank_bits = set(module['netnames']['g_full.u_full.bank_ready']['bits'])
        saved_bits = set()
        for name in ('write_bank_blocked_q', 'next_write_bank_blocked_q'):
            net = module['netnames'].get('g_full.u_full.' + name)
            if net:
                saved_bits.update(net['bits'])
        new_bit = max(bit for net in module['netnames'].values()
                      for bit in net['bits'] if isinstance(bit, int)) + 1
        # 仅在分析图中添加接收端，实际 RTL 的输出接口不增加周期。
        module['cells']['analysis_full'] = {
            'type': 'FDRE', 'parameters': {},
            'attributes': {'fpga_register_origin': 'fifo_full_flag'},
            'connections': {'C': ['0'], 'CE': ['1'], 'R': ['0'],
                            'D': module['ports']['fifo_full_flag']['bits'], 'Q': [new_bit]},
            'port_directions': {'C': 'input', 'CE': 'input', 'R': 'input',
                                'D': 'input', 'Q': 'output'},
        }
        paths = {}
        for key, bits in (('bank_ready', bank_bits), ('saved_blocked', saved_bits),
                          ('all_registers', None)):
            paths[key] = connected_paths(
                module, limit=4, group_limit=8,
                root_filter=lambda name, cell, port, bits=bits:
                    name != 'analysis_full' and
                    (bits is None or bool(bits.intersection(cell['connections'].get('Q', [])))),
                sink_filter=lambda name, cell, port: name == 'analysis_full' and port == 'D')
            if not paths[key]['graph_complete']:
                raise RuntimeError('FIFO path graph is incomplete')
        result[label] = {'mapped_sha256': hashlib.sha256(payload).hexdigest(), 'paths': paths}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + '\n')
    print({label: {name: path['longest_register_path_cells']
                   for name, path in item['paths'].items()} for label, item in result.items()})


if __name__ == '__main__':
    main()
