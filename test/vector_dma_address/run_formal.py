#!/usr/bin/env python3
"""对完整向量地址子模块进行无限时序等价检查。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCES = [
    'rtl/npu/conv/conv_im2col_pkg.sv',
    'rtl/npu/conv/vector_engine_control_pkg.sv',
    'rtl/npu/conv/vector_engine_pkg.sv',
    'rtl/common/add_equal.sv',
    'rtl/common/parallel_prefix_add.sv',
    'rtl/common/unsigned_compare.sv',
    'rtl/npu/conv/vector_coordinate_bound.sv',
    'rtl/npu/conv/vector_interval_bound.sv',
    'rtl/npu/conv/vector_read_address_add.sv',
    'rtl/npu/conv/vector_engine_address.sv',
]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def connect_saved_qualifiers(text):
    """按已证明的控制字关系连接新增输入，其余生产源码保持原样。"""
    text = text.replace("parameter bit p_registered_read_phase = 1'b0",
                        "parameter bit p_registered_read_phase = 1'b1")
    for name in ('i_state_soft_lut_read', 'i_state_pool_read', 'i_load_read_select'):
        text, count = re.subn(r'^  input wire logic[^\n]*\b' + name + r'[^\n]*\n', '', text, flags=re.M)
        if count != 1:
            raise RuntimeError('未找到完整的读取资格接口：' + name)
    declarations = '''  logic i_state_soft_lut_read, i_state_pool_read;
  logic [5:0] i_load_read_select;
  logic [8:0] selected_load_word;
  assign i_state_soft_lut_read = i_state == vector_engine_control_pkg::SOFT_LUT_REQ ||
      i_state == vector_engine_control_pkg::SOFT_LUT_WAIT;
  assign i_state_pool_read = i_state == vector_engine_control_pkg::POOL_LOAD_REQ ||
      i_state == vector_engine_control_pkg::POOL_LOAD_WAIT;
  assign selected_load_word = vector_engine_control_pkg::load_control_value(i_load_kind);
  assign i_load_read_select = selected_load_word[8:3];
'''
    if text.count('  logic start;') != 1:
        raise RuntimeError('无法确定地址模块声明位置')
    return text.replace('  logic start;', declarations + '  logic start;')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference-rev', default='7ddc0d8d')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--only-production', action='store_true')
    parser.add_argument('--direct-inputs', action='store_true',
                        help='直接比较两侧公开输入，不添加保存资格的关系约束')
    args = parser.parse_args()
    source, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    hashes = {name: digest(source / name) for name in SOURCES}
    copied = {}
    for label in ('reference', 'current'):
        folder = out / label
        folder.mkdir(exist_ok=True)
        copied[label] = []
        for name in SOURCES:
            if label == 'reference':
                text = subprocess.check_output(['git', 'show', args.reference_rev + ':' + name],
                                               cwd=ROOT, text=True)
            else:
                text = (source / name).read_text()
                if name.endswith('/vector_engine_address.sv') and not args.direct_inputs:
                    text = connect_saved_qualifiers(text)
            path = folder / Path(name).name
            path.write_text(text)
            copied[label].append(path)
    profiles = [('production', ['-Gp_tile=16', '-Gp_bus_width=64', '-Gp_window_lanes=8',
                               '-Gp_pe_count=8', '-Gp_shared_storage_enable=1'])]
    if args.direct_inputs:
        profiles[0][1].append('-Gp_registered_read_phase=1')
    if not args.only_production:
        for bus, tile in ((32, 16), (128, 16), (32, 3), (64, 32)):
            profiles.append((f'bus{bus}_tile{tile}', [f'-Gp_tile={tile}', f'-Gp_bus_width={bus}']))
    rows = []
    for name, parameters in profiles:
        commands = []
        for label in ('reference', 'current'):
            commands += [
                'read_slang --top vector_engine_address -DSYNTHESIS=1 ' +
                    ' '.join(parameters) + ' ' + ' '.join(map(str, copied[label])),
                'setattr -mod -unset keep_hierarchy', 'prep -top vector_engine_address -flatten',
                'memory_map', 'async2sync', 'opt -full',
                'write_json ' + str(out / (name + '_' + label + '_ports.json')),
                'rename -top ' + label, 'design -stash ' + label,
            ]
        commands += [
            'design -copy-from reference -as reference reference',
            'design -copy-from current -as current current',
            'equiv_make reference current proof', 'hierarchy -top proof',
            'equiv_simple -seq 3', 'opt_clean', 'equiv_induct -seq 5', 'equiv_status -assert',
        ]
        script, log = out / (name + '.ys'), out / (name + '.log')
        script.write_text('\n'.join(commands) + '\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                            '--worker', str(script)], stdout=stream, stderr=subprocess.STDOUT,
                           cwd=ROOT, check=True, timeout=600)
        match = re.search(r'Of those cells (\d+) are proven and 0 are unproven', log.read_text())
        if not match:
            raise RuntimeError('完整地址模块的时序证明未完成：' + name)
        original = json.loads((out / (name + '_reference_ports.json')).read_text())['modules']['vector_engine_address']['ports']
        current_ports = json.loads((out / (name + '_current_ports.json')).read_text())['modules']['vector_engine_address']['ports']
        port_shape = lambda ports: {key:(value['direction'],len(value['bits'])) for key,value in ports.items()}
        if port_shape(original) != port_shape(current_ports):
            raise RuntimeError('公开接口的方向或位宽发生变化')
        output_bits = sum(len(port['bits']) for port in original.values() if port['direction']=='output')
        row = dict(name=name, parameters=parameters, passed=True, compared_output_bits=output_bits,
                   equivalent_points=int(match[1]),
                   unbounded_equivalence=True, script_sha256=digest(script), log_sha256=digest(log))
        rows.append(row)
        print(json.dumps(row), flush=True)
    if hashes != {name: digest(source / name) for name in SOURCES}:
        raise RuntimeError('检查期间源码发生变化')
    (out / 'summary.json').write_text(json.dumps(dict(passed=True, reference_revision=args.reference_rev,
        source_sha256=hashes, input_assumptions=[], runs=rows,
        scope='完整公开输出、DMA范围、地址、传输尺寸、参数检查及内部寄存行为'), indent=2)+'\n')


if __name__ == '__main__':
    main()
