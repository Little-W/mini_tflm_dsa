#!/usr/bin/env python3
"""核对实际 RTL、证明日志及映射输入，汇总 IA 加载许可的验证结果。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CHANGED = ('rtl/npu/loaders/ia_loader.sv', 'rtl/npu/loaders/ia_loader_ctrl.sv')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path):
    return json.loads(path.read_text())


def check_hashes(hashes, root=ROOT):
    for name, expected in hashes.items():
        path = Path(name)
        if not path.is_absolute():
            path = root / path
        if digest(path) != expected:
            raise RuntimeError('Source hash differs: ' + str(path))


def check_models(folder, data):
    library = Path(data.get('library', data.get('vendor_source', '')))
    expected = data.get('library_sha256', data.get('vendor_sha256'))
    if digest(library) != expected:
        raise RuntimeError('Primitive library differs')
    models = [path for path in folder.glob('xilinx_*') if path.is_file() and digest(path) == data['models_sha256']]
    if len(models) != 1:
        raise RuntimeError('Primitive functional model is missing or ambiguous')


def revision(name):
    return subprocess.check_output(['git', 'rev-parse', name], cwd=ROOT, text=True).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path, default=ROOT / 'build/ia_reuse_admission')
    parser.add_argument('--reference-map', type=Path)
    parser.add_argument('--current-map', type=Path)
    parser.add_argument('--out', type=Path, default=HERE / 'measurement.json')
    args = parser.parse_args()
    build = args.build.resolve()
    report = {'reference_revision': revision('3c8cafeb'),
        'changed_source_sha256': {name: digest(ROOT / name) for name in CHANGED},
        'formal': {}, 'numeric': {}, 'mapping': {}}
    for kind, directory, required in (('full_state', 'formal_final', 8), ('combinational', 'control_final', 16)):
        folder = build / directory
        data = load(folder / 'summary.json')
        if not data['passed'] or len(data['runs']) != required or not all(row['passed'] for row in data['runs']):
            raise RuntimeError('Formal verification is incomplete: ' + kind)
        if data.get('input_constraints', data.get('source_input_constraints', True)):
            raise RuntimeError('Formal inputs must remain unrestricted')
        if revision(data.get('reference_revision', data.get('reference_rev'))) != report['reference_revision']:
            raise RuntimeError('Formal reference differs')
        check_hashes(data['source_sha256'])
        check_models(folder, data['primitive_models'])
        for row in data['runs']:
            log = folder / (row['name'] + '.log')
            if digest(log) != row['log_sha256']:
                raise RuntimeError('Formal log differs: ' + row['name'])
            text = log.read_text()
            if kind == 'full_state':
                match = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', text)
                if not match or int(match[1]) != row['equivalent_bits'] or int(match[2]) or 'Equivalence successfully proven' not in text:
                    raise RuntimeError('Full-state result is incomplete')
            elif 'no model found: SUCCESS!' not in text or digest(folder / (row['name'] + '.ys')) != row['script_sha256']:
                raise RuntimeError('Combinational result differs')
        if kind == 'full_state':
            check_hashes(data['common_sha256'])
            for name, expected in data['source_sha256'].items():
                if digest(folder / 'current' / Path(name).name) != expected:
                    raise RuntimeError('Formal current snapshot differs')
                original = subprocess.check_output(['git', 'show', report['reference_revision'] + ':' + name], cwd=ROOT)
                if (folder / 'reference' / Path(name).name).read_bytes() != original:
                    raise RuntimeError('Formal reference snapshot differs')
            data['equivalent_bits'] = sum(row['equivalent_bits'] for row in data['runs'])
        else:
            check_hashes(data['miter_sha256'], folder)
        report['formal'][kind] = data | {'summary_sha256': digest(folder / 'summary.json')}

    folder = build / 'numeric_final'
    numeric = load(folder / 'summary.json')
    if not numeric['passed'] or not numeric['fpga_primitives_enabled'] or len(numeric['runs']) != 1:
        raise RuntimeError('FPGA numerical verification is incomplete')
    if numeric['reference_commit'] != report['reference_revision']:
        raise RuntimeError('Numerical reference differs')
    check_hashes(numeric['source_sha256'])
    wrapper = numeric['runs'][0]
    if not wrapper['passed'] or wrapper['name'] != 'interface':
        raise RuntimeError('IA interface comparison is missing')
    check_models(folder / 'interface', wrapper['primitive_models'])
    check_hashes({'run.log': wrapper['log_sha256'], 'verilator_models': wrapper['wrapper_sha256'],
                  'primitive_widths.vlt': wrapper['primitive_lint_file_sha256']}, folder / 'interface')
    interface_folder = folder / 'interface/run'
    interface = load(interface_folder / 'summary.json')
    if interface != wrapper['result'] or not interface['passed'] or len(interface['runs']) != 2:
        raise RuntimeError('IA cycle result differs')
    check_hashes(interface['source_sha256'])
    check_hashes(interface['generated_sha256'], interface_folder)
    check_models(interface_folder, interface['primitive_models'])
    results = []
    for row in interface['runs']:
        detail_path = Path(row['summary'])
        detail = load(detail_path)
        if row['case'] == 'grouped32':
            detail = detail['tests']['loader']
        if not row['passed'] or not detail['passed']:
            raise RuntimeError('Numerical case is incomplete')
        check_hashes(detail['source_sha256'])
        if any(row[key] != detail[key] for key in ('cycles', 'value_checks')):
            raise RuntimeError('Numerical totals differ')
        results.append({key: value for key, value in row.items() if key not in ('command', 'summary')} |
            {'summary_sha256': digest(detail_path), 'numeric_result': {key: value for key, value in detail.items()
                if key not in ('compile_command', 'run_command', 'elapsed_seconds')}})
    report['numeric'] = {'passed': True, 'compared_outputs': interface['compared_outputs'],
        'source_sha256': numeric['source_sha256'], 'runs': results,
        'cycles': sum(row['cycles'] for row in results), 'value_checks': sum(row['value_checks'] for row in results),
        'fpga_primitives_enabled': True, 'primitive_models': [wrapper['primitive_models'], interface['primitive_models']],
        'summary_sha256': digest(folder / 'summary.json'),
        'interface_summary_sha256': digest(interface_folder / 'summary.json')}

    folders = {'reference': args.reference_map or build / 'joint/reference',
               'current': args.current_map or build / 'joint_final/current'}
    for label, folder in folders.items():
        data = load(folder / 'summary.json')
        manifest = data['manifest']
        if revision(manifest['reference_revision']) != report['reference_revision']:
            raise RuntimeError('Mapping reference differs')
        if (manifest['controller_output_analysis_boundaries'] or not manifest['full_ia_controller'] or
                manifest['address_width'] != 32 or manifest['count_width'] != 29 or
                '-GADDR_WIDTH=32' not in manifest['options']):
            raise RuntimeError('Full SoC-width IA controller is required')
        if any(row['type'].startswith('ia_loader_ctrl') for row in data['interface_boundaries']):
            raise RuntimeError('The IA controller must be retained')
        if label == 'current':
            check_hashes(manifest['source_sha256'])
        check_hashes(manifest['source_sha256'], folder / 'sources')
        artifacts = {'mapped.json': data['mapped_sha256'], 'pre_lut.il': data['pre_lut_sha256'],
            'manifest.json': data['manifest_sha256'], '03_map_lut.log': data['functional_verification']['log_sha256'],
            'xilinx_primitives.sv': manifest['primitive_models']['model_sha256'],
            'native.lut': data['lut_library']['source_library_sha256'],
            'physical.lut': data['lut_library']['library_sha256']}
        check_hashes(artifacts, folder)
        if not data['functional_verification']['passed']:
            raise RuntimeError('Mapped truth verification is incomplete')
        pre_lut = (folder / 'pre_lut.il').read_text()
        widths = {}
        for name, expected in (('l2_idx', 29), ('load_ia_cursor', 7)):
            match = re.search(r'attribute \\hdlname "u_ia_loader u_ctrl ' + name + r'"\s+wire width (\d+)', pre_lut)
            if not match or int(match[1]) != expected:
                raise RuntimeError('Elaborated controller width differs: ' + name)
            widths[name] = int(match[1])
        paths = {}
        for name, path in data['paths'].items():
            if not path['graph_complete'] or not path['register_to_register_paths']:
                raise RuntimeError('Connected register path is incomplete: ' + label + '/' + name)
            paths[name] = {key: value for key, value in path.items()
                if key not in ('register_to_register_paths', 'distinct_register_path_groups')} | {
                    'longest_path': path['register_to_register_paths'][0]}
        report['mapping'][label] = {key: value for key, value in data.items() if key != 'paths'} | {
            'paths': paths, 'elaborated_controller_widths': widths, 'summary_sha256': digest(folder / 'summary.json')}
    current = report['mapping']['current']['paths']
    report['path_requirement'] = {'maximum_combinational_cells': 15,
        'observed': {name: path['longest_register_path_cells'] for name, path in current.items()},
        'met': all(path['longest_register_path_cells'] <= 15 for path in current.values()),
        'scope': 'Actual NPU connections with complete IA controller; register outputs to register D/CE/reset inputs.'}
    if not report['path_requirement']['met']:
        raise RuntimeError('The IA admission paths exceed the requested limit')
    scripts = [*sorted(HERE.glob('*.py')), ROOT / 'test/ia_write_output_depth/run_numeric.py',
        ROOT / 'test/ia_write_output_depth/primitives.py', ROOT / 'test/ia_write_admission/run_interface.py',
        ROOT / 'test/ia_request_lut/run_interface.py', ROOT / 'test/ia_request_lut/models.py',
        ROOT / 'test/ia_timing/run_interface.py', ROOT / 'scripts/fpga/open_fpga_synth.py',
        ROOT / 'scripts/fpga/remap_fpga_luts.py', ROOT / 'scripts/fpga/netlist_metrics.py',
        ROOT / 'scripts/fpga/lut_dependencies.py']
    report['verification_source_sha256'] = {str(path.relative_to(ROOT)): digest(path) for path in scripts}
    report['physical_lut_positions'] = None
    report['timing_150mhz_confirmed'] = False
    report['passed'] = True
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'passed': True, 'report_sha256': digest(args.out),
        'formal_bits': report['formal']['full_state']['equivalent_bits'],
        'paths': report['path_requirement']['observed']}))


if __name__ == '__main__':
    main()
