#!/usr/bin/env python3
"""比较双 DMA 的全部状态、公开输出以及各个子模块接口。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "test"))
from reference_sources import read_reference_file
TOP = 'axi_dual_block_dma'
RTL = 'rtl/npu/dma/axi_dual_block_dma.sv'
PACKAGE = 'rtl/npu/conv/conv_im2col_pkg.sv'
CHILDREN = (
    'rtl/npu/dma/axi_linear_block_dma.sv',
    'rtl/npu/dma/conv_window_queue.sv',
    'rtl/npu/dma/dma_register_buffer.sv',
    'rtl/npu/dma/axi_write_page_guard.sv',
    'rtl/npu/conv/conv_im2col_frontend.sv',
    'rtl/npu/conv/conv_axi_read_guard.sv',
    'rtl/npu/conv/conv_axi_read_mux.sv',
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(out, name, commands):
    script, log = out / (name + '.ys'), out / (name + '.log')
    script.write_text('\n'.join(commands) + '\n')
    with log.open('w') as stream:
        subprocess.run(
            [sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
             '--worker', str(script)], cwd=ROOT, stdout=stream,
            stderr=subprocess.STDOUT, check=True, timeout=180)
    return log


def module_header(source):
    """参数及端口声明保留原文，由子模块输出提供任意返回信号。"""
    masked = re.sub(r'//[^\n]*|/\*.*?\*/', lambda match: ' ' * len(match[0]),
                    source, flags=re.S)
    beginning = re.search(r'\bmodule\s+\w+', masked)
    if beginning is None:
        raise ValueError('Module declaration is missing')
    ending = masked.index(';', beginning.end()) + 1
    return source[:ending] + '\nendmodule\n'


def expand_ports(path, output):
    design = json.loads(path.read_text())
    module = design['modules'][TOP]
    descriptions = []
    for instance, cell in sorted(list(module['cells'].items())):
        if cell['type'].startswith('$'):
            continue
        if not any(cell['type'].startswith(Path(name).stem) for name in CHILDREN):
            raise RuntimeError('Unexpected child module: ' + cell['type'])
        del module['cells'][instance]
        for port, bits in sorted(cell['connections'].items()):
            direction = cell['port_directions'][port]
            if direction not in ('input', 'output'):
                raise RuntimeError('Unsupported child port direction')
            selected = (list(dict.fromkeys(bit for bit in bits if isinstance(bit, int)))
                        if direction == 'output' else bits)
            if not selected:
                continue
            name = 'formal_' + instance.replace('.', '_') + '_' + port
            module['ports'][name] = {
                'direction': 'input' if direction == 'output' else 'output',
                'bits': selected,
            }
            module['netnames'][name] = {'hide_name': 0, 'bits': selected, 'attributes': {}}
            descriptions.append({'instance': instance, 'port': port,
                                 'direction_at_child': direction, 'bits': len(selected)})
    design['modules'] = {TOP: module}
    output.write_text(json.dumps(design) + '\n')
    return descriptions


def match_optional_inputs(reference, current):
    """为参照接口补充可选输入；新增输入在参照设计中保持未使用。"""
    left, right = [json.loads(path.read_text()) for path in (reference, current)]
    target, candidate = left['modules'][TOP], right['modules'][TOP]
    added = []
    for name, port in candidate['ports'].items():
        if name in target['ports']:
            continue
        if name != 'rd_image_columns' or port['direction'] != 'input':
            raise RuntimeError('Unsupported optional input: ' + name)
        used = [bit for net in target['netnames'].values() for bit in net['bits'] if isinstance(bit, int)]
        first = max(used, default=1) + 1
        bits = list(range(first, first + len(port['bits'])))
        target['ports'][name] = {'direction': 'input', 'bits': bits}
        target['netnames'][name] = {'hide_name': 0, 'bits': bits, 'attributes': {}}
        added.append(name)
    reference.write_text(json.dumps(left) + '\n')
    return added


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference-rev', required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--prepared-image-columns', action='store_true',
                        help='将保存列数按已证明的原始列数关系连接，并检查启用配置')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    files = (RTL, PACKAGE) + CHILDREN
    source_hashes = {name: digest(ROOT / name) for name in files}
    snapshots = {}
    snapshot_hashes = {}
    for label in ('reference', 'current'):
        folder = out / label
        folder.mkdir(exist_ok=True)
        snapshots[label] = []
        snapshot_hashes[label] = {}
        for name in (PACKAGE, RTL) + CHILDREN:
            data = (read_reference_file(ROOT, args.reference_rev, name)
                    if label == 'reference' else (ROOT / name).read_bytes())
            snapshot_hashes[label][name] = hashlib.sha256(data).hexdigest()
            text = data.decode()
            if args.prepared_image_columns and label == 'current' and name == RTL:
                text = text.replace("parameter bit p_prepared_image_columns = 1'b0",
                                    "parameter bit p_prepared_image_columns = 1'b1")
                declaration = re.search(r'^.*input[^\n]*\brd_image_columns\b[^\n]*\n', text, re.M)
                if declaration is None:
                    raise RuntimeError('Prepared column input is missing')
                text = text[:declaration.start()] + text[declaration.end():]
                connection = '''    logic [CONV_RW-1:0] rd_image_columns;
    assign rd_image_columns=(rd_valid_cols>0 && rd_valid_cols<=REG_WIDTH'(IM2COL_SIZE)) ?
        CONV_RW'(rd_valid_cols) : CONV_RW'(IM2COL_SIZE);
'''
                text = text.replace('    logic job_conv, job_read_guard;',
                                    connection + '    logic job_conv, job_read_guard;')
            if name in CHILDREN:
                text = module_header(text)
            path = folder / Path(name).name
            path.write_text(text)
            snapshots[label].append(path)
    for name in (PACKAGE,) + CHILDREN:
        reference = (out / 'reference' / Path(name).name).read_bytes()
        current = (out / 'current' / Path(name).name).read_bytes()
        if reference != current:
            raise RuntimeError('Child interface or package differs: ' + name)

    profiles = [
        ('image32_w4', 16, 16, 16, 32, 4, 1),
        ('image32_w8', 16, 64, 16, 32, 8, 32),
        ('image64_w4', 16, 64, 16, 64, 4, 32),
        ('image64_w8', 16, 64, 16, 64, 8, 32),
        ('image64_s64', 16, 64, 64, 64, 8, 32),
        ('linear_data8', 8, 64, 16, 64, 8, 32),
        ('linear_bus128', 16, 64, 16, 128, 8, 32),
    ]
    report = {
        'passed': False, 'reference_revision': args.reference_rev,
        'source_sha256': source_hashes, 'snapshot_sha256': snapshot_hashes,
        'public_inputs_constrained': False, 'child_outputs_constrained': False,
        'prepared_image_columns': args.prepared_image_columns,
        'prepared_input_relation': 'The saved columns equal normalization of the raw command field; proven separately across command capture events.' if args.prepared_image_columns else None,
        'scope': 'Every public output, every shared clocked state, and every unchanged child port',
        'profiles': [],
    }
    for name, data, size, image_size, bus, lanes, blocks in profiles:
        options = [
            '-DSYNTHESIS=1', '-DXILINX_FPGA=1', f'-GDATA_WIDTH={data}',
            f'-GSIZE={size}', f'-GIM2COL_SIZE={image_size}', f'-GBUS_WIDTH={bus}',
            f'-GWINDOW_LANES={lanes}', f'-GCACHE_BLOCKS={blocks}',
        ]
        ports = {}
        for label in ('reference', 'current'):
            raw = out / (name + '_' + label + '.json')
            expanded = out / (name + '_' + label + '_expanded.json')
            commands = [
                'read_slang --keep-hierarchy --top ' + TOP + ' ' +
                shlex.join(options + list(map(str, snapshots[label]))),
                'blackbox ' + ' '.join(Path(child).stem + '*' for child in CHILDREN),
                f'prep -top {TOP} -flatten', 'memory_map', 'opt_clean',
                'write_json ' + shlex.quote(str(raw)),
            ]
            run(out, name + '_' + label + '_elaborate', commands)
            ports[label] = expand_ports(raw, expanded)
        if ports['reference'] != ports['current']:
            raise RuntimeError('Child port boundaries differ')
        optional_inputs = match_optional_inputs(out / (name + '_reference_expanded.json'),
                                               out / (name + '_current_expanded.json'))
        commands = []
        for label in ('reference', 'current'):
            path = out / (name + '_' + label + '_expanded.json')
            commands += ['read_json ' + shlex.quote(str(path)), f'prep -top {TOP}',
                         f'rename {TOP} {label}', f'design -stash {label}']
        commands += [
            'design -copy-from reference -as reference reference',
            'design -copy-from current -as current current',
            'expose -dff -shared reference current', 'async2sync', 'opt_clean',
            'rename -hide reference/w:* current/w:*',
            'equiv_make reference current comparison', 'hierarchy -top comparison',
            'equiv_simple -seq 1', 'opt_clean', 'equiv_induct -seq 2', 'equiv_status -assert',
        ]
        log = run(out, name, commands)
        text = log.read_text()
        match = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', text)
        passed = match is not None and int(match[2]) == 0 and 'Equivalence successfully proven' in text
        row = {
            'name': name, 'data_width': data, 'size': size, 'im2col_size': image_size,
            'bus_width': bus, 'window_lanes': lanes, 'cache_blocks': blocks,
            'passed': passed, 'equivalent_bits': int(match[1]) if match else None,
            'child_ports': ports['current'], 'optional_reference_inputs': optional_inputs,
            'log_sha256': digest(log),
        }
        report['profiles'].append(row)
        print(json.dumps({key: value for key, value in row.items() if key != 'child_ports'}), flush=True)
        if not passed:
            raise RuntimeError('DMA state comparison did not complete')
    if source_hashes != {name: digest(ROOT / name) for name in files}:
        raise RuntimeError('RTL sources changed during verification')
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
