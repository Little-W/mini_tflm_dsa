#!/usr/bin/env python3
"""核对读取首段地址比较的源码、日志、资源和组合路径。"""
import argparse
import re
import hashlib
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]
SOURCE = 'rtl/npu/dma/axi_linear_block_dma.sv'
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--reference', default='38f32d93')
parser.add_argument('--results', type=Path, default=ROOT / 'build/first_address')
parser.add_argument('--reference-map', type=Path)
parser.add_argument('--current-map', type=Path)
parser.add_argument('--native-paths', type=Path)
parser.add_argument('--cost-paths', type=Path)
parser.add_argument('--out', type=Path, default=ROOT / 'test/dma_first_address/measurement.json')
args = parser.parse_args()
REFERENCE = args.reference
CURRENT_HASH = hashlib.sha256((ROOT / SOURCE).read_bytes()).hexdigest()
REFERENCE_HASH = hashlib.sha256(read_rtl_source(REFERENCE + ':' + SOURCE, cwd=ROOT)).hexdigest()
FINAL = args.results.resolve()
CURRENT_MAP = (args.current_map or FINAL).resolve()
REFERENCE_MAP = (args.reference_map or FINAL).resolve()
NATIVE_PATHS = (args.native_paths or FINAL / 'native_paths.json').resolve()
COST_PATHS = (args.cost_paths or FINAL / 'cost_paths.json').resolve()


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


assert sha(ROOT / SOURCE) == CURRENT_HASH
assert hashlib.sha256(read_rtl_source(REFERENCE + ':' + SOURCE, cwd=ROOT)).hexdigest() == REFERENCE_HASH

formal = []
for name in ['formal_fpga', 'formal_generic']:
    summary = read(FINAL / name / 'summary.json')
    assert summary['passed'] and not summary['inputs_constrained']
    assert summary['source_sha256'][SOURCE] == CURRENT_HASH
    assert summary['original_reference_sha256'] == REFERENCE_HASH
    for filename, digest in summary['source_sha256'].items():
        assert sha(ROOT / filename) == digest
    for run in summary['runs']:
        assert run['passed']
        folder = ('s{SIZE}_b{BUS_WIDTH}_d{DATA_WIDTH}_c{RD_CONTEXT_DEPTH}'
                  '_a{REG_WIDTH}_m{DMA_MAX_BYTES}_k{CACHE_BLOCKS}').format(**run)
        assert sha(FINAL / name / folder / 'formal.log') == run['log_sha256']
    formal.append(summary)

reference_manifest_path = FINAL / 'reference_runtime/source_manifest.json'
reference_numeric = {width: read(FINAL / f'reference_numeric{width}/summary.json')
                     for width in [32, 64]}
numeric = []
for width in [32, 64]:
    data = read(FINAL / f'numeric{width}/summary.json')
    assert data['passed'] and data['source_sha256'][SOURCE] == CURRENT_HASH
    assert reference_numeric[width]['source_sha256'][SOURCE] == REFERENCE_HASH
    assert data['sources_unchanged_during_build']
    assert reference_numeric[width]['passed']
    assert reference_numeric[width]['sources_unchanged_during_build']
    assert data['primitive_library_sha256'] == reference_numeric[width]['primitive_library_sha256']
    for label, summary in [(f'numeric{width}', data),
                           (f'reference_numeric{width}', reference_numeric[width])]:
        directory = FINAL / label
        assert sha(directory / 'obj/Vlinear_dma_4k_top') == summary['binary_sha256']
        for run in summary['runs']:
            assert run['passed'] and run['returncode'] == 0
            log = (directory / ('random.log' if run['random'] else 'fixed.log')).read_text()
            assert 'LINEAR_CONTEXT_PASS' in log
            counters = {key: int(value) for key, value in re.findall(r'(\w+)=(\d+)', log)}
            assert counters == run['counters']
    for filename, digest in data['source_sha256'].items():
        if filename != SOURCE:
            assert reference_numeric[width]['source_sha256'][filename] == digest
            assert sha(ROOT / filename) == digest
    for field in ['outstanding', 'contexts', 'dma_max_bytes', 'bus_width', 'fpga']:
        assert data[field] == reference_numeric[width][field]
    assert data['runs'] == reference_numeric[width]['runs']
    numeric.append(data)

