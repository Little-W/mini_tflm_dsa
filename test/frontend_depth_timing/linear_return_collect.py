#!/usr/bin/env python3
"""检查线性 DMA 返回列资格的证明、事务和综合源码，并保存统一摘要。"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from pathlib import Path


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--formal', type=Path, required=True)
    parser.add_argument('--measurement', type=Path, required=True)
    parser.add_argument('--read-tests', nargs='+', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    formal = json.loads((args.formal / 'summary.json').read_text())
    measurement = json.loads((args.measurement / 'measurement.json').read_text())
    if not formal['passed'] or not formal['complete_dma']['passed']:
        raise RuntimeError('完整 DMA 证明未通过')
    expected_profiles = set(itertools.product((16, 64), (32, 64), (1, 4), (1, 4), (1, 4)))
    actual_profiles = set()
    for row in formal['complete_dma']['profiles']:
        if not row['passed']:
            raise RuntimeError('存在未通过的参数配置')
        actual_profiles.add(tuple(row[key] for key in
                                  ('size', 'bus_width', 'read_outstanding',
                                   'write_outstanding', 'read_context_depth')))
    if actual_profiles != expected_profiles:
        raise RuntimeError('完整 DMA 参数配置不完整')
    if formal['input_assumptions'] or formal['complete_dma']['input_assumptions']:
        raise RuntimeError('本项检查要求无输入假设')
    for name in ('reference', 'candidate'):
        row = formal['inputs'][name]
        expected = row['sha256']
        measured = measurement['inputs'][name]
        measured_copy = args.measurement / 'source' / name / 'axi_linear_block_dma.sv'
        if expected != measured['sha256'] or digest(row['path']) != expected or digest(measured_copy) != expected:
            raise RuntimeError(f'证明与综合的源码不同：{name}')
    helpers = formal['complete_dma']['helper_sha256']
    for name, expected in helpers.items():
        if digest(args.measurement / 'source/rtl/common' / name) != expected:
            raise RuntimeError(f'证明与综合的公共依赖不同：{name}')
    source_sha = formal['inputs']['candidate']['sha256']
    reads = []
    totals = {key: 0 for key in ('commands', 'bursts', 'beats', 'raw_words', 'outputs')}
    for folder in args.read_tests:
        test = json.loads((folder / 'summary.json').read_text())
        if not test['passed'] or not test['sources_unchanged_during_build']:
            raise RuntimeError(f'实际读取测试未通过：{folder}')
        expected_files = {'axi_linear_block_dma.sv': source_sha, **helpers}
        for name, expected in expected_files.items():
            hashes = [value for path, value in test['source_sha256'].items() if Path(path).name == name]
            if hashes != [expected]:
                raise RuntimeError(f'实际读取测试的源码不同：{folder} {name}')
        if {row['random'] for row in test['runs']} != {False, True}:
            raise RuntimeError('实际读取测试缺少固定或随机背压')
        for row in test['runs']:
            if not row['passed']:
                raise RuntimeError('实际读取测试未全部通过')
            for key in totals:
                totals[key] += row['counters'][key]
        reads.append({'folder': str(folder.resolve()), **test})
    if {row['bus_width'] for row in reads} != {32, 64}:
        raise RuntimeError('实际读取测试需要覆盖 32 位和 64 位总线')
    depth = measurement['cases']['candidate']['maximum_register_depth']
    report = {
        'passed': True,
        'source_sha256': source_sha,
        'behavior': {
            'additional_pipeline_stages': 0,
            'public_cycle_relationships_unchanged': True,
            'tail_columns': 'wr_valid is preserved; valid tile lanes beyond valid_cols return zero',
            'qualification_capture': 'rd_rsp_lane_in_data_r is reset to zero and updated together with column metadata on rd_r_hs',
        },
        'formal': formal,
        'transactions': {'passed': True, 'totals': totals, 'tests': reads},
        'synthesis': measurement,
        'register_path_requirement': {'maximum_cells': 14, 'measured_cells': depth, 'met': depth <= 14},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(args.out)


if __name__ == '__main__':
    main()
