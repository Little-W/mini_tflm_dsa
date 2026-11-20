#!/usr/bin/env python3
"""核对最终源码与全部验证输入，保存 IA 请求及仲裁计数的测量报告。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CHANGED = ('rtl/npu/loaders/ia_loader.sv', 'rtl/npu/dma/axi_block_dma_arbiter.sv')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked_hashes(hashes):
    for name, expected in hashes.items():
        path = Path(name)
        if not path.is_absolute():
            path = ROOT / path
        if digest(path) != expected:
            raise RuntimeError('Source hash differs: ' + str(path))


def load(path):
    return json.loads(path.read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path, default=ROOT / 'build/ia_arbiter_request')
    parser.add_argument('--out', type=Path, default=HERE / 'measurement.json')
    args = parser.parse_args()
    build = args.build.resolve()
    report = {'reference_revision': subprocess.check_output(
        ['git', 'rev-parse', '437a8d81'], cwd=ROOT, text=True).strip(),
        'changed_source_sha256': {name: digest(ROOT / name) for name in CHANGED},
        'formal': {}, 'numeric': {}, 'mapping': {}}
    for kind, folder_name, runs in (('ia', 'ia_parallel_verified', 6), ('arbiter', 'arbiter_verified', 7)):
        folder = build / folder_name
        data = load(folder / 'summary.json')
        if not data['passed'] or len(data['runs']) != runs or not all(row['passed'] for row in data['runs']):
            raise RuntimeError('Complete formal verification is required: ' + kind)
        revision = data.get('reference_rev', data.get('reference_revision'))
        if subprocess.check_output(['git', 'rev-parse', revision], cwd=ROOT, text=True).strip() != report['reference_revision']:
            raise RuntimeError('Formal reference revision differs')
        checked_hashes(data['source_sha256'])
        if data['source_input_constraints']:
            raise RuntimeError('Expected unrestricted source inputs')
        for row in data['runs']:
            if digest(folder / (row['name'] + '.log')) != row['log_sha256']:
                raise RuntimeError('Formal log differs: ' + row['name'])
        if kind == 'ia':
            checked_hashes(data['common_sha256'])
            models = data['primitive_models']
            if digest(folder / 'xilinx_luts.v') != models['models_sha256'] or digest(Path(models['vendor_source'])) != models['vendor_sha256']:
                raise RuntimeError('IA primitive models differ')
            if len(data['equality_runs']) != 8 or not all(row['passed'] for row in data['equality_runs']):
                raise RuntimeError('Coordinate comparison coverage is incomplete')
            for row in data['equality_runs']:
                name = f"equality_{row['width']}_{row['low_width']}_{int(row['use_lut'])}.log"
                if digest(folder / name) != row['log_sha256']:
                    raise RuntimeError('Coordinate proof log differs')
        else:
            if data['dma_outputs_constrained']:
                raise RuntimeError('Expected unrestricted DMA responses')
            if digest(folder / 'lut_models.v') != data['primitive_model_sha256']:
                raise RuntimeError('Arbiter primitive models differ')
        report['formal'][kind] = {key: value for key, value in data.items() if key != 'runs'} | {
            'equivalent_bits': sum(row['equivalent_bits'] for row in data['runs']),
            'summary_sha256': digest(folder / 'summary.json'),
            'runs': [{key: value for key, value in row.items() if key != 'dma_ports'} for row in data['runs']]}
    interface = load(build / 'ia_cycle_verified/summary.json')
    if (not interface['passed'] or len(interface['runs']) != 2 or
            not all(row['passed'] for row in interface['runs']) or not interface['fpga_primitives_enabled']):
        raise RuntimeError('IA cycle comparison is incomplete')
    checked_hashes(interface['source_sha256'])
    if digest(build / 'ia_cycle_verified/xilinx_luts.v') != interface['primitive_models']['models_sha256']:
        raise RuntimeError('IA numerical primitive models differ')
    for name, expected in interface['generated_sha256'].items():
        if digest(build / 'ia_cycle_verified' / name) != expected:
            raise RuntimeError('Generated IA comparison source differs: ' + name)
    ia_runs = []
    for row in interface['runs']:
        detail = load(Path(row['summary']))
        if row['case'] == 'grouped32':
            detail = detail['tests']['loader']
        if not detail['passed']:
            raise RuntimeError('IA numerical detail is incomplete')
        checked_hashes(detail['source_sha256'])
        for key in ('cycles', 'value_checks'):
            if row[key] != detail[key]:
                raise RuntimeError('IA numerical totals differ: ' + key)
        ia_runs.append({key: value for key, value in row.items() if key not in ('command', 'summary')} |
            {'summary_sha256': digest(Path(row['summary'])),
             'numeric_result': {key: value for key, value in detail.items()
                if key not in ('compile_command', 'run_command', 'elapsed_seconds')}})
    report['numeric']['ia'] = {key: value for key, value in interface.items() if key != 'runs'} | {
        'summary_sha256': digest(build / 'ia_cycle_verified/summary.json'), 'runs': ia_runs}
    dma = load(build / 'dma_verified/summary.json')
    if not dma['passed'] or len(dma['runs']) != 2 or not all(row['passed'] for row in dma['runs']):
        raise RuntimeError('DMA numerical verification is incomplete')
    checked_hashes(dma['source_sha256'])
    if digest(build / 'dma_verified/xilinx_primitives.sv') != dma['primitive_models_sha256']:
        raise RuntimeError('DMA numerical primitive models differ')
    for row in dma['runs']:
        checked_hashes(row['source_sha256'])
        if digest(build / f"dma_verified/bus{row['bus_width']}/summary.json") != row['summary_sha256']:
            raise RuntimeError('DMA result differs')
    report['numeric']['dma'] = {'summary_sha256': digest(build / 'dma_verified/summary.json'),
        'primitive_library_sha256': dma['primitive_library_sha256'],
        'runs': [{key: value for key, value in row.items()
                  if key not in ('source_sha256', 'compile_command', 'run_command')} for row in dma['runs']]}
    window = load(build / 'window_verified/summary.json')
    if not window['passed'] or not window['reference']['passed'] or not window['resident_stream_cycle_equivalent']:
        raise RuntimeError('Window DMA cycle comparison is incomplete')
    for row in (window, window['reference']):
        checked_hashes(row['source_sha256'])
        if digest(Path(row['log']).parent / 'resident_stream.csv') != row['resident_stream_sha256']:
            raise RuntimeError('Window DMA cycle record differs')
    report['numeric']['window'] = {key: value for key, value in window.items()
        if key not in ('source_sha256', 'reference', 'log')} | {
        'summary_sha256': digest(build / 'window_verified/summary.json'),
        'reference_executable_sha256': window['reference']['executable_sha256']}
    for label in ('reference', 'current'):
        folder = build / 'joint_final' / label
        data = load(folder / 'summary.json')
        manifest = data['manifest']
        if label == 'current':
            checked_hashes(manifest['source_sha256'])
        for name, expected in manifest['source_sha256'].items():
            if digest(folder / 'sources' / name) != expected:
                raise RuntimeError('Mapped input snapshot differs: ' + name)
        if not manifest['controller_output_analysis_boundaries']:
            raise RuntimeError('All coordinate and slot bits must be retained')
        boundaries = data['analysis_boundaries']
        if (set(row['port'] for row in boundaries) != {'request_p0', 'request_q0', 'tl_slot_id'} or
                any(row['retained_bits'] != row['width'] or not row['analysis_only'] for row in boundaries)):
            raise RuntimeError('Controller output analysis boundaries are incomplete')
        for name, expected in (('mapped.json', data['mapped_sha256']), ('pre_lut.il', data['pre_lut_sha256']),
                               ('manifest.json', data['manifest_sha256']),
                               ('03_map_lut.log', data['functional_verification']['log_sha256']),
                               ('xilinx_primitives.sv', manifest['primitive_models']['model_sha256']),
                               ('native.lut', data['lut_library']['source_library_sha256']),
                               ('physical.lut', data['lut_library']['library_sha256'])):
            if digest(folder / name) != expected:
                raise RuntimeError('Mapping artifact differs: ' + name)
        if not data['functional_verification']['passed'] or not all(row['graph_complete'] for row in data['paths'].values()):
            raise RuntimeError('Mapped logic verification is incomplete')
        for name, path in data['paths'].items():
            if not path['register_to_register_paths'] and not (label == 'current' and name == 'slot_to_dw_count'):
                raise RuntimeError('Expected a connected path group: ' + label + '/' + name)
        report['mapping'][label] = data | {'summary_sha256': digest(folder / 'summary.json')}
    paths = report['mapping']['current']['paths']
    required = ('request_p0_to_grant', 'request_q0_to_grant', 'slot_to_client_counts',
                'slot_to_dw_count', 'ia_to_arbiter', 'all_to_grant', 'all_to_client_counts')
    report['path_requirement'] = {'maximum_combinational_cells': 15,
        'observed': {name: paths[name]['longest_register_path_cells'] for name in required},
        'met': all(paths[name]['longest_register_path_cells'] <= 15 for name in required),
        'scope': 'Actual NPU IA-to-arbiter connections; controller coordinate and slot outputs are analysis boundaries.'}
    if not report['path_requirement']['met']:
        raise RuntimeError('The requested IA and arbiter paths exceed 15 cells')
    scripts = [*sorted(HERE.glob('*.py')), ROOT / 'test/ia_write_admission/run_interface.py',
        ROOT / 'test/ia_request_lut/run_interface.py', ROOT / 'test/ia_request_lut/models.py',
        ROOT / 'test/ia_timing/run_interface.py', ROOT / 'test/dma_read_permission/run_numeric.py',
        ROOT / 'test/dma_abort/run_read_arbiter.py', ROOT / 'test/window_dma/run.py',
        ROOT / 'scripts/fpga/open_fpga_synth.py', ROOT / 'scripts/fpga/remap_fpga_luts.py',
        ROOT / 'scripts/fpga/netlist_metrics.py', ROOT / 'scripts/fpga/lut_dependencies.py']
    report['verification_source_sha256'] = {str(path.relative_to(ROOT)): digest(path) for path in scripts}
    report['passed'] = True
    report['physical_lut_positions'] = None
    report['timing_150mhz_confirmed'] = False
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'passed': True, 'report_sha256': digest(args.out),
        'formal_bits': {name: data['equivalent_bits'] for name, data in report['formal'].items()},
        'paths': report['path_requirement']['observed']}))


if __name__ == '__main__':
    main()
