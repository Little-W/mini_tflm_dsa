#!/usr/bin/env python3
"""使用统一网表分析器测量前端和 DMA 公共输出的实际组合级数。"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from netlist_metrics import connected_paths, register_origins


def measure(folder, top):
    metrics = json.loads((folder / 'metrics.json').read_text())
    module = json.loads((folder / 'mapped.json').read_text())['modules'][top]
    for name, origin in register_origins(folder / 'pre_lut.il').items():
        if name in module['cells']:
            module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = origin
    names = ('wr_valid', 'wr_data', 'wr_mask', 'wr_last', 'tile_done', 'tile_error',
             'busy', 'tile_ready', 'cfg_ready') if top == 'conv_im2col_frontend' else (
             'wr_valid', 'wr_data', 'wr_row', 'wr_col_base', 'wr_slot',
             'win_rsp_valid', 'win_rsp_data', 'win_rsp_mask', 'win_rsp_last',
             'win_rsp_error', 'win_rsp_tag', 'rd_done', 'rd_busy', 'conv_cfg_ready')
    result = {'top': top, 'resources': metrics['resources'],
              'maximum_register_depth': metrics['paths']['longest_register_path_cells'],
              'outputs': {}}
    for port_name in names:
        marker = '$output$' + port_name
        # 端点标记仅用于分析，既不写入综合网表，也不计为组合逻辑单元。
        module['cells'][marker] = {
            'type': 'FDRE', 'connections': {'D': module['ports'][port_name]['bits']},
            'port_directions': {'D': 'input'},
            'attributes': {'fpga_register_origin': port_name}}
        paths = connected_paths(module, limit=1, group_limit=1,
            sink_filter=lambda name, cell, port: name == marker)
        selected = paths['register_to_register_paths']
        result['outputs'][port_name] = {
            'maximum_cells': paths['longest_register_path_cells'],
            'path': selected[0] if selected else None}
        if top == 'axi_dual_block_dma':
            paths = connected_paths(module, limit=1, group_limit=1,
                root_filter=lambda name, cell, port: cell.get('attributes', {}).get(
                    'fpga_register_origin', '').startswith('fe_output_'),
                sink_filter=lambda name, cell, port: name == marker)
            selected = paths['register_to_register_paths']
            result['outputs'][port_name]['registered_image_output'] = {
                'maximum_cells': paths['longest_register_path_cells'],
                'path': selected[0] if selected else None}
        del module['cells'][marker]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--folder', type=Path, required=True)
    parser.add_argument('--top', choices=('conv_im2col_frontend', 'axi_dual_block_dma'),
                        default='axi_dual_block_dma')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = measure(args.folder.resolve(), args.top)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    for name, output in result['outputs'].items():
        print(name, output['maximum_cells'],
              output.get('registered_image_output', {}).get('maximum_cells', ''), flush=True)


if __name__ == '__main__':
    main()
