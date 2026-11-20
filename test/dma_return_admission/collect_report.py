#!/usr/bin/env python3
"""核对源码、综合网表和验证记录，保存 DMA 返回与授予路径的测量结果。"""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CHANGED = ('rtl/npu/conv/conv_axi_read_mux.sv', 'rtl/npu/dma/axi_block_dma_arbiter.sv')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked_hashes(hashes):
    for name, expected in hashes.items():
        path = Path(name)
        if not path.is_absolute():
            path = ROOT / path
        if digest(path) != expected:
            raise RuntimeError('Source hash mismatch: ' + str(path))


def load(path):
    return json.loads(path.read_text())


def formal(folder):
    data = load(folder / 'summary.json')
    if not data['passed'] or not all(row['passed'] for row in data['runs']):
        raise RuntimeError('Formal verification is incomplete')
    checked_hashes(data['source_sha256'])
    for row in data['runs']:
        if digest(folder / (row['name'] + '.log')) != row['log_sha256']:
            raise RuntimeError('Formal log differs: ' + row['name'])
    return {key: value for key, value in data.items() if key != 'runs'} | {
        'summary_sha256': digest(folder / 'summary.json'),
        'equivalent_bits': sum(row['equivalent_bits'] for row in data['runs']),
        'runs': [{key: value for key, value in row.items() if key != 'dma_ports'} for row in data['runs']]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path, default=ROOT / 'build/dma_return_admission')
    parser.add_argument('--out', type=Path, default=HERE / 'measurement.json')
    args = parser.parse_args()
    build = args.build.resolve()
    inputs = load(build / 'joint_inputs/manifest.json')
    checked_hashes(inputs['source_sha256']['current'])
    for label in ('reference', 'current'):
        folder = build / 'joint_inputs' / label
        for name, expected in inputs['source_sha256'][label].items():
            if digest(folder / Path(name).name) != expected:
                raise RuntimeError('Source snapshot differs: ' + label + '/' + name)
        for name, expected in inputs['excerpt_sha256'][label].items():
            if digest(folder / name) != expected:
                raise RuntimeError('Source excerpt differs: ' + label + '/' + name)
    for name, expected in inputs['source_sha256']['reference'].items():
        if name not in CHANGED and inputs['source_sha256']['current'][name] != expected:
            raise RuntimeError('Joint reference context changed: ' + name)
    report = {'reference_revision': inputs['reference_revision'], 'scope': inputs['scope'],
              'source_sha256': inputs['source_sha256'], 'excerpt_sha256': inputs['excerpt_sha256'],
              'input_manifest_sha256': digest(build / 'joint_inputs/manifest.json'),
              'formal': {'arbiter': formal(build / 'arbiter_formal'),
                         'read_pair': formal(build / 'read_pair_formal')}}
    scripts = [*sorted(HERE.glob('*.py')), ROOT / 'test/dma_read_permission/run_formal.py',
               ROOT / 'test/dma_read_permission/run_numeric.py', ROOT / 'test/window_dma/run.py',
               ROOT / 'test/dma_read_permission/prepare_measurement.py',
               ROOT / 'test/dma_read_ready/read_pair.sv.inc']
    report['test_source_sha256'] = {str(path.relative_to(ROOT)): digest(path) for path in scripts}
    if report['formal']['arbiter']['source_input_constraints'] or \
            report['formal']['arbiter']['dma_outputs_constrained'] or \
            report['formal']['read_pair']['inputs_constrained']:
        raise RuntimeError('Expected unrestricted formal inputs')
    numeric = load(build / 'numeric/summary.json')
    if not numeric['passed'] or len(numeric['runs']) != 2:
        raise RuntimeError('DMA numerical verification is incomplete')
    checked_hashes(numeric['source_sha256'])
    report['dma_numeric'] = {'primitive_library_sha256': numeric['primitive_library_sha256'],
        'primitive_models_sha256': numeric['primitive_models_sha256'],
        'summary_sha256': digest(build / 'numeric/summary.json'), 'runs': []}
    for row in numeric['runs']:
        if not row['passed']:
            raise RuntimeError('DMA numerical verification failed')
        checked_hashes(row['source_sha256'])
        path = build / f"numeric/bus{row['bus_width']}/summary.json"
        if digest(path) != row['summary_sha256']:
            raise RuntimeError('DMA numerical summary differs')
        report['dma_numeric']['runs'].append({key: value for key, value in row.items()
            if key not in ('source_sha256', 'compile_command', 'run_command')})
    window = load(build / 'window_numeric/summary.json')
    if not window['passed'] or not window['reference']['passed'] or \
            not window['resident_stream_cycle_equivalent']:
        raise RuntimeError('Window DMA cycle comparison is incomplete')
    for row in (window, window['reference']):
        checked_hashes(row['source_sha256'])
        trace = Path(row['log']).parent / 'resident_stream.csv'
        if digest(trace) != row['resident_stream_sha256']:
            raise RuntimeError('Window DMA cycle record differs')
    report['window_numeric'] = {key: value for key, value in window.items()
        if key not in ('source_sha256', 'reference', 'log')}
    report['window_numeric']['summary_sha256'] = digest(build / 'window_numeric/summary.json')
    report['window_numeric']['reference_executable_sha256'] = window['reference']['executable_sha256']
    report['mapping'] = {}
    for mode, folder_name in (('native', 'joint_synthesis'), ('physical_cost', 'joint_cost')):
        report['mapping'][mode] = {}
        for label in ('reference', 'current'):
            folder = build / folder_name / label
            manifest = load(folder / 'manifest.json')
            checked_hashes(manifest['sources_sha256'])
            paths = load(folder / 'return_paths.json')
            pre_lut = build / 'joint_synthesis' / label / 'pre_lut.il'
            if digest(folder / 'mapped.json') != paths['mapped_sha256'] or \
                    digest(pre_lut) != paths['pre_lut_sha256']:
                raise RuntimeError('Measured netlist differs: ' + mode + '/' + label)
            if not paths['internal_paths']['graph_complete']:
                raise RuntimeError('Joint path graph is incomplete')
            if mode == 'physical_cost':
                mapping = load(folder / 'summary.json')
                if not mapping['functional_verification']['passed']:
                    raise RuntimeError('LUT mapping equivalence is incomplete')
            report['mapping'][mode][label] = {
                'manifest_sha256': digest(folder / 'manifest.json'),
                'mapped_sha256': paths['mapped_sha256'], 'pre_lut_sha256': paths['pre_lut_sha256'],
                'path_report_sha256': digest(folder / 'return_paths.json'),
                'resources': paths['resources'],
                'internal_register_maximum': paths['internal_paths']['longest_register_path_cells'],
                'port_paths': {source: {name: {key: value for key, value in row.items() if key != 'longest_path'}
                    for name, row in destinations.items()} for source, destinations in paths['port_paths'].items()},
                'segments': {source: {name: row['combinational_cells'] for name, row in destinations.items()}
                    for source, destinations in paths['segments'].items()},
                'context_to_idle_path': paths['port_paths']['rd_context_count']['kernel_idle']['longest_path'][0],
                'port_method': paths['port_method']}
    report['passed'] = True
    report['physical_lut_positions'] = None
    report['timing_150mhz_confirmed'] = False
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'passed': True, 'report_sha256': digest(args.out),
        'arbiter_equivalent_bits': report['formal']['arbiter']['equivalent_bits'],
        'read_pair_equivalent_bits': report['formal']['read_pair']['equivalent_bits'],
        'window_cycle_equivalent': report['window_numeric']['resident_stream_cycle_equivalent']}))


if __name__ == '__main__':
    main()
