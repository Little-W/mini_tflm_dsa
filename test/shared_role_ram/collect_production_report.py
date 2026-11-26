#!/usr/bin/env python3
"""核验完整生产测试的结果、程序摘要和消费者活动，并保存共享存储验证报告。"""
import argparse
import hashlib
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', type=Path, required=True)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    results = args.results.resolve()
    source_root = args.source_root.resolve()
    manifest_path = results / 'npu/s16/build.json'
    manifest = json.loads(manifest_path.read_text())
    binary = results / 'npu/s16/obj/Vtb_conv_npu'
    binary_hash = digest(binary)
    assert manifest['returncode'] == 0
    assert manifest['binary_sha256'] == binary_hash
    assert manifest['sources_unchanged_during_build']
    assert '--assert' in manifest['command']
    assert Path(manifest['source_root']).resolve() == source_root
    for relative, expected in manifest['source_sha256'].items():
        if relative.startswith(('rtl/', 'include/')):
            assert digest(source_root / relative) == expected, relative

    reports = {}
    all_cases = []
    for label, directory in (('functional', 'npu'), ('capacity', 'capacity'),
                             ('output', 'output'), ('packed', 'packed')):
        path = results / directory / 'summary.json'
        packed_in_combined_report = label == 'packed' and not path.is_file()
        if packed_in_combined_report:
            path = results / 'summary.json'
        data = json.loads(path.read_text())
        if packed_in_combined_report:
            data = data['results']['packed']
        assert data['passed'], label
        cases = data['cases'] if label == 'functional' else [
            data if label == 'packed' else data['suite']]
        for case in cases:
            assert case['passed'] and case['returncode'] == 0
            assert case['binary_sha256'] == binary_hash
            assert len(case['tasks']) == len(case['measurements'])
        tasks = sum(len(case['measurements']) for case in cases)
        checks = sum(measurement['int32_checks'] for case in cases
                     for measurement in case['measurements'])
        reports[label] = dict(passed=True, tasks=tasks, int32_checks=checks,
                             report_sha256=digest(path),
                             cases=[dict(name=case['name'], tasks=len(case['tasks']),
                                         log_sha256=case['log_sha256']) for case in cases])
        all_cases.extend(cases)

    activity, frames = [], []
    for path in sorted(results.rglob('*.log')):
        for line in path.read_text(errors='replace').splitlines():
            for prefix, records in (('SHARED_ROLE_CONSUMER_PASS ', activity),
                                    ('FRAME_ADDRESS_NPU_PASS ', frames)):
                if line.startswith(prefix):
                    records.append(dict(log=str(path.relative_to(results)),
                                        log_sha256=digest(path),
                                        **{key: int(value) for key, value in
                                           re.findall(r'(\w+)=(\d+)', line)}))
    assert len(activity) == len(all_cases)
    assert len(frames) == len(all_cases)
    assert sum(row['ia'] for row in activity) > 0
    assert sum(row['ps'] for row in activity) > 0
    assert sum(row['ws_frames'] for row in frames) > 0
    assert sum(row['is_frames'] for row in frames) > 0
    assert sum(row['packed_frames'] for row in frames) > 0
    selected = ('rtl/npu/buffers/ia_ps_channel_ram.sv',
                'rtl/npu/buffers/ia_ps_role_ram.sv', 'rtl/npu/top/npu_top.sv')
    report = dict(
        passed=True,
        tasks=sum(row['tasks'] for row in reports.values()),
        int32_checks=sum(row['int32_checks'] for row in reports.values()),
        hardware_parameters={name: manifest[name] for name in (
            'size', 'bus_width', 'shared_bank_bytes', 'shared_bank_count',
            'address_width', 'vector_pe_count', 'ps_storage_rows',
            'oa_s16_fifo_banks_max', 'ps_frame_count', 'ia_compact_enable')},
        source_sha256={name: digest(source_root / name) for name in selected},
        build_manifest_sha256=digest(manifest_path), binary_sha256=binary_hash,
        consumer_observer_sha256=digest(Path(__file__).with_name('consumer_observer.sv')),
        cases=reports, shared_role_consumers=activity, frame_address_activity=frames,
        test_sha256=digest(Path(__file__)))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({key: report[key] for key in ('passed', 'tasks', 'int32_checks')}))


if __name__ == '__main__':
    main()
