#!/usr/bin/env python3
"""分别测量完整模块的寄存器路径和公开端口边界。"""
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


def measure(folder, top):
    folder = folder.resolve()
    module = json.loads((folder / 'mapped.json').read_text())['modules'][top]
    metrics = json.loads((folder / 'metrics.json').read_text())
    if metrics['paths']['graph_complete'] is not True:
        raise RuntimeError('模块寄存器图未完成：' + str(folder))
    for name, origin in register_origins(folder / 'pre_lut.il').items():
        if name in module['cells']:
            module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = origin
    outputs = ['out_data'] if top == 'vector_softmax' else (
        ['load_ia_req'] if top == 'ia_loader' else [])
    inputs = [] if top == 'vector_softmax' else (
        ['ext_dma_wr_data', 'ext_dma_wr_col_base', 'ext_dma_wr_valid'] if top == 'ia_loader' else
        ['wr_data', 'wr_col_base', 'wr_valid'])
    result = dict(resources=metrics['resources'], register_paths=metrics['paths'],
                  source_manifest=json.loads((folder / 'manifest.json').read_text()),
                  mapped_sha256=digest(folder / 'mapped.json'),
                  pre_lut_sha256=digest(folder / 'pre_lut.il'), boundaries={})
    for port in outputs:
        marker = '$boundary_output$' + port
        # 这些标记仅表示公开端口的观察位置，不增加寄存器或组合单元。
        module['cells'][marker] = dict(type='FDRE', connections={'D': module['ports'][port]['bits']},
            port_directions={'D': 'input'}, attributes={'fpga_register_origin': port})
        paths = connected_paths(module, limit=1, group_limit=1,
            sink_filter=lambda name, cell, pin: name == marker)
        result['boundaries'][port] = dict(scope='内部时钟寄存器输出到公开输出端口', paths=paths)
        del module['cells'][marker]
    for port in inputs:
        names = [name for name in module['ports'] if name == port or name.startswith(port + '[')]
        marker = '$boundary_input$' + port
        module['cells'][marker] = dict(type='FDRE',
            connections={'Q': [bit for name in names for bit in module['ports'][name]['bits']]},
            port_directions={'Q': 'output'}, attributes={'fpga_register_origin': port})
        paths = connected_paths(module, limit=1, group_limit=1,
            root_filter=lambda name, cell, pin: name == marker,
            sink_filter=lambda name, cell, pin: 'ram_shared_wr_data' in
                cell.get('attributes', {}).get('fpga_register_origin', ''))
        result['boundaries'][port] = dict(scope='公开输入端口到共享写数据寄存器的同步输入', paths=paths)
        del module['cells'][marker]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--top', required=True,
                        choices=('vector_softmax', 'ia_loader', 'ia_loader_cache_mgr'))
    parser.add_argument('--reference-folder', type=Path, required=True)
    parser.add_argument('--current-folder', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = dict(top=args.top,
        reference=measure(args.reference_folder, args.top),
        current=measure(args.current_folder, args.top),
        runner_sha256=digest(Path(__file__).resolve()))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    for label in ('reference', 'current'):
        print(label, 'registers', result[label]['register_paths']['longest_register_path_cells'])
        for name, value in result[label]['boundaries'].items():
            print(label, name, value['paths']['longest_register_path_cells'])


if __name__ == '__main__':
    main()
