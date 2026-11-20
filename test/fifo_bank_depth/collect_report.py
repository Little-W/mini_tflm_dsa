#!/usr/bin/env python3
"""核对完整 FIFO 的形式比较、逐周期数值测试和实际映射结果。"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]
SOURCE = 'rtl/npu/writeback/vec_s8_to_fifo.sv'


def contents(path):
    if path.exists():
        return path.read_bytes()
    return gzip.decompress(path.with_suffix(path.suffix + '.gz').read_bytes())


def digest(path):
    return hashlib.sha256(contents(path)).hexdigest()


def read(path):
    return json.loads(contents(path))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', type=Path, default=ROOT / 'build/fifo_bank_depth')
    parser.add_argument('--reference', default='eaba7635')
    parser.add_argument('--soc-paths', type=Path)
    parser.add_argument('--out', type=Path, default=ROOT / 'test/fifo_bank_depth/measurement.json')
    args = parser.parse_args()
    results = args.results.resolve()
    current_hash = digest(ROOT / SOURCE)
    reference_hash = hashlib.sha256(read_rtl_source(args.reference + ':' + SOURCE, cwd=ROOT)).hexdigest()
    artifacts = {}

    formal_file = results / 'formal/summary.json'
    formal = read(formal_file)
    assert formal['passed'] and len(formal['formal']) == 7
    assert not formal['inputs_constrained'] and not formal['ram_read_data_constrained']
    assert formal['storage_implementation_identical']
    assert formal['source_sha256'] == current_hash
    assert formal['reference_sha256'] == reference_hash
    for run in formal['formal']:
        assert run['passed']
        profile = ('v{vlen}_n{banks}_b{bus_width}_c{cyclic_storage}_').format(**run)
        profile += 'fpga' if run['fpga'] else 'generic'
        log = results / 'formal' / profile / 'formal.log'
        assert digest(log) == run['log_sha256']
        artifacts[str(log)] = digest(log)
    artifacts[str(formal_file)] = digest(formal_file)

    numeric = []
    for banks in (16, 32):
        for width in (32, 64):
            folder = results / f'numeric{banks}_{width}'
            data = read(folder / 'summary.json')
            assert data['passed'] and data['sources_unchanged'] and data['fpga']
            assert data['banks'] == banks and data['bus_width'] == width
            assert data['sources_sha256'][SOURCE] == current_hash
            assert data['reference_sha256']['vec_s8_to_fifo.sv'] == reference_hash
            assert data['primitive_library_sha256'] == formal['primitive_library_sha256']
            for filename, value in data['sources_sha256'].items():
                assert digest(ROOT / filename) == value
            log = contents(folder / 'run.log').decode()
            match = re.search(r'WRITEBACK_BUS_PASS bus_width=(\d+) cases=(\d+) checked_bytes=(\d+)', log)
            assert match is not None
            assert (int(match[1]), int(match[2]), int(match[3])) == (
                width, data['cases'], data['checked_bytes'])
            data['binary_sha256'] = digest(folder / 'obj/Vtb_writeback_bus')
            numeric.append(data)
            for filename in ('summary.json', 'run.log', 'obj/Vtb_writeback_bus'):
                artifacts[str(folder / filename)] = digest(folder / filename)

    mapping = {}
    for flow, subdirectory, path_file in [
            ('native', 'wrapped_synthesis', 'wrapped_native_paths.json'),
            ('physical_cost', 'wrapped_cost', 'wrapped_cost_paths.json')]:
        paths = read(results / path_file)
        artifacts[str(results / path_file)] = digest(results / path_file)
        mapping[flow] = {}
        for label, expected in [('reference', reference_hash), ('current', current_hash)]:
            directory = results / subdirectory / label
            metrics = read(directory / 'metrics.json')
            manifest = read(directory / 'manifest.json')
            assert expected in manifest['sources_sha256'].values()
            assert metrics['paths']['graph_complete']
            assert digest(directory / 'mapped.json') == paths[label]['mapped_sha256']
            assert digest(directory / 'pre_lut.il') == paths[label]['pre_lut_sha256']
            for filename, value in manifest['sources_sha256'].items():
                assert digest(ROOT / filename) == value
            path_summary = {}
            for name, detail in paths[label]['paths'].items():
                assert detail['graph_complete']
                if label == 'current':
                    assert detail['longest_register_path_cells'] <= 15
                path_summary[name] = {
                    'combinational_cells': detail['longest_register_path_cells'],
                    'longest_path': detail['register_to_register_paths'][0],
                }
            mapping[flow][label] = {
                'resources': metrics['resources'],
                'longest_register_path_cells': metrics['paths']['longest_register_path_cells'],
                'fifo_paths': path_summary,
                'source_manifest': manifest,
            }
            for filename in ('mapped.json', 'pre_lut.il', 'metrics.json', 'manifest.json'):
                artifacts[str(directory / filename)] = digest(directory / filename)
            if flow == 'physical_cost':
                verification = read(directory / 'verification.json')
                assert verification['passed']
                mapping[flow][label]['lut_mapping_verification'] = verification
                artifacts[str(directory / 'verification.json')] = digest(directory / 'verification.json')
        reference_manifest = mapping[flow]['reference']['source_manifest']
        current_manifest = mapping[flow]['current']['source_manifest']
        for field in ('top', 'parameters', 'options', 'build_configuration',
                      'primitive_models', 'part', 'clock_period_ns'):
            assert reference_manifest[field] == current_manifest[field]
        dependencies = []
        for manifest in (reference_manifest, current_manifest):
            normalized = {}
            for filename, value in manifest['sources_sha256'].items():
                name = re.sub(r'^(reference|current)_', '', Path(filename).name)
                if name != 'vec_s8_to_fifo.sv':
                    normalized[name] = value
            dependencies.append(normalized)
        assert dependencies[0] == dependencies[1]

    report = {
        'passed': True,
        'reference_commit': subprocess.check_output(
            ['git', 'rev-parse', args.reference], cwd=ROOT, text=True).strip(),
        'source_sha256': {SOURCE: current_hash},
        'reference_source_sha256': {SOURCE: reference_hash},
        'configuration': {'VLEN': 16, 'BANKS': 32, 'BUS_WIDTH': 64,
                          'COUNT_WIDTH': 28, 'p_cyclic_storage': 1,
                          'output_register_entries': 2, 'logical_fifo_bytes': 8192},
        'formal': formal,
        'numeric': numeric,
        'numeric_totals': {'cases': sum(item['cases'] for item in numeric),
                           'checked_bytes': sum(item['checked_bytes'] for item in numeric)},
        'mapping': mapping,
        'artifact_sha256': artifacts,
    }
    if args.soc_paths:
        source = read(args.soc_paths)
        report['soc_reference_path'] = {
            'source_commit': source['source_commit'],
            'source_mapped_sha256': source['source_mapped_sha256'],
            'fifo': source['fifo'],
        }
        artifacts[str(args.soc_paths.resolve())] = digest(args.soc_paths)
    output = args.out.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'passed': True, 'source_sha256': current_hash,
                      'formal_configurations': len(formal['formal']),
                      'formal_equivalent_bits': formal['equivalent_bits'],
                      'numeric_totals': report['numeric_totals'],
                      'mapping': {flow: {label: {
                          'logic_luts': item['resources']['logic_lut_cells'],
                          'fifo_max_cells': item['fifo_paths']['all_fifo_endpoints']['combinational_cells']}
                          for label, item in values.items()} for flow, values in mapping.items()}}, indent=2))


if __name__ == '__main__':
    main()
