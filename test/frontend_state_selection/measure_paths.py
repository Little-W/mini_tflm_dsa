#!/usr/bin/env python3
"""测量完整 DMA 中坐标及配置寄存器到前端状态的实际组合路径。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from netlist_metrics import connected_paths, register_origins


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mapped', type=Path, required=True)
    parser.add_argument('--pre-lut', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    module = json.loads(args.mapped.read_text())['modules']['axi_dual_block_dma']
    for name, origin in register_origins(args.pre_lut, top='axi_dual_block_dma').items():
        if name in module['cells']:
            module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = origin
    result = dict(mapped_sha256=digest(args.mapped), pre_lut_sha256=digest(args.pre_lut), paths={})
    for label, start in [('coordinate_to_state', 'u_runtime_registers.o_input_coordinate'),
                         ('configuration_to_state', 'u_runtime_registers.o_configuration')]:
        root = lambda name, cell, pin, start=start: start in cell.get('attributes', {}).get('fpga_register_origin', '')
        sink = lambda name, cell, pin: 'g_im2col.u_frontend.state ' in cell.get('attributes', {}).get('fpga_register_origin', '')
        paths = connected_paths(module, limit=3, group_limit=6, root_filter=root, sink_filter=sink)
        if not paths['graph_complete']:
            raise RuntimeError('完整 DMA 的组合连接分析未覆盖全部单元')
        result['paths'][label] = paths
        print(label, paths['longest_register_path_cells'], flush=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    main()
