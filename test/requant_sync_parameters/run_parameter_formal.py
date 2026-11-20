#!/usr/bin/env python3
"""比较参数存储、输入参数采样与完整控制接口，保留任意配置和暂停。"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]


def run(out, name, commands):
    script = out / (name + '.ys')
    log = out / (name + '.log')
    script.write_text(commands)
    with log.open('w') as stream:
        process = subprocess.run([sys.executable, __file__, '--out', str(out), '--worker', str(script)],
                                 cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
    if process.returncode:
        raise RuntimeError(log.read_text()[-12000:])
    return log


def memory_interfaces(module, label):
    """按独立字段比较实际存储模型，并将存储输出作为公共任意输入。"""
    result = {}
    for name, cell in list(module['cells'].items()):
        match = re.search(r'\.gen_is_parameter_bank\[(\d+)\]\.u_(\w+)\.mem$', name)
        if not match:
            continue
        assert cell['type'] == '$mem_v2', (name, cell['type'])
        parameters = cell['parameters']
        connections = cell['connections']
        width = int(parameters['WIDTH'], 2)
        depth = int(parameters['SIZE'], 2)
        assert int(parameters['RD_PORTS'], 2) == 1
        assert int(parameters['WR_PORTS'], 2) == 1
        assert parameters['RD_CLK_ENABLE'] == '0'
        fields = [(match[2], 0, width)]
        if label == 'reference':
            prepared = 'product_multiplier' if match[2] == 'multiplier' else 'product_amount'
            fields = [(match[2], 0, 32), (prepared, 32, width - 32)]
        for field, offset, field_width in fields:
            key = match[1] + '_' + field
            normalized = dict(parameters)
            normalized.pop('MEMID')
            normalized['WIDTH'] = format(field_width, '032b')
            for parameter in ('INIT', 'RD_INIT_VALUE', 'RD_ARST_VALUE', 'RD_SRST_VALUE'):
                # Yosys 常量字符串按高位在前排列，字段投影先转为低位在前。
                bits = parameters[parameter][::-1]
                projected = ''.join(bits[index + offset:index + offset + field_width]
                                    for index in range(0, len(bits), width))
                normalized[parameter] = projected[::-1]
            data = connections['RD_DATA'][offset:offset + field_width]
            read_port = 'memory_data_' + key
            module['ports'][read_port] = {'direction': 'input', 'bits': data}
            module['netnames'][read_port] = {'hide_name': 0, 'bits': data, 'attributes': {}}
            driven = []
            for port in sorted(connections):
                if port == 'RD_DATA':
                    continue
                bits = connections[port]
                if port in ('WR_DATA', 'WR_EN'):
                    bits = bits[offset:offset + field_width]
                driven += bits
            drive_port = 'memory_drive_' + key
            module['ports'][drive_port] = {'direction': 'output', 'bits': driven}
            module['netnames'][drive_port] = {'hide_name': 0, 'bits': driven, 'attributes': {}}
            result[key] = {'parameters': normalized, 'width': field_width, 'depth': depth,
                           'driven_bits': len(driven)}
        del module['cells'][name]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-rev', default='4ae43ade')
    parser.add_argument('--worker', type=Path)
    parser.add_argument('--bus', type=int, default=64)
    parser.add_argument('--lanes', type=int, default=16)
    parser.add_argument('--reuse', type=int, default=32)
    args = parser.parse_args()
    if args.worker:
        from pyosys import libyosys
        libyosys.run_pass('script ' + shlex.quote(str(args.worker)))
        return
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    relative = 'rtl/npu/writeback/vec_requant.sv'
    scalar_relative = 'rtl/npu/conv/vector_scalar_multiplier.sv'
    modules = {}
    memory_models = {}
    source_hashes = {}
    for label in ('reference', 'candidate'):
        paths = []
        for stem, path in [('requant', relative), ('scalar', scalar_relative)]:
            data = (read_rtl_source(args.reference_rev + ':' + path, cwd=ROOT)
                    if label == 'reference' else (ROOT / path).read_bytes())
            target = out / (label + '_' + stem + '.sv')
            target.write_bytes(data)
            paths.append(target)
            source_hashes[label + '_' + stem] = hashlib.sha256(data).hexdigest()
        paths.append(ROOT / 'rtl/common/regfile.v')
        raw = out / (label + '_raw.json')
        run(out, label + '_elaborate',
            f'read_slang --top vec_requant -D SYNTHESIS -D ASIC_SYNTHESIS -GBUS_WIDTH={args.bus} '
            f'-GVLEN={args.lanes} -GMAX_IA_REUSE={args.reuse} -GENABLE_S16=1 ' +
            ' '.join(shlex.quote(str(path)) for path in paths) + '\n'
            'prep -top vec_requant -flatten\nwrite_json ' + str(raw) + '\n')
        module = json.loads(raw.read_text())['modules']['vec_requant']
        # 运算部分分别验证；此处直接观察实际乘法输入和移位量采样。
        for name in ('out_vec_s8', 'out_vec_s16'):
            module['ports'].pop(name)
        captured = []
        for lane in range(args.lanes):
            prefix = f'g_full.u_full.LANE[{lane}].'
            for suffix in ('u_product.operand_a', 'u_product.operand_b', 'amount_s0'):
                captured += module['netnames'][prefix + suffix]['bits']
        module['ports']['captured_parameters'] = {'direction': 'output', 'bits': captured}
        module['netnames']['captured_parameters'] = {'hide_name': 0, 'bits': captured, 'attributes': {}}
        for item in list(module['netnames'].values()) + list(module['cells'].values()):
            item.get('attributes', {}).pop('keep', None)
        memory_models[label] = memory_interfaces(module, label)
        trimmed = out / (label + '_trimmed.json')
        trimmed.write_text(json.dumps({'modules': {'vec_requant': module}}))
        mapped = out / (label + '_mapped.json')
        run(out, label + '_storage', 'read_json ' + str(trimmed) + '\nopt_clean\nmemory_map\nopt -full\n'
            'write_json ' + str(mapped) + '\n')
        modules[label] = json.loads(mapped.read_text())['modules']['vec_requant']

    # 字段存储的模型参数全部相同，形式比较继续检查全部驱动端口。
    # 任意读值下驱动端口与采样结果一致，保证相同初始字段状态持续产生相同读值。
    assert memory_models['reference'] == memory_models['candidate']
    assert len(memory_models['reference']) == 4 * (args.bus // 32)
    reference = modules['reference']
    common = set(reference['netnames']) & set(modules['candidate']['netnames'])
    delayed_parameters = re.compile(
        r'\.(?:ch_product_(?:multiplier|amount)_is_(?:read|sel)(?:\[\d+\])?'
        r'|product_(?:multiplier_sel|amount_sel|i_b)|u_product\.i_b)$')
    common = {name for name in common
              if len(reference['netnames'][name]['bits']) == len(modules['candidate']['netnames'][name]['bits'])
              and not delayed_parameters.search(name)
              and all(not modules[label]['netnames'][name]['hide_name'] for label in modules)}
    for label, module in modules.items():
        kept = set(module['ports']) | common
        nets = {}
        for index, (name, value) in enumerate(module['netnames'].items()):
            key = name if name in kept else f'$formal_{label}_{index}'
            nets[key] = value
        module['netnames'] = nets
        (out / (label + '.json')).write_text(json.dumps({'modules': {label: module}}))
    log = run(out, 'compare',
        'read_json ' + str(out / 'reference.json') + '\ndesign -stash reference\n'
        'read_json ' + str(out / 'candidate.json') + '\ndesign -stash candidate\n'
        'design -copy-from reference -as reference reference\n'
        'design -copy-from candidate -as candidate candidate\n'
        'equiv_make reference candidate equiv\nhierarchy -top equiv\nopt_clean\nopt_merge\n'
        'equiv_simple -seq 2\nequiv_induct -seq 4\nequiv_status -assert\n')
    text = log.read_text()
    assert 'Equivalence successfully proven' in text
    result = {'passed': True, 'reference_rev': args.reference_rev,
              'bus_width': args.bus, 'lanes': args.lanes, 'reuse': args.reuse,
              'inputs_constrained': False, 'source_sha256': source_hashes,
              'memory_models': {
                  name: {key: value for key, value in model.items() if key != 'parameters'}
                  for name, model in memory_models['reference'].items()},
              'memory_parameters_sha256': hashlib.sha256(json.dumps(
                  memory_models['reference'], sort_keys=True).encode()).hexdigest(),
              'stored_bits_compared': sum(item['width'] * item['depth']
                                          for item in memory_models['reference'].values()),
              'memory_read_data': 'Unconstrained each cycle; corresponding field models and every driven port are compared.',
              'captured_parameter_bits': args.lanes * 71,
              'equivalent_bits': int(re.search(r'Of those cells (\d+) are proven', text)[1]),
              'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest()}
    (out / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
