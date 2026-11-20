#!/usr/bin/env python3
"""汇总固定 IA 缓存源码的形式、数值和实际连接测量。"""
import argparse
import hashlib
import json
from pathlib import Path

from run_formal import ROOT, SOURCE, cases


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--interface', type=Path)
    parser.add_argument('--shared', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    build = args.build.resolve()
    files = []

    def read(path):
        path = path.resolve()
        files.append(path)
        return json.loads(path.read_text())

    source_hash = digest(ROOT / SOURCE)
    formal = read(build / 'formal_all/summary.json')
    runs = {row['name']: row for row in formal['runs']}
    if (build / 'formal_production/summary.json').exists():
        production = read(build / 'formal_production/summary.json')
        assert production['passed'] and production['source_sha256'] == formal['source_sha256']
        runs.update({row['name']: row for row in production['runs']})
    assert set(runs) == set(cases())
    assert formal['source_sha256'][str(SOURCE)] == source_hash
    assert all(row['passed'] for row in runs.values())
    interface = read((args.interface or build / 'numeric/interface/run') / 'summary.json')
    shared = read((args.shared or build / 'numeric/shared/run') / 'summary.json')
    assert interface['passed'] and shared['passed']
    assert interface['source_sha256'][str(SOURCE)] == shared['source_sha256'][str(SOURCE)] == source_hash
    paths = read(build / 'paths.json')
    joint_path = build / 'joint_current_en_paths.json'
    joint = read(joint_path if joint_path.exists() else build / 'joint_current_paths.json')
    joint_cost = read(build / 'joint_cost_paths.json')
    joint_cost_summary = read(build / 'joint_cost/current/summary.json')
    assert joint['source_sha256'][str(SOURCE)] == source_hash
    assert joint['dsp_separation']['passed']
    assert joint_cost['source_sha256'] == joint['source_sha256']
    assert joint_cost['dsp_separation']['passed']
    assert joint_cost_summary['functional_verification']['passed']
    assert max(item['longest_register_path_cells'] for item in joint_cost['paths'].values()) <= 15
    manifests = {}
    for label in ('reference', 'current'):
        manifest = read(build / 'native' / label / 'manifest.json')
        if label == 'current':
            assert source_hash in manifest['sources_sha256'].values()
        manifests[label] = manifest
    assert manifests['reference']['parameters'] == manifests['current']['parameters']
    report = dict(passed=True, reference_commit=formal['reference_commit'],
        source_sha256={str(SOURCE): source_hash,
                       'rtl/npu/compute/select_add.sv': digest(ROOT / 'rtl/npu/compute/select_add.sv')},
        formal=dict(passed=True, inputs_constrained=False, cases=len(runs),
            equivalent_bits=sum(row['equivalent_bits'] for row in runs.values()),
            primitive_models=formal['primitive_models'], runs=list(runs.values())),
        numerical=dict(interface=interface, shared_ram=shared),
        mapping=dict(parameters=manifests['current']['parameters'],
            source_manifests=manifests, standalone=paths, actual_npu_native=joint,
            actual_npu_physical_cost=joint_cost,
            joint_cost_functional_verification=joint_cost_summary['functional_verification'],
            joint_cost_lut_library=joint_cost_summary['lut_library']),
        output_sha256={str(path.relative_to(ROOT)): digest(path) for path in files})
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(dict(passed=True, formal_cases=len(runs),
        equivalent_bits=report['formal']['equivalent_bits'],
        interface_cycles=sum(row['cycles'] for row in interface['runs']),
        shared_cycles=shared['cycles'],
        target_depths={name: item['longest_register_path_cells'] for name, item in joint['paths'].items()})))


if __name__ == '__main__':
    main()
