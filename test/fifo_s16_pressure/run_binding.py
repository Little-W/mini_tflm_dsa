#!/usr/bin/env python3
"""核对实际矩阵引擎的容量反馈连接，并展开普通及八位专用配置。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def tokens(text):
    return re.sub(r'\s+', '', re.sub(r'/\*.*?\*/|//[^\n]*', '', text, flags=re.S))


def instance(text, module):
    match = re.search(r'^\s*'+re.escape(module)+r'\s+#\(', text, re.M)
    if match is None:
        raise ValueError('缺少模块实例：'+module)
    start = match.start()
    return text[start:text.index(';', start)+1]


def connections(text, name):
    start = re.search(r'\b'+re.escape(name)+r'\s*\(', text).end()
    body = text[start:]
    result = {}
    for match in re.finditer(r'\.(\w+)\s*\(', body):
        last = match.end()
        depth = 1
        while depth:
            depth += (body[last] == '(') - (body[last] == ')')
            last += 1
        result[match[1]] = tokens(body[match.end():last-1])
    return result


def remove_once(text, expression):
    result, count = re.subn(expression, '', text, flags=re.M)
    if count != 1:
        raise ValueError('需要唯一的连接或声明：'+expression)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference', default='4927debf')
    parser.add_argument('--verilator', default='verilator')
    args = parser.parse_args()
    source = args.source_root.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    revision = subprocess.check_output(['git', 'rev-parse', args.reference+'^{commit}'],
                                       cwd=source, text=True).strip()
    names = ('rtl/npu/top/npu_matrix_engine.sv', 'rtl/npu/top/npu_output_pipeline.sv')
    current = {name: (source/name).read_text() for name in names}
    reference = {name: subprocess.check_output(['git', 'show', revision+':'+name],
                 cwd=source, text=True) for name in names}

    matrix = current[names[0]]
    old_controller = connections(instance(reference[names[0]], 'npu_controller'), 'u_npu_controller')
    new_controller = connections(instance(matrix, 'npu_controller'), 'u_npu_controller')
    if new_controller.pop('fifo_full_flag') != 'fifo_issue_full_flag':
        raise ValueError('控制器容量输入未连接到完整发送资格')
    if old_controller.pop('fifo_full_flag') != 'fifo_full_flag&&ia_output_pending':
        raise ValueError('参考控制器容量表达式与证明关系不一致')
    if old_controller != new_controller:
        raise ValueError('控制器其他输入输出连接发生变化')
    old_output = connections(instance(reference[names[0]], 'npu_output_pipeline'), 'u_output_pipeline')
    new_output = connections(instance(matrix, 'npu_output_pipeline'), 'u_output_pipeline')
    if new_output.pop('i_output_pending') != 'ia_output_pending' or \
            new_output.pop('o_fifo_issue_full_flag') != 'fifo_issue_full_flag' or new_output != old_output:
        raise ValueError('输出处理容量端口连接不完整')
    matrix = remove_once(matrix, r'^\s*logic fifo_issue_full_flag;[^\n]*\n')
    matrix = remove_once(matrix, r'^\s*\.i_output_pending\(ia_output_pending\),[^\n]*\n')
    matrix = remove_once(matrix, r'^\s*\.o_fifo_issue_full_flag\(fifo_issue_full_flag\),[^\n]*\n')
    matrix = matrix.replace('(fifo_issue_full_flag)', '(fifo_full_flag && ia_output_pending)')
    if tokens(matrix) != tokens(reference[names[0]]):
        raise ValueError('矩阵引擎的其余功能表达式发生变化')

    output = current[names[1]]
    old_fifo = instance(reference[names[1]], 'vec_s16_to_fifo')
    new_fifo = instance(output, 'vec_s16_to_fifo')
    old_ports = connections(old_fifo, 'u_vec_s16_to_fifo')
    new_ports = connections(new_fifo, 'u_vec_s16_to_fifo')
    expected = dict(i_full_select='i_run_16x8', i_output_pending='i_output_pending',
                    i_other_full='fifo_s8_full_flag', o_issue_full='o_fifo_issue_full_flag')
    for port, expression in expected.items():
        if new_ports.pop(port) != expression:
            raise ValueError('十六位容量选择端口不符合公开证明关系：'+port)
    if old_ports != new_ports:
        raise ValueError('十六位 FIFO 其余输入输出连接发生变化')
    output = output.replace(new_fifo, old_fifo, 1)
    output = remove_once(output, r'^\s*input wire logic i_output_pending = 1\'b1,[^\n]*\n')
    output = remove_once(output, r'^\s*output logic o_fifo_issue_full_flag,[^\n]*\n')
    output = remove_once(output, r'^\s*assign o_fifo_issue_full_flag = o_fifo_full_flag && i_output_pending;[^\n]*\n')
    if tokens(output) != tokens(reference[names[1]]):
        raise ValueError('输出流水线的其余功能表达式发生变化')

    resolve = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    sources = resolve([source/names[0]], source)
    hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in [*sources, Path(__file__)]}
    profiles = []
    for label, options in (('bus32', ['-Gp_bus_width=32']),
                           ('bus64', ['-Gp_bus_width=64']),
                           ('int8_bus64', ['-Gp_bus_width=64', '-DGEMMORA_INT8_PROFILE=1'])):
        command = [args.verilator, '--lint-only', '--timing', '-Wno-fatal',
                   '--top-module', 'npu_matrix_engine', '-I'+str(source/'include'),
                   '-DGEMMORA_PS_POOL_BYTES=12288',
                   *options, *map(str, sources)]
        with (out/(label+'.log')).open('w') as log:
            result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
        if result.returncode != 0:
            raise RuntimeError('实际矩阵引擎展开失败：'+label)
        profiles.append(dict(profile=label, passed=True, command=command))
    unchanged = all(hashlib.sha256(Path(path).read_bytes()).hexdigest() == value
                    for path, value in hashes.items())
    if not unchanged:
        raise RuntimeError('展开期间输入源码发生变化')
    report = dict(passed=True, reference_commit=revision, source_sha256=hashes,
                  parent_functional_tokens_unchanged=True, capacity_connections_verified=True,
                  full_expression='(i_run_16x8 ? fifo_s16_full_flag : fifo_s8_full_flag) && ia_output_pending',
                  int8_expression='o_fifo_full_flag && i_output_pending', profiles=profiles)
    (out/'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print('FIFO_S16_PARENT_BINDING_PASS profiles=3')


if __name__ == '__main__':
    main()
