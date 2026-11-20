#!/usr/bin/env python3
"""保留仿真原始文件，重新验证完整模型输出、窗口计数和 INT32 部分和。"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys


def read(path):
    return json.loads(path.read_text())


def require(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    repo, out = args.repo.resolve(), args.out.resolve()
    sys.path.insert(0, str(repo))
    sys.path.insert(0, str(repo / 'test/model_benchmark'))
    sys.path.insert(0, str(repo / 'test/ps_compression'))
    import report
    import run as bench
    from verify_storage_models import parse_log, verify_window_jobs

    spec = importlib.util.spec_from_file_location('recheck_ps_rows', repo / 'test/ps_compression/run_soc.py')
    ps_runner = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = ps_runner
    spec.loader.exec_module(ps_runner)
    settings_path = out / 'settings_hw_perf_trace.json'
    settings = read(settings_path)
    build = read(out / 'sim/build.json')
    binary = out / 'sim/obj/Vtb_model_benchmark'
    require(build['returncode'] == 0 and build['sources_unchanged_during_build'], '仿真器构建尚未通过')
    require(bench.digest(binary) == build['binary_sha256'], '仿真二进制与构建记录不一致')
    bench.verify_sources(build)
    lanes = build['profile'].get('window_lanes')
    require(type(lanes) is int and lanes > 0, '构建记录缺少有效窗口并行数')
    requested = settings['arguments']
    models = requested['models'] or list(settings['prepared_manifest_sha256'])
    expected = {(model, sample, kind, 63 if mode == 'hw' else 0)
                for model in models for sample in requested['samples']
                for kind in requested['kinds'] for mode in requested['modes']}
    paths = sorted((out / 'results/cases').glob('*/*/*/result.json'))
    saved = [read(path) for path in paths]
    require({(row['model_id'], row['sample_index'], row['kind'], row['mode']) for row in saved} == expected
            and len(saved) == len(expected), '完整模型运行数量与请求不一致')
    validation_sources = {str(path.relative_to(repo)): bench.digest(path) for path in (
        repo / 'test/model_benchmark/run.py', Path(__file__).resolve(),
        repo / 'test/gemmini_comparison/verify_storage_models.py')}
    ps_hash = bench.digest(repo / 'test/ps_compression/run_soc.py')
    records, raw_hashes = [], {}
    for result_path, old in zip(paths, saved):
        directory = result_path.parent
        raw_files = [path for path in directory.rglob('*') if path.is_file() and path.suffix != '.json']
        before = {str(path.relative_to(out)): bench.digest(path) for path in raw_files}
        case = read(directory / 'case.json')
        fw = read(Path(case['firmware_dir']) / 'firmware.json')
        bench.verify_sources(fw)
        simulator = read(directory / 'summary.json')
        require(simulator['simulator_sha256'] == build['binary_sha256'], '运行的仿真二进制不同')
        require(bench.digest(Path(case['firmware_dir']) / 'cpu.mem') == simulator['firmware_memory_sha256'] == fw['mem_sha256'],
                '运行固件内存映像不同')
        require(bench.digest(Path(case['firmware_dir']) / 'cpu.elf') == case['firmware_elf_sha256'] == fw['elf_sha256'],
                '运行固件 ELF 不同')
        for filename, field in (('result.bin', 'result_sha256'), ('output.bin', 'output_sha256'),
                                ('data.mem', 'data_memory_sha256')):
            require(bench.digest(directory / filename) == simulator[field], '原始运行文件不同：' + filename)
        require(bench.digest(directory / 'memory_axi64.mem') == simulator['packed_memory']['sha256'], '打包 RAM 映像不同')
        parsed = parse_log(directory / 'run.log')
        for key, value in parsed.items():
            require(simulator[key] == value, '日志计数与保存记录不同：' + key)
        network = [row for row in parsed['counters'] if row['scope'] == 'network']
        require(len(network) == 1, '需要一个完整网络计时间隔')
        verify_window_jobs(parsed['window_jobs'], network[0], build['profile'])
        result = bench.validate_case(directory, case, fw, simulator, latency=old['ram_fixed_lat'], window_lanes=lanes)
        if case['mode']:
            result = ps_runner.validate_result(result, 'raw', binary, ps_hash)
        for key in ('host_seconds', 'experiment_runner_sha256', 'source_commit', 'hardware_profile'):
            result[key] = old[key]
        result['validation_source_sha256'] = validation_sources
        require(result['passed'] and all(result['checks'].values()), '完整模型验证未通过：' + str(directory))
        require(before == {str(path.relative_to(out)): bench.digest(path) for path in raw_files}, '验证期间原始运行文件发生变化')
        bench.write_json(result_path, result)
        raw_hashes.update(before)
        records.append(result)
    settings['validation_source_sha256'] = validation_sources
    bench.write_json(settings_path, settings)
    summary = report.summarize(out, Path(requested['prepared']))
    label = '_'.join(requested['modes']) + '_' + '_'.join(requested['kinds'])
    progress = [{'model': row['model_id'], 'sample': row['sample_index'],
                 'kind': row['kind'], 'mode': row['mode_name'], 'passed': row['passed'],
                 'invoke_cycles': row['result']['invoke_cycles'],
                 'init_cycles': row['result']['init_cycles'], 'case_dir': row['case_dir']} for row in records]
    bench.write_json(out / f'progress_{label}.json', dict(completed_cases=len(records), cases=progress))
    outcome = dict(functional_passed=summary['functional_passed'],
                   complete_requested_suite=summary['functional_passed'] and len(records) == len(expected),
                   complete_software_hardware_suite=summary['complete'],
                   completed_requested_cases=len(records), expected_requested_cases=len(expected), models=summary['models'])
    bench.write_json(out / f'outcome_{label}.json', outcome)
    verification = dict(passed=True, checked_runs=len(records), window_lanes=lanes,
                        simulator_sha256=build['binary_sha256'], validation_source_sha256=validation_sources,
                        raw_artifacts_unchanged=True, raw_artifact_sha256=raw_hashes)
    bench.write_json(out / 'revalidation.json', verification)
    print(json.dumps({key: verification[key] for key in ('passed', 'checked_runs', 'window_lanes', 'raw_artifacts_unchanged')}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
