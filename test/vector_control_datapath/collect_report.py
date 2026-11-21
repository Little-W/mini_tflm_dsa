#!/usr/bin/env python3
"""核对组合证明、实际消费检查和完整数值回归使用的源码。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
ENGINE = 'rtl/npu/conv/vector_engine.sv'
HELPER = 'rtl/common/parallel_prefix_add.sv'
OBSERVER = 'test/monitors/vector_engine_observer.sv'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def compiled_digest(compiled, relative):
    matches = [sha for name, sha in compiled.items()
               if name == relative or Path(name).as_posix().endswith('/' + relative)]
    if len(matches) != 1:
        raise RuntimeError(f'编译输入应包含唯一的文件：{relative}')
    return matches[0]


def compiled_rtl(compiled):
    result = {}
    for name, sha in compiled.items():
        path = Path(name).as_posix()
        if path.startswith('rtl/'):
            relative = path
        elif '/rtl/' in path:
            relative = 'rtl/' + path.rsplit('/rtl/', 1)[1]
        else:
            continue
        if relative in result:
            raise RuntimeError(f'编译输入包含重复的 RTL 路径：{relative}')
        result[relative] = sha
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--control', type=Path, required=True)
    parser.add_argument('--dma', type=Path, required=True)
    parser.add_argument('--storage', type=Path, required=True)
    parser.add_argument('--quant', type=Path, required=True)
    parser.add_argument('--source-root', type=Path, default=ROOT,
                        help='与两组数值测试对应的固定 RTL 目录')
    parser.add_argument('--proof', action='append', default=[], metavar='NAME=SUMMARY',
                        help='加入当前引擎的其它证明摘要，并检查全部已记录源码')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    source_root = args.source_root.resolve()
    control = json.loads((args.control / 'summary.json').read_text())
    dma = json.loads((args.dma / 'summary.json').read_text())
    if not control['passed'] or not dma['passed']:
        raise RuntimeError('组合关系检查未全部通过')
    expected = control['source_sha256']
    if expected[ENGINE] != dma['source_sha256']:
        raise RuntimeError('两组证明使用的向量引擎不同')
    report = {'passed': True, 'control_combinational': control, 'dma_combinational': dma,
              'registered_consumers': {'method': 'Assertions on real engine state and data during complete numerical regression',
                                       'observer_sha256': digest(ROOT / OBSERVER)},
              'numerical_runs': [], 'source_root': str(source_root), 'additional_formal': {}}
    for item in args.proof:
        name, separator, summary_path = item.partition('=')
        if not separator or re.fullmatch(r'[A-Za-z][A-Za-z_0-9]*', name) is None:
            raise RuntimeError('附加证明格式应为 NAME=SUMMARY')
        if name in report['additional_formal']:
            raise RuntimeError(f'附加证明名称重复：{name}')
        path = Path(summary_path).resolve()
        proof = json.loads(path.read_text())
        if not proof['passed']:
            raise RuntimeError(f'附加证明未通过：{name}')
        hashes = proof['source_sha256']
        hashes = {ENGINE: hashes} if isinstance(hashes, str) else dict(hashes)
        hashes.update(proof.get('dependency_sha256', {}))
        if hashes.get(ENGINE) != expected[ENGINE]:
            raise RuntimeError(f'附加证明的引擎源码不同：{name}')
        for relative, sha in hashes.items():
            if digest(source_root / relative) != sha:
                raise RuntimeError(f'附加证明与固定源码不同：{name} {relative}')
        report['additional_formal'][name] = {'summary': str(path), 'result': proof}
    shared_rtl = None
    for folder, pe, mode in [(args.storage, 8, 'shared_storage'), (args.quant, 16, 'shared_quant')]:
        summary = json.loads((folder / 'summary.json').read_text())
        build = json.loads((folder / f'pe{pe}' / 'build.json').read_text())
        if len(summary['runs']) != 1:
            raise RuntimeError(f'数值结果应包含指定的单个 PE 配置：{folder}')
        row = summary['runs'][0]
        if (not row['passed'] or row['pe'] != pe or not summary[mode] or
                summary['tile'] != 16 or summary['bus_width'] != 64 or summary['window_lanes'] != 8 or
                summary['implementation'] != 'official Xilinx primitive models'):
            raise RuntimeError(f'数值配置或运行结果不符：{folder}')
        binary = folder / f'pe{pe}/obj/Vvector_engine_dma_top'
        if digest(binary) != row['executable_sha256']:
            raise RuntimeError(f'仿真程序与已记录结果不同：{folder}')
        compiled = build['sha256']
        rtl = compiled_rtl(compiled)
        if shared_rtl is None:
            shared_rtl = rtl
        elif rtl != shared_rtl:
            raise RuntimeError('两组数值回归使用的 RTL 文件集合或内容不同')
        for relative, sha in {**expected, **dma['dependency_sha256'],
                              OBSERVER: report['registered_consumers']['observer_sha256']}.items():
            if compiled_digest(compiled, relative) != sha:
                raise RuntimeError(f'编译输入与证明输入不同：{folder} {relative}')
        log = (folder / f'pe{pe}' / 'functional.log').read_text()
        matches = re.findall(r'^VECTOR_CONTROL_DATAPATH_PASS (.+)$', log, re.M)
        if len(matches) != 1:
            raise RuntimeError(f'消费周期检查摘要缺失或不唯一：{folder}')
        coverage = {name: int(value) for name, value in re.findall(r'(\w+)=(\d+)', matches[0])}
        if set(coverage) != {'parameter_cycles', 'lut_cycles', 'commit_cycles', 'reduce_cycles'} or not all(coverage.values()):
            raise RuntimeError(f'消费周期检查未覆盖所有目标：{folder}')
        parameter_rows = re.findall(r'^VECTOR_PARAMETER_ROWS_CHECK (.+)$', log, re.M)
        row_coverage = {name: int(value) for name, value in re.findall(r'(\w+)=(\d+)', parameter_rows[0])} if len(parameter_rows) == 1 else {}
        totals = row['totals']
        if any(totals[name] == 0 for name in ('cases', 'outputs', 'add_cases', 'add_outputs',
                                             'softmax_cases', 'softmax_outputs')):
            raise RuntimeError(f'通用、Add 或 Softmax 场景未完整执行：{folder}')
        for name, minimum in [('cases', 615), ('add_cases', 143), ('softmax_cases', 273)]:
            if totals[name] < minimum:
                raise RuntimeError(f'数值回归未完成指定场景集合：{folder} {name}')
        pipeline = [case for case in row['cases'] if case['name'] == 'pipeline_dw_c16']
        if len(pipeline) != 1 or pipeline[0]['window_request_response_overlap'] == 0:
            raise RuntimeError(f'c16 场景未覆盖请求和响应同时传输：{folder}')
        report['numerical_runs'].append({
            'pe': pe, 'mode': mode, 'bus_width': summary['bus_width'],
            'window_lanes': summary['window_lanes'], 'passed': True,
            'totals': totals, 'all_outputs': totals['outputs'] + totals['add_outputs'] + totals['softmax_outputs'],
            'consumer_coverage': coverage, 'parameter_row_commands': row_coverage,
            'source_sha256': compiled, 'executable_sha256': row['executable_sha256'],
            'summary': str((folder / 'summary.json').resolve()),
        })
    if any(digest(source_root / relative) != sha for relative, sha in expected.items()):
        raise RuntimeError('固定向量引擎或公共加法模块与受测文件不同')
    if any(digest(source_root / relative) != sha for relative, sha in shared_rtl.items()):
        raise RuntimeError('数值测试包含与固定源码不同的 RTL 文件')
    manifest = source_root / 'source_manifest.json'
    if manifest.is_file():
        report['source_manifest_sha256'] = digest(manifest)
    report['all_outputs'] = sum(row['all_outputs'] for row in report['numerical_runs'])
    report['shared_rtl_sha256'] = shared_rtl
    report['all_cases'] = sum(sum(row['totals'][name] for name in ('cases', 'add_cases', 'softmax_cases'))
                              for row in report['numerical_runs'])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + '\n')
    print(args.out)


if __name__ == '__main__':
    main()
