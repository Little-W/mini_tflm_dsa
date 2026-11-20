#!/usr/bin/env python3
"""核对 Softmax 写入资格的源码、完整写入证明、实际来源路径及生产数值结果。"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import runpy
import subprocess


ROOT = Path(__file__).resolve().parents[2]
SOURCE = 'rtl/npu/conv/vector_engine.sv'
SOFTMAX = 'rtl/npu/conv/vector_softmax.sv'
SCRIPTS = ('run_formal.py', 'prepare_measurement.py', 'measure_paths.py', 'collect.py')


def read_bytes(path):
    if path.exists():
        return path.read_bytes()
    with gzip.open(str(path) + '.gz', 'rb') as stream:
        return stream.read()


def digest(path):
    if path.exists():
        with path.open('rb') as stream:
            return hashlib.file_digest(stream, 'sha256').hexdigest()
    with gzip.open(str(path) + '.gz', 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def load(path):
    return json.loads(read_bytes(path))


def check_sources(values):
    for name, expected in values.items():
        assert digest(ROOT / name) == expected, name


def canonical_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--numeric-reference', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    build = args.build.resolve()
    source = (ROOT / SOURCE).read_text()
    source_sha256 = digest(ROOT / SOURCE)
    formal = load(build / 'formal/summary.json')
    reference = subprocess.check_output(
        ['git', 'show', formal['reference_commit'] + ':' + SOURCE], cwd=ROOT, text=True)
    helpers = runpy.run_path(str(Path(__file__).with_name('run_formal.py')))
    assert source.replace(helpers['section'](source), helpers['section'](reference), 1) == reference
    assert formal['passed'] and formal['source_sha256'] == source_sha256
    assert formal['reference_sha256'] == hashlib.sha256(reference.encode()).hexdigest()
    assert formal['outside_accumulator_block_unchanged'] and not formal['inputs_constrained']
    assert formal['softmax_data_identity_sha256'] == digest(ROOT / SOFTMAX)
    assert len(formal['cases']) == 12
    assert sum(row['compared_bits'] for row in formal['cases']) == 8400
    for row in formal['cases']:
        assert row['passed']
        folder = build / 'formal' / ('bus%d_tile%d_pe%d' % (
            row['bus_width'], row['tile'], row['pe_count']))
        stem = row['implementation']
        assert digest(folder / (stem + '.log')) == row['log_sha256']
        assert digest(folder / (stem + '.ys')) == row['script_sha256']
        assert b'SAT proof finished - no model found: SUCCESS!' in read_bytes(folder / (stem + '.log'))
        for label, text in (('reference', reference), ('current', source)):
            expected = helpers['unit'](text, label, row['bus_width'], row['tile'], row['pe_count'])
            assert expected.encode() == read_bytes(folder / (label + '.sv'))
            assert digest(folder / (label + '.sv')) == row['model_sha256'][label]

    generator = runpy.run_path(str(Path(__file__).with_name('prepare_measurement.py')))
    model_sources = {}
    for name in ('local', 'connected'):
        manifest = load(build / name / 'source.json')
        assert manifest['reference_commit'] == formal['reference_commit']
        assert manifest['cases']['current']['source_sha256'] == source_sha256
        assert manifest['cases']['reference']['source_sha256'] == formal['reference_sha256']
        assert manifest['softmax_sha256'] == digest(ROOT / SOFTMAX)
        assert manifest['generator_sha256'] == digest(Path(__file__).with_name('prepare_measurement.py'))
        assert manifest['formal_script_sha256'] == digest(Path(__file__).with_name('run_formal.py'))
        assert manifest['softmax_control_included'] == (name == 'connected')
        for label, text in (('reference', reference), ('current', source)):
            model = helpers['unit'](text, 'accumulator_write', 64, 16, 8, False)
            if name == 'connected':
                model = generator['with_softmax_control'](model, text, (ROOT / SOFTMAX).read_text())
            assert model.encode() == read_bytes(build / name / (label + '.sv'))
            assert digest(build / name / (label + '.sv')) == manifest['cases'][label]['model_sha256']
        model_sources[name] = manifest

    paths = load(build / 'paths.json')
    mappings = {}
    folders = (
        ('native', build / 'local/results', build / 'local/results'),
        ('physical_cost', build / 'cost', build / 'local/results'),
        ('connected_physical_cost', build / 'connected/cost', build / 'connected/pre'),
    )
    for mode, folder, pre_folder in folders:
        mappings[mode] = {}
        for label in ('reference', 'current'):
            row = paths[mode][label]
            current = folder / label
            assert row['mapped_sha256'] == digest(current / 'mapped.json')
            assert row['pre_lut_sha256'] == digest(pre_folder / label / 'pre_lut.il')
            assert row['all_paths']['graph_complete']
            manifest = load(current / 'manifest.json')
            check_sources(manifest['sources_sha256'])
            log = current / '03_map_lut.log'
            assert b'Networks are equivalent.' in read_bytes(log)
            if mode != 'native':
                verify = load(current / 'verification.json')
                assert verify['passed'] and verify['log_sha256'] == digest(log)
                assert manifest['pre_lut_origin']['sha256'] == row['pre_lut_sha256']
            mappings[mode][label] = {
                'resources': row['resources'],
                'longest_register_path_cells': row['all_paths']['longest_register_path_cells'],
                'graph_complete': True,
                'functional_mapping_verification': 'ABC9 &verify: passed',
                'mapped_sha256': row['mapped_sha256'],
                'pre_lut_sha256': row['pre_lut_sha256'],
                'source_paths': {s: {t: {k: v for k, v in p.items() if k != 'path'}
                                        for t, p in targets.items()} for s, targets in row['paths'].items()},
                'target_path_details': {s: row['paths'][s]['acc_buf']['path'] for s in (
                    'rd_raw_valid', 'soft_exp_we', 'rd_done', 'rd_error', 'soft_state', 'soft_exp_index')},
                'mapping_manifest_sha256': digest(current / 'manifest.json'),
                'mapping_log_sha256': digest(log),
            }

    numeric = load(build / 'fpga64/summary.json')
    assert numeric['tile'] == 16 and numeric['bus_width'] == 64
    assert numeric['implementation'] == 'official Xilinx primitive models'
    assert len(numeric['runs']) == 1
    run = numeric['runs'][0]
    assert run['passed'] and run['pe'] == 8
    assert run['totals']['cases'] == len(run['cases']) == 592
    model_path = build / 'fpga64/pe8/build.json'
    model = load(model_path)
    assert model['sha256'][SOURCE] == source_sha256
    check_sources(model['sha256'])
    assert digest(build / 'fpga64/pe8/obj/Vvector_engine_dma_top') == run['executable_sha256']
    reference_numeric = load(args.numeric_reference)
    reference_model_path = args.numeric_reference.parent / 'pe8/build.json'
    reference_model = load(reference_model_path)
    assert reference_model['sha256'][SOURCE] == formal['reference_sha256']
    reference_run = reference_numeric['runs'][0]
    assert reference_run['passed'] and reference_run['pe'] == 8
    assert run['cases'] == reference_run['cases'] and run['totals'] == reference_run['totals']
    log = read_bytes(build / 'fpga64/pe8/functional.log').decode()
    observer = next(line for line in log.splitlines() if line.startswith('VECTOR_INPUT_BANKS_PASS '))

    report = {
        'passed': True,
        'reference_commit': formal['reference_commit'],
        'source_sha256': source_sha256,
        'reference_source_sha256': formal['reference_sha256'],
        'added_register_bits': 0,
        'added_interface_cycles': 0,
        'formal': formal,
        'mapping_sources': model_sources,
        'mappings': mappings,
        'numeric': {
            'passed': True, 'tile': 16, 'pe': 8, 'bus_width': 64,
            'implementation': numeric['implementation'], 'totals': run['totals'],
            'task_cycles': sum(case['cycles'] for case in run['cases']),
            'each_case_statistics_equal': True,
            'case_statistics_sha256': canonical_digest(run['cases']),
            'summary_sha256': digest(build / 'fpga64/summary.json'),
            'reference_summary_sha256': digest(args.numeric_reference),
            'reference_model_sha256': digest(reference_model_path),
            'functional_log_sha256': digest(build / 'fpga64/pe8/functional.log'),
            'executable_sha256': run['executable_sha256'],
            'model_sha256': digest(model_path), 'model': model,
            'all_model_source_hashes_verified': True,
            'input_bank_observer': observer,
        },
        'report_sha256': {
            'formal': digest(build / 'formal/summary.json'),
            'paths': digest(build / 'paths.json'),
            'numeric': digest(build / 'fpga64/summary.json'),
        },
        'scripts_sha256': {name: digest(Path(__file__).with_name(name)) for name in SCRIPTS},
        'whole_soc_result': None,
        'timing_150mhz_confirmed': None,
        'timing_scope': '局部寄存器间组合深度；150 MHz 仍须厂商完整布线后静态时序检查。',
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'passed': True, 'source_sha256': source_sha256,
                      'formal_cases': len(formal['cases']), 'numeric': report['numeric']['totals'],
                      'task_cycles': report['numeric']['task_cycles']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
