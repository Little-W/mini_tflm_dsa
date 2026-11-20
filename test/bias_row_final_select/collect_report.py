#!/usr/bin/env python3
"""核对偏置行索引的状态证明、数值结果和寄存器输入路径。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from extract_control import ROOT, TOP, module_source


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def path_summary(data):
    return {key: data[key] for key in ('graph_complete', 'longest_register_path_cells', 'path_method')} | {
        'register_to_register_paths': data['register_to_register_paths'][:1],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', type=Path, default=ROOT / 'build/bias_row_final_select')
    parser.add_argument('--out', type=Path, default=ROOT / 'test/bias_row_final_select/measurement.json')
    args = parser.parse_args()
    results = args.results.resolve()
    artifacts = {}
    formal = {}
    for name in ('formal', 'group_index_formal', 'residency_formal'):
        path = results / name / 'summary.json'
        data = read(path)
        assert data['passed'] and not data['inputs_constrained']
        for filename, value in data['source_sha256'].items():
            assert digest(ROOT / filename) == value
        for profile in data['profiles']:
            assert profile['passed']
            if name == 'formal':
                folder = 's{SIZE}_g{BIAS_GROUP_BLOCKS_MAX}_r{REG_WIDTH}_'.format(**profile)
                folder += 'fpga' if profile['fpga'] else 'generic'
            else:
                folder = 's{SIZE}_b{BUS_WIDTH}_c{COUNT_WIDTH}_g{GROUP_BLOCKS_MAX}'.format(**profile)
            for filename, field in [('formal.log', 'log_sha256'), ('run.ys', 'script_sha256')]:
                file = results / name / folder / filename
                assert digest(file) == profile[field]
                artifacts[str(file)] = digest(file)
        formal[name] = data
        artifacts[str(path)] = digest(path)
    current_text = (ROOT / TOP).read_text()
    current_snapshot = hashlib.sha256(module_source(current_text).encode()).hexdigest()
    assert current_snapshot == formal['formal']['snapshot_sha256']['current']
    reference = formal['formal']['reference']
    reference_text = subprocess.check_output(
        ['git', 'show', reference + ':' + str(TOP)], cwd=ROOT, text=True)
    assert hashlib.sha256(module_source(reference_text).encode()).hexdigest() == \
        formal['formal']['snapshot_sha256']['reference']

    bias_numeric = read(results / 'bias_numeric/result.json')
    assert bias_numeric['passed'] and bias_numeric['sources_unchanged']
    for filename, value in bias_numeric['source_sha256'].items():
        assert digest(ROOT / filename) == value
    assert digest(Path(bias_numeric['simulator'])) == bias_numeric['simulator_sha256']
    for filename in ('result.json', 'run.log'):
        path = results / 'bias_numeric' / filename
        artifacts[str(path)] = digest(path)

    npu = read(results / 'npu/summary.json')
    npu_suite = read(results / 'npu/npu/summary.json')
    build = read(results / f"npu/npu/s{npu['SIZE']}/build.json")
    assert npu['passed'] and npu_suite['passed']
    assert build['returncode'] == 0 and build['sources_unchanged_during_build']
    assert build['source_sha256'][str(TOP)] == digest(ROOT / TOP)
    assert npu['primitive_library_sha256'] == formal['formal']['primitive_library_sha256']
    for filename, value in build['source_sha256'].items():
        assert digest(ROOT / filename) == value
    binary = results / f"npu/npu/s{npu['SIZE']}/obj/Vtb_conv_npu"
    assert digest(binary) == build['binary_sha256']
    for path in (results / 'npu/summary.json', results / 'npu/npu/summary.json',
                 results / f"npu/npu/s{npu['SIZE']}/build.json", binary):
        artifacts[str(path)] = digest(path)

    inputs = read(results / 'inputs/manifest.json')
    assert inputs['source_sha256']['current']['top_sha256'] == digest(ROOT / TOP)
    mapping = {}
    for flow, directory_name, paths_name in [
            ('native', 'synthesis', 'native_paths.json'),
            ('physical_cost', 'cost', 'cost_paths.json')]:
        paths = read(results / paths_name)
        artifacts[str(results / paths_name)] = digest(results / paths_name)
        mapping[flow] = {}
        for label in ('reference', 'current'):
            directory = results / directory_name / label
            metrics = read(directory / 'metrics.json')
            manifest = read(directory / 'manifest.json')
            expected = inputs['source_sha256'][label]['snapshot_sha256']
            assert expected in manifest['sources_sha256'].values()
            assert expected == formal['formal']['snapshot_sha256'][label]
            for filename, value in manifest['sources_sha256'].items():
                assert digest(ROOT / filename) == value
            assert metrics['paths']['graph_complete']
            assert digest(directory / 'mapped.json') == paths[label]['mapped_sha256']
            assert digest(directory / 'pre_lut.il') == paths[label]['pre_lut_sha256']
            mapping[flow][label] = {
                'resources': metrics['resources'],
                'longest_register_path_cells': metrics['paths']['longest_register_path_cells'],
                'register_to_row_index': path_summary(paths[label]['register_to_row_index']),
                'input_to_row_index': {signal: path_summary(detail)
                                       for signal, detail in paths[label]['input_to_row_index'].items()},
                'source_manifest': manifest,
            }
            if label == 'current':
                for signal in ('send_ia_trigger', 'init_cfg_ia', 'bias_sleep'):
                    assert paths[label]['input_to_row_index'][signal]['longest_register_path_cells'] == 1
            for filename in ('mapped.json', 'pre_lut.il', 'manifest.json', 'metrics.json'):
                artifacts[str(directory / filename)] = digest(directory / filename)
            if flow == 'physical_cost':
                verification = read(directory / 'verification.json')
                assert verification['passed']
                mapping[flow][label]['lut_mapping_verification'] = verification
                artifacts[str(directory / 'verification.json')] = digest(directory / 'verification.json')
        reference_manifest = mapping[flow]['reference']['source_manifest']
        current_manifest = mapping[flow]['current']['source_manifest']
        for field in ('top', 'parameters', 'options', 'primitive_models', 'part', 'clock_period_ns'):
            assert reference_manifest[field] == current_manifest[field]
        dependencies = []
        for manifest in (reference_manifest, current_manifest):
            dependencies.append({name: value for name, value in manifest['sources_sha256'].items()
                                 if name.startswith('rtl/')})
        assert dependencies[0] == dependencies[1]

    report = {
        'passed': True,
        'source_sha256': {str(TOP): digest(ROOT / TOP)},
        'reference_commit': subprocess.check_output(
            ['git', 'rev-parse', reference], cwd=ROOT, text=True).strip(),
        'configuration': {'SIZE': 16, 'REG_WIDTH': 32, 'BIAS_GROUP_BLOCKS_MAX': 32},
        'formal': formal,
        'bias_numeric': bias_numeric,
        'npu': npu,
        'npu_suite': npu_suite,
        'npu_build_manifest': build,
        'mapping': mapping,
        'artifact_sha256': artifacts,
    }
    prior_path = results / 'r18_bias_row_path.json'
    if prior_path.exists():
        report['soc_reference_path'] = read(prior_path)
        artifacts[str(prior_path)] = digest(prior_path)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'passed': True, 'source_sha256': report['source_sha256'],
                      'formal': {name: {'profiles': len(data['profiles']),
                                        'equivalent_bits': sum(p['equivalent_bits'] for p in data['profiles'])}
                                 for name, data in formal.items()},
                      'bias_cases': bias_numeric['case_count'],
                      'npu_tasks': npu['tasks'], 'npu_int32_checks': npu['int32_checks']}, indent=2))


if __name__ == '__main__':
    main()
