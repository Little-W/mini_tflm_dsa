#!/usr/bin/env python3
"""统计前端坐标、分组配置和预计算终点到消费寄存器的实际组合路径。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from netlist_metrics import analyze, connected_paths, register_origins


def configuration_bits():
    source = (ROOT / 'rtl/npu/conv/conv_im2col_pkg.sv').read_text()
    body = re.search(r'typedef struct packed \{(.*?)\} conv_cfg_t;', source, re.S).group(1)
    body = re.sub(r'//[^\n]*', '', body)
    fields = []
    for match in re.finditer(r'logic\s+(?:signed\s+)?(?:\[(\d+):(\d+)\]\s+)?([^;]+);', body):
        width = int(match.group(1)) - int(match.group(2)) + 1 if match.group(1) else 1
        fields.extend((name.strip(), width) for name in match.group(3).split(','))
    result, offset = {}, 0
    for name, width in reversed(fields):
        result[name] = [offset, offset + width - 1]
        offset += width
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mapped', type=Path, required=True)
    parser.add_argument('--pre-lut', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    module = json.loads(args.mapped.read_text())['modules']['conv_im2col_frontend']
    for name, origin in register_origins(args.pre_lut).items():
        if name in module['cells']:
            module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = origin
    group_low, group_high = configuration_bits()['group_c']
    result = {'netlist_sha256': hashlib.sha256(args.mapped.read_bytes()).hexdigest(),
              'pre_lut_sha256': hashlib.sha256(args.pre_lut.read_bytes()).hexdigest(),
              'configuration_group_bits': [group_low, group_high],
              'complete_module': analyze(module), 'register_groups': {}}
    for signal in ('ix', 'c.group_c', 'group_high_minus_one_q', 'last_input_col_q',
                   'last_group_channel_q', 'kernel_width_valid_q'):
        def selected(name, cell, port):
            origin = cell.get('attributes', {}).get('fpga_register_origin') or ''
            if signal == 'c.group_c':
                match = re.fullmatch(r'c \[(\d+)\]', origin)
                return bool(match and group_low <= int(match.group(1)) <= group_high)
            return bool(re.match(re.escape(signal) + r'(?: \[|$)', origin))

        paths = connected_paths(module, limit=100000, group_limit=100000, root_filter=selected)
        targets = {}
        for target in ('state', 'addr', 'q_current'):
            matches = [path for path in paths['register_to_register_paths']
                       if (path['endpoint'].get('register_origin') or '').startswith(target + ' ')]
            targets[target] = {'longest_path_cells': max((path['combinational_cells'] for path in matches), default=0),
                               'longest_paths': matches[:1]}
        result['register_groups'][signal] = {'longest_path_cells': paths['longest_register_path_cells'],
                                             'targets': targets,
                                             'longest_paths': paths['register_to_register_paths'][:1]}
    # 只为连接图设置输入端口起点，原始映射网表与资源统计均保持完整。
    for index, bit in enumerate(module['ports']['tile_p0']['bits']):
        if isinstance(bit, int):
            name = f'input_position_root[{index}]'
            if name in module['cells']:
                raise ValueError('Analysis root name already exists')
            module['cells'][name] = {
                'type': 'FDRE', 'attributes': {'fpga_register_origin': f'input tile_p0 [{index}]'},
                'parameters': {}, 'port_directions': {'Q': 'output', 'C': 'input'},
                'connections': {'Q': [bit], 'C': module['ports']['clk']['bits']}}
    selected = lambda name, cell, port: (cell.get('attributes', {}).get('fpga_register_origin') or '').startswith('input tile_p0 ')
    paths = connected_paths(module, limit=100000, group_limit=100000, root_filter=selected)
    result['input_position_paths'] = {}
    for target in ('oy_q', 'state', 'request_epoch_q', 'request_index_q', 'request_progress_q'):
        matches = [path for path in paths['register_to_register_paths']
                   if (path['endpoint'].get('register_origin') or '').startswith(target + ' ')]
        data = [path for path in matches if path['endpoint']['category'] == 'data']
        control = [path for path in matches if path['endpoint']['category'] == 'control']
        result['input_position_paths'][target] = {
            'data_path_cells': max((path['combinational_cells'] for path in data), default=0),
            'control_path_cells': max((path['combinational_cells'] for path in control), default=0),
            'data_paths': data[:1], 'control_paths': control[:1]}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'module_max': result['complete_module']['paths']['longest_register_path_cells'],
                      'roots': {name: {target: value['longest_path_cells']
                                      for target, value in data['targets'].items()}
                                for name, data in result['register_groups'].items()},
                      'input_position': {name: data['data_path_cells']
                                         for name, data in result['input_position_paths'].items()}}))


if __name__ == '__main__':
    main()
