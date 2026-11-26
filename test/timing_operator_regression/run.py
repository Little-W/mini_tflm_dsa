#!/usr/bin/env python3
"""在固定硬件与AXI条件下验证62个算子，并比较修改前后的周期数。"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
COLLECTIONS = (('common36', 'workloads', 36), ('numeric26', 'numeric', 26))
SEEDS = {'common36': 20261116, 'numeric26': 20261123}
PREPARATION_FIELDS = frozenset(('conv_register_descriptor', 'conv_register_row_address'))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prepare_inputs(repo, destination):
    directory = repo / 'test/gemmini_comparison'
    sys.path.insert(0, str(directory))
    gemm = load('timing_gemm_inputs', directory / 'prepare.py')
    conv = load('timing_conv_inputs', directory / 'prepare_conv.py')
    numeric = load('timing_numeric_inputs', directory / 'prepare_regression_operators.py')
    reference = read(directory / 'public_operator_reference_20261123.json')
    for kind in ('gemm', 'conv'):
        target = destination / 'workloads' / kind
        target.mkdir(parents=True, exist_ok=True)
        rows = []
        for item in reference['cases']:
            if (item['kind'] == 'gemm') != (kind == 'gemm'):
                continue
            if kind == 'gemm':
                shape = item['shape']
                row = gemm.case(target, item['name'], shape['m'], shape['n'], shape['k'],
                                {'kind': 'common_operator_regression'}, SEEDS['common36'])
            else:
                shape = item['spatial']
                operation = 'depthwise' if item['kind'] in ('dw', 'depthwise') else 'conv2d'
                row = conv.create_case(target, item['name'], operation, shape['input_h'],
                    shape['input_w'], shape['input_channels'], shape['output_channels'],
                    shape['stride'], shape['padding'], SEEDS['common36'])
            for name, expected in item['input_tensor_sha256'].items():
                if row['tensors'][name]['sha256'] != expected:
                    raise ValueError('共同张量摘要不同: ' + item['name'] + '/' + name)
            rows.append(row)
        numeric.write_catalogue(target, rows)
    subprocess.run([sys.executable, str(directory / 'prepare_regression_operators.py'),
                    '--out', str(destination / 'numeric'), '--seed', str(SEEDS['numeric26'])],
                   check=True)
    memory = destination / 'scripts/memory_service'
    memory.mkdir(parents=True, exist_ok=True)
    source = repo / 'test/conv_npu/axi_memory.sv'
    shutil.copyfile(source, memory / 'axi_memory.sv')
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip()
    write(memory / 'source_manifest.json', {
        'source_commit': commit, 'source_path': 'test/conv_npu/axi_memory.sv',
        'source_sha256': {'axi_memory.sv': digest(source)}})


def verify_inputs(repo, inputs):
    reference_path = repo / 'test/gemmini_comparison/public_operator_reference_20261123.json'
    expected = {row['name']: row for row in read(reference_path)['cases']}
    case_records = []
    for collection, folder, count in COLLECTIONS:
        names = set()
        for kind in ('gemm', 'conv'):
            directory = inputs / folder / kind
            catalogue = read(directory / 'workloads.json')
            for entry in catalogue['cases']:
                name = entry['name']
                if name in names:
                    raise ValueError('重复测试名称: ' + name)
                names.add(name)
                manifest = directory / entry['manifest']
                if digest(manifest) != entry['manifest_sha256']:
                    raise ValueError('输入描述文件摘要不同: ' + name)
                row = read(manifest)
                tensors = {}
                for tensor_name, tensor in row['tensors'].items():
                    actual = digest(manifest.parent / tensor['path'])
                    if actual != tensor['sha256']:
                        raise ValueError('输入张量摘要不同: ' + name + '/' + tensor_name)
                    tensors[tensor_name] = actual
                if collection == 'common36':
                    if name not in expected or tensors != expected[name]['input_tensor_sha256']:
                        raise ValueError('共同张量与公开参考表不同: ' + name)
                case_records.append(dict(collection=collection, name=name,
                    manifest_sha256=digest(manifest), tensor_sha256=tensors))
        if len(names) != count:
            raise ValueError(f'{collection}需要{count}项，实际为{len(names)}项')
        if collection == 'common36' and names != set(expected):
            raise ValueError('共同算子集合不同')
    memory = inputs / 'scripts/memory_service'
    memory_manifest = read(memory / 'source_manifest.json')
    if digest(memory / 'axi_memory.sv') != memory_manifest['source_sha256']['axi_memory.sv']:
        raise ValueError('AXI存储模型摘要不同')
    record = {'schema_version': 1, 'case_count': len(case_records), 'seeds': SEEDS,
              'reference_table_sha256': digest(reference_path),
              'memory_source': memory_manifest, 'cases': case_records}
    manifest = inputs / 'input_manifest.json'
    if manifest.exists() and read(manifest) != record:
        raise ValueError('输入集合与保存的描述文件不同')
    write(manifest, record)
    return record


def save_collection(out, name, count):
    summary = read(out / 'summary.json')
    if not summary['passed'] or summary['case_count'] != count:
        raise ValueError('算子集合未完成: ' + name)
    target = out / 'collections' / name
    target.mkdir(parents=True, exist_ok=True)
    for filename in ('summary.json', 'prepared.json', 'hardware_profile.json'):
        shutil.copyfile(out / filename, target / filename)
    for kind in ('gemm', 'conv'):
        shutil.copyfile(out / kind / 'summary.json', target / (kind + '.json'))


def collect(out, inputs):
    rows = []
    profiles, binaries, commits = [], set(), set()
    for collection, _folder, count in COLLECTIONS:
        collection_rows = []
        for kind in ('gemm', 'conv'):
            group = read(out / 'collections' / collection / (kind + '.json'))
            if not group['passed']:
                raise ValueError('数值检查未通过: ' + collection + '/' + kind)
            profiles.append(group['profile'])
            binaries.add(group['binary_sha256'])
            commits.add(group['source_commit'])
            for row in group['cases']:
                if not row['passed'] or row['returncode'] != 0:
                    raise ValueError('算子检查未通过: ' + row['name'])
                actual = digest(row['observed_output_file'])
                if actual != row['output_sha256'] or actual != row['observed_output_sha256']:
                    raise ValueError('实际输出摘要不同: ' + row['name'])
                if row['measurement']['cycles'] != row['timing']['done']:
                    raise ValueError('算子完成周期不同: ' + row['name'])
                collection_rows.append(dict(collection=collection, kind=row['operator_kind'],
                    name=row['name'], cycles=row['measurement']['cycles'],
                    output_sha256=actual, passed=True, timing=row['timing']))
        if len(collection_rows) != count:
            raise ValueError('算子集合数量不同: ' + collection)
        rows.extend(collection_rows)
    build = read(out / 'sim/build.json')
    if len(binaries) != 1 or binaries != {build['binary_sha256']} or len(commits) != 1:
        raise ValueError('不同集合使用了不同的编译结果')
    if not build['sources_unchanged_during_build'] or build['returncode'] != 0:
        raise ValueError('编译输入检查未通过')
    if any(profile != profiles[0] for profile in profiles):
        raise ValueError('不同集合的硬件配置不同')
    result = {'passed': True, 'case_count': len(rows), 'source_commit': next(iter(commits)),
              'profile': profiles[0], 'binary_sha256': build['binary_sha256'],
              'input_manifest_sha256': digest(inputs / 'input_manifest.json'),
              'input_manifest': read(inputs / 'input_manifest.json'),
              'source_sha256': build['source_sha256'], 'cases': rows,
              'total_cycles': sum(row['cycles'] for row in rows)}
    write(out / 'all_cases.json', result)
    return result


def compare(reference, current, *, allow_preparation_stage_change=False,
            allow_cache_response_depth_change=False):
    """默认要求配置相同且周期不增加；指定流水参数实验单独报告周期变化。"""
    old = {row['name']: row for row in reference['cases']}
    new = {row['name']: row for row in current['cases']}
    checks = {'both_completed': reference['passed'] and current['passed'],
              'same_cases': set(old) == set(new) and len(old) ==
                            len(reference['cases']) == len(current['cases']) == 62,
              'same_hardware_profile': reference['profile'] == current['profile'],
              'same_inputs': reference['input_manifest_sha256'] == current['input_manifest_sha256']}
    rows = []
    for name in sorted(old.keys() & new.keys()):
        a, b = old[name], new[name]
        rows.append(dict(name=name, collection=b['collection'], kind=b['kind'],
            reference_cycles=a['cycles'], current_cycles=b['cycles'],
            cycle_difference=b['cycles'] - a['cycles'],
            equal_output=a['output_sha256'] == b['output_sha256'],
            no_cycle_regression=b['cycles'] <= a['cycles']))
    checks['all_outputs_equal'] = all(row['equal_output'] for row in rows)
    checks['all_cycles_not_increased'] = all(row['no_cycle_regression'] for row in rows)
    required = list(checks)
    comparison_parameters = set()
    if allow_preparation_stage_change:
        comparison_parameters.update(PREPARATION_FIELDS)
    if allow_cache_response_depth_change:
        comparison_parameters.add('conv_cache_demand_outstanding')
    if comparison_parameters:
        # 仅忽略明确选择的流水参数，其余存储容量、并行度及仿真条件仍逐项相同。
        profiles = [{key: value for key, value in item['profile'].items()
                     if key not in comparison_parameters} for item in (reference, current)]
        checks['hardware_changes_limited_to_selected_pipeline_parameters'] = profiles[0] == profiles[1]
        required.remove('same_hardware_profile')
        required.remove('all_cycles_not_increased')
        required.append('hardware_changes_limited_to_selected_pipeline_parameters')
    if allow_preparation_stage_change:
        checks['preparation_parameters_are_boolean'] = (
            all(current['profile'].get(key) in (0, 1) for key in PREPARATION_FIELDS)
            and all(value in (0, 1) for item in (reference, current)
                    for key, value in item['profile'].items() if key in PREPARATION_FIELDS))
        required.append('preparation_parameters_are_boolean')
    if allow_cache_response_depth_change:
        depths = [item['profile'].get('conv_cache_demand_outstanding') for item in (reference, current)]
        checks['cache_response_depths_are_powers_of_two'] = all(
            type(depth) is int and depth >= 1 and not depth & (depth - 1) for depth in depths)
        required.append('cache_response_depths_are_powers_of_two')
    profile_changes = {
        key: dict(reference=reference['profile'].get(key), current=current['profile'].get(key),
                  reference_recorded=key in reference['profile'], current_recorded=key in current['profile'])
        for key in sorted(reference['profile'].keys() | current['profile'].keys())
        if reference['profile'].get(key) != current['profile'].get(key)
        or (key in reference['profile']) != (key in current['profile'])}
    return dict(passed=all(checks[key] for key in required), checks=checks, cases=rows,
                comparison_mode=('selected_pipeline_changes' if allow_cache_response_depth_change else
                                 'preparation_stage_change' if allow_preparation_stage_change else 'strict'),
                permitted_profile_changes=sorted(comparison_parameters),
                required_checks=required, hardware_profile_changes=profile_changes,
                reference_total_cycles=reference['total_cycles'],
                current_total_cycles=current['total_cycles'],
                total_cycle_difference=current['total_cycles'] - reference['total_cycles'],
                increased_case_count=sum(row['cycle_difference'] > 0 for row in rows),
                decreased_case_count=sum(row['cycle_difference'] < 0 for row in rows),
                unchanged_case_count=sum(row['cycle_difference'] == 0 for row in rows),
                maximum_cycle_increase=max(0, max((row['cycle_difference'] for row in rows), default=0)),
                timing_result='not_increased' if checks['all_cycles_not_increased'] else 'increased')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--inputs-from', type=Path)
    parser.add_argument('--compare-with', type=Path)
    parser.add_argument('--allow-preparation-stage-change', action='store_true',
                        help='仅允许描述符与行地址准备寄存配置变化，并逐项报告周期增减')
    parser.add_argument('--allow-cache-response-depth-change', action='store_true',
                        help='允许缓存响应容量变化，并逐项报告周期增减')
    parser.add_argument('--verilator', default='verilator')
    parser.add_argument('--jobs', type=int, default=1)
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--collect-only', action='store_true')
    args = parser.parse_args()
    if args.allow_preparation_stage_change and not args.compare_with:
        parser.error('--allow-preparation-stage-change 需要 --compare-with')
    if args.allow_cache_response_depth_change and not args.compare_with:
        parser.error('--allow-cache-response-depth-change 需要 --compare-with')
    repo, out = args.repo.resolve(), args.out.resolve()
    inputs = args.inputs_from.resolve() if args.inputs_from else out / 'inputs'
    if not args.inputs_from and not args.collect_only:
        prepare_inputs(repo, inputs)
    verify_inputs(repo, inputs)
    if args.prepare_only:
        print(json.dumps(dict(prepared=62, inputs=str(inputs))))
        return 0
    if not args.collect_only:
        common = [sys.executable, str(repo / 'test/gemmini_comparison/run_storage_operators.py'),
                  '--repo', str(repo), '--reference-root', str(inputs), '--out', str(out),
                  '--verilator', args.verilator, '--jobs', str(args.jobs),
                  '--bank-bytes', '8192', '--bank-count', '7', '--cache-bytes', '4096',
                  '--pe-count', '8', '--synthesis', '--fpga']
        out.mkdir(parents=True, exist_ok=True)
        for index, (name, folder, count) in enumerate(COLLECTIONS):
            command = common + ['--workloads', str(inputs / folder)]
            if index:
                command.append('--skip-build')
            with (out / (name + '.log')).open('w') as log:
                subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
            save_collection(out, name, count)
            print(json.dumps(dict(collection=name, passed=True, cases=count)), flush=True)
    result = collect(out, inputs)
    if args.compare_with:
        reference = args.compare_with.resolve()
        if reference.is_dir():
            reference /= 'all_cases.json'
        comparison = compare(read(reference), result,
                             allow_preparation_stage_change=args.allow_preparation_stage_change,
                             allow_cache_response_depth_change=args.allow_cache_response_depth_change)
        write(out / 'comparison.json', comparison)
        if not comparison['passed']:
            print(json.dumps(comparison['checks'], ensure_ascii=False))
            return 1
    print(json.dumps(dict(passed=True, case_count=result['case_count'],
                         total_cycles=result['total_cycles'], result=str(out / 'all_cases.json'))))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
