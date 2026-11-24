#!/usr/bin/env python3
"""从完整 DMA 映射结果中提取描述符接收和完成状态的连接路径。"""
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

CONTROL_REGISTERS = {
    'conv_pending', 'conv_finished', 'conv_active', 'conv_command_error',
    'descriptor_error', 'conv_done_r', 'conv_done_error', 'command_im2col',
    'configuration_available_q',
}


def retained(folder, name):
    path = folder / name
    return path if path.exists() else path.with_suffix(path.suffix + '.gz')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--folder', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--maximum', type=int, default=11)
    args = parser.parse_args()
    folder = args.folder.resolve()
    path = retained(folder, 'mapped.json')
    raw = gzip.open(path, 'rb').read() if path.suffix == '.gz' else path.read_bytes()
    module = json.loads(raw)['modules']['axi_dual_block_dma']
    for name, origin in register_origins(retained(folder, 'pre_lut.il')).items():
        if name in module['cells']:
            module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = origin

    def selected(name, cell, port):
        origin = cell.get('attributes', {}).get('fpga_register_origin', '')
        return origin.split(' [', 1)[0] in CONTROL_REGISTERS

    paths = connected_paths(module, limit=20, group_limit=20, sink_filter=selected)
    if not paths['register_to_register_paths']:
        raise RuntimeError('No connected control path was found')
    metrics = json.loads((folder / 'metrics.json').read_text())
    passed = paths['graph_complete'] and paths['longest_register_path_cells'] <= args.maximum
    report = {
        'passed': passed,
        'source_mapped_sha256': hashlib.sha256(raw).hexdigest(),
        'selected_registers': sorted(CONTROL_REGISTERS),
        'required_maximum': args.maximum,
        'complete_dma_maximum': metrics['paths']['longest_register_path_cells'],
        'paths': paths,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({
        'passed': passed, 'maximum_control_path_cells': paths['longest_register_path_cells'],
        'complete_dma_maximum': report['complete_dma_maximum'],
        'graph_complete': paths['graph_complete'],
    }))
    if not passed:
        raise RuntimeError('DMA control paths exceed the requested maximum')


if __name__ == '__main__':
    main()
