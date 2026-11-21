#!/usr/bin/env python3
"""核对后续读长度的同源完整模块证明、四态传播、实际读写和路径测量。"""
import argparse
import hashlib
import itertools
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = 'rtl/npu/dma/axi_linear_block_dma.sv'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def source_matches(hashes, expected):
    return [sha for name, sha in hashes.items() if name.endswith(SOURCE)] == [expected]


def checked_runs(runs):
    require(len(runs) == 2 and {row['random'] for row in runs} == {False, True},
            '固定等待与随机等待检查不完整')
    require(all(row['passed'] is True and row['returncode'] == 0 for row in runs),
            '实际读写检查未通过')
    return [dict(random=row['random'], passed=True, counters=row['counters']) for row in runs]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    for name in ('formal', 'arithmetic', 'read-root', 'write-root', 'measurement', 'out'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    sha = digest(args.source_root / SOURCE)
    formal, arithmetic, measurement = [read(path) for path in
        (args.formal, args.arithmetic, args.measurement)]
    reference_sha = formal['inputs']['reference']['sha256']
    require(formal['passed'] is True and formal['inputs']['current']['sha256'] == sha,
            '完整模块等价检查源码或状态不正确')
    expected = set(itertools.product((16, 64), (32, 64), (1, 4), (1, 4), (1, 4)))
    fields = ('size', 'bus_width', 'read_outstanding', 'write_outstanding', 'read_context_depth')
    require(len(formal['profiles']) == 32 and
            {tuple(row[key] for key in fields) for row in formal['profiles']} == expected and
            all(row['passed'] is True and row['equivalent_bits'] > 0 for row in formal['profiles']) and
            formal['input_assumptions'] == [], '完整模块证明配置不完整')
    require(arithmetic['passed'] is True and arithmetic['source_sha256'] ==
            dict(reference=reference_sha, current=sha), '算术与四态检查源码不一致')
    expected = set(itertools.product((1, 2, 3, 4), (1, 2, 4, 8, 16, 32, 64, 128, 256)))
    require(len(arithmetic['profiles']) == 36 and
            {(row['address_lsb'], row['maximum_burst_beats']) for row in arithmetic['profiles']} == expected and
            all(row['passed'] is True for row in arithmetic['profiles']) and
            arithmetic['input_constraints'] == [] and
            arithmetic['four_state_samples'] == 32768 and
            arithmetic['four_state_comparisons'] == 1179648, '算术与四态检查覆盖不完整')
    numeric = dict(read=[], write=[])
    report_files = [args.formal, args.arithmetic, args.measurement]
    for bus, outstanding in itertools.product((32, 64), (1, 4)):
        path = args.read_root / f'b{bus}_o{outstanding}' / 'summary.json'
        report_files.append(path)
        part = read(path)
        require(part['passed'] is True and part['bus_width'] == bus and
                part['outstanding'] == outstanding and part['sources_unchanged_during_build'] is True and
                source_matches(part['source_sha256'], sha), '读事务配置或源码不一致：' + str(path))
        for helper, helper_sha in formal['helper_sha256'].items():
            require([value for name, value in part['source_sha256'].items()
                     if name.endswith('rtl/common/' + helper)] == [helper_sha],
                    '读事务辅助模块源码不一致：' + helper)
        numeric['read'].append(dict(bus_width=bus, outstanding=outstanding,
            binary_sha256=part['binary_sha256'], runs=checked_runs(part['runs'])))
    for bus in (32, 64):
        path = args.write_root / f'b{bus}' / 'summary.json'
        report_files.append(path)
        part = read(path)
        require(part['passed'] is True and part['bus_width'] == bus and part['rtl_sha256'] == sha,
                '写事务配置或源码不一致：' + str(path))
        require(len(part['configurations']) == 2 and
                {row['outstanding'] for row in part['configurations']} == {1, 4},
                '写事务在途配置不完整')
        for row in part['configurations']:
            numeric['write'].append(dict(bus_width=bus, outstanding=row['outstanding'],
                runs=checked_runs(row['runs'])))
    for label, expected_sha in (('reference', reference_sha), ('current', sha)):
        part = measurement[label]
        require(source_matches(part['source_manifest']['sources_sha256'], expected_sha) and
                part['whole_dma_register_paths']['graph_complete'] is True,
                '完整模块测量源码或组合图覆盖不正确：' + label)
        for value in part['selected_register_paths'].values():
            require(value['graph_complete'] is True, '固定寄存器路径图覆盖不完整')
    current_paths = measurement['current']['selected_register_paths']
    require(current_paths['linear_state']['longest_register_path_cells'] <= 14 and
            current_paths['follow_length']['longest_register_path_cells'] <= 14,
            '线性 DMA 寄存器路径超过 14 级')
    totals = {direction: {field: sum(run['counters'][field] for row in rows for run in row['runs'])
                         for field in ('commands', 'bursts', 'beats', 'cycles')}
              for direction, rows in numeric.items()}
    result = dict(passed=True, source_sha256={SOURCE: sha}, reference_source_sha256=reference_sha,
        scope='线性 DMA 后续读长度的功能保持与固定寄存器路径',
        full_module_formal=formal, arithmetic_and_four_state=arithmetic,
        actual_transactions=numeric, transaction_totals=totals, measurement=measurement,
        input_reports_sha256={str(path): digest(path) for path in report_files},
        public_cycles_changed=False, physical_timing_confirmed=False,
        collector_sha256=digest(Path(__file__)))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(dict(passed=True, source_sha256=sha, transaction_totals=totals)))


if __name__ == '__main__':
    main()