artifacts = {}
mapping = {}
for flow, folder_name, paths_path in [
        ('native', 'synthesis', NATIVE_PATHS),
        ('physical_cost', 'cost', COST_PATHS)]:
    paths = read(paths_path)
    artifacts[str(paths_path)] = sha(paths_path)
    mapping[flow] = {}
    for label, directory, expected_hash in [
            ('reference', REFERENCE_MAP / folder_name / 'reference', REFERENCE_HASH),
            ('current', CURRENT_MAP / folder_name / 'current', CURRENT_HASH)]:
        metrics = read(directory / 'metrics.json')
        manifest = read(directory / 'manifest.json')
        assert expected_hash in manifest['sources_sha256'].values()
        for filename, expected in manifest['sources_sha256'].items():
            if filename.startswith('rtl/'):
                assert sha(ROOT / filename) == expected
        assert sha(directory / 'mapped.json') == paths[label]['mapped_sha256']
        assert metrics['paths']['graph_complete']
        targeted = {}
        for target, detail in paths[label]['dsp_output_port_paths'].items():
            assert detail['graph_complete']
            targeted[target] = {
                'combinational_cells': detail['longest_register_path_cells'],
                'path': detail['register_to_register_paths'][0],
            }
        mapping[flow][label] = {
            'resources': metrics['resources'],
            'longest_register_path_cells': metrics['paths']['longest_register_path_cells'],
            'graph_complete': metrics['paths']['graph_complete'],
            'dsp_output_port_paths': targeted,
            'source_manifest': manifest,
        }
        for filename in ['mapped.json', 'pre_lut.il', 'metrics.json', 'manifest.json']:
            artifacts[str(directory / filename)] = sha(directory / filename)
        if flow == 'physical_cost':
            verification = read(directory / 'verification.json')
            assert verification['passed']
            mapping[flow][label]['lut_mapping_verification'] = verification
            artifacts[str(directory / 'verification.json')] = sha(directory / 'verification.json')

    reference_manifest = mapping[flow]['reference']['source_manifest']
    current_manifest = mapping[flow]['current']['source_manifest']
    for field in ['top', 'parameters', 'options', 'build_configuration',
                  'primitive_models', 'part', 'clock_period_ns']:
        assert reference_manifest[field] == current_manifest[field]
    reference_helpers = {name: digest for name, digest in reference_manifest['sources_sha256'].items()
                         if name.startswith('rtl/')}
    current_helpers = {name: digest for name, digest in current_manifest['sources_sha256'].items()
                       if name.startswith('rtl/')}
    assert reference_helpers == current_helpers

numeric_comparison = {
    'passed': True,
    'source_sha256': CURRENT_HASH,
    'reference_source_sha256': REFERENCE_HASH,
    'all_counters_and_cycles_equal': True,
    'commands': sum(run['counters']['commands'] for data in numeric for run in data['runs']),
    'compared_values': sum(run['counters']['outputs'] for data in numeric for run in data['runs']),
    'cycles': sum(run['counters']['cycles'] for data in numeric for run in data['runs']),
}
assert read(reference_manifest_path)['source_sha256'] == reference_numeric[32]['source_sha256']

for filename in ['formal_fpga/summary.json',
                 'formal_generic/summary.json', 'numeric32/summary.json', 'numeric64/summary.json',
                 'reference_numeric32/summary.json', 'reference_numeric64/summary.json']:
    artifacts[str(FINAL / filename)] = sha(FINAL / filename)
artifacts[str(reference_manifest_path)] = sha(reference_manifest_path)

report = {
    'passed': True,
    'reference_commit': subprocess.check_output(['git', 'rev-parse', REFERENCE], cwd=ROOT, text=True).strip(),
    'source_sha256': {SOURCE: CURRENT_HASH},
    'reference_source_sha256': {SOURCE: REFERENCE_HASH},
    'configuration': {'SIZE': 64, 'BUS_WIDTH': 64, 'DATA_WIDTH': 16,
                      'REG_WIDTH': 32, 'CACHE_BLOCKS': 64, 'RD_CONTEXT_DEPTH': 4,
                      'RD_TAG_WIDTH': 3, 'DMA_MAX_BYTES': 2048},
    'formal': formal,
    'numeric': numeric,
    'reference_numeric': [reference_numeric[width] for width in [32, 64]],
    'numeric_comparison': numeric_comparison,
    'mapping': mapping,
    'artifact_sha256': artifacts,
}
output = args.out.resolve()
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'output': str(output), 'passed': True,
                  'formal_configurations': sum(len(data['runs']) for data in formal),
                  'formal_equivalent_bits': sum(run['equivalent_bits'] for data in formal for run in data['runs']),
                  'numeric_comparison': report['numeric_comparison']}, indent=2))
