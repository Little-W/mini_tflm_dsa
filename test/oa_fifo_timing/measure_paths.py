#!/usr/bin/env python3
"""测量行分块控制到 FIFO 数据有效寄存器的实际连接路径。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from netlist_metrics import connected_paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--synthesis', type=Path, required=True)
    args = parser.parse_args()
    summary = {}
    for label in ('reference', 'current'):
        folder = args.synthesis.resolve() / label
        design = json.loads((folder / 'mapped.json').read_text())
        module = design['modules']['oa_fifo_timing_top']
        roots, sink_bits = set(), set()
        for name, net in module['netnames'].items():
            if name in ('u_writer.co_current_rows', 'u_writer.co_valid_rows', 'u_writer.co_current_row_tiles_q'):
                roots.update(net['bits'])
            if name == 'u_fifo.co_data_valid':
                sink_bits.update(net['bits'])
        sinks = {name for name, cell in module['cells'].items()
                 if set(cell['connections'].get('Q', [])) & sink_bits}
        if not roots or not sinks:
            raise RuntimeError('Expected writer or FIFO register was not found')
        report = connected_paths(module,
            root_filter=lambda _name, cell, port: bool(set(cell['connections'].get(port, [])) & roots),
            sink_filter=lambda name, _cell, _port: name in sinks)
        if not report['graph_complete'] or not report['register_to_register_paths']:
            raise RuntimeError('The register connection graph is incomplete')
        (folder / 'row_tiles_to_fifo.json').write_text(json.dumps(report, indent=2) + '\n')
        summary[label] = {'longest_register_path_cells': report['longest_register_path_cells'],
                          'graph_complete': report['graph_complete']}
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
