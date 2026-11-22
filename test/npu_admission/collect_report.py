#!/usr/bin/env python3
"""核对受测源码，汇总配置接收和完整帧地址参数的实际检查结果。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from run_formal import ROOT, TOP, CURRENT_FLAGS, current_admission, condition_module, digest
sys.path.insert(0, str(ROOT/'scripts/fpga'))
from netlist_metrics import connected_paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--require-complete', action='store_true',
                        help='要求调度器和完整地址模块的形式检查也已完成')
    args = parser.parse_args()
    build, source_root = args.build.resolve(), args.source_root.resolve()

    def read(name):
        return json.loads((build/name).read_text())

    formal = read('verified_formal/summary.json')
    if not formal['passed']:
        raise RuntimeError('The requested formal checks must pass')
    scope_name = formal.get('scope')
    if scope_name not in ('admission_only', 'complete_local_checks'):
        raise RuntimeError('Formal report must declare its validation scope')
    if args.require_complete and scope_name != 'complete_local_checks':
        raise RuntimeError('The requested complete local checks are unavailable')
    complete = scope_name == 'complete_local_checks'
    if len(formal['admission']) != 1 or not formal['admission'][0]['passed']:
        raise RuntimeError('Ordinary RTL admission proof is unavailable')
    if complete and (len(formal['scheduler_invariant']) != 4 or len(formal['frame_address']) != 6 or
            not formal.get('scheduler_ready_coverage', {}).get('passed') or
            not all(row['passed'] for row in formal['scheduler_invariant'] + formal['frame_address'])):
        raise RuntimeError('Complete local proof coverage is incomplete')
    if formal['script_sha256'] != digest(Path(__file__).with_name('run_formal.py')):
        raise RuntimeError('The formal script changed after verification')
    results = {'formal': formal}
    for label, path in [('frame_numeric','frame_numeric/summary.json'),
                        ('shared_allocation_formal','allocation_formal/summary.json'),
                        ('registered_fault','registered_fault/summary.json')]:
        if (build/path).exists():
            results[label] = read(path)
    for label, result in results.items():
        if not result['passed']:
            raise RuntimeError(f'The check did not pass: {label}')
        for path, expected in result['source_sha256'].items():
            source = source_root/path
            if path.startswith('test/npu_admission/'):
                source = ROOT/path
            if digest(source) != expected:
                raise RuntimeError(f'Source changed for {label}: {path}')
    if 'frame_numeric' in results:
        numeric = results['frame_numeric']
        if {row['ready_mask_abort'] for row in numeric['profiles']} != {0,1}:
            raise RuntimeError('Both address readiness parameters must be validated')
        if not all(row['passed'] for row in numeric['profiles']):
            raise RuntimeError('Address readiness validation did not pass')
        if any(row['result_latency_cycles'] != numeric['result_latency_cycles'] or
               row['pipeline_products'] != numeric['pipeline_products'] for row in numeric['profiles']):
            raise RuntimeError('Address preparation latency differs between readiness parameters')

    mapping = None
    if (build/'mapping/manifest.json').exists():
        manifest = read('mapping/manifest.json')
        if manifest['source_sha256'][str(TOP)] != digest(source_root/TOP):
            raise RuntimeError('Mapped admission source differs from the formal source')
        for name, expected in manifest['source_files_sha256'].items():
            if digest(build/'mapping'/name) != expected:
                raise RuntimeError(f'Mapping source changed: {name}')
        files = [build/'mapping/results'/('admission_'+label)/name
                 for label in ('reference','current') for name in ('mapped.json','metrics.json','summary.json')]
        mapping = {'executed':False, 'status':'sources_prepared',
                   'manifest_sha256':digest(build/'mapping/manifest.json')}
        if any(path.exists() for path in files):
            if not all(path.exists() for path in files):
                raise RuntimeError('Admission mapping results are incomplete')
            mapping.update(executed=True, status='verified', results={})
            for label in ('reference','current'):
                folder = build/'mapping/results'/('admission_'+label)
                module = json.loads((folder/'mapped.json').read_text())['modules']['admission_measure']
                flags = module['netnames']['flags_q']['bits']
                paths_by_input = {}
                for name in ('kernel_prefetch_idle','conv_task_idle','task_fault'):
                    bit = flags[CURRENT_FLAGS.index(name)]
                    paths = connected_paths(module,
                        root_filter=lambda _name, cell, _port, bit=bit:
                            bit in cell['connections'].get('Q',[]))
                    if not paths['graph_complete']:
                        raise RuntimeError('Admission mapping graph is incomplete')
                    paths_by_input[name] = paths
                summary = json.loads((folder/'summary.json').read_text())
                if not summary['functional_verification']['passed']:
                    raise RuntimeError('Admission mapping verification did not pass')
                mapping['results'][label] = {'metrics':json.loads((folder/'metrics.json').read_text()),
                    'input_to_output':paths_by_input,'mapped_sha256':digest(folder/'mapped.json'),
                    'functional_verification':summary['functional_verification']}

    revision = subprocess.run(['git','rev-parse','HEAD'], cwd=source_root, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    scope = {'rtl_revision':revision.stdout.strip() if revision.returncode == 0 else None,
        'admission_expression_sha256':hashlib.sha256(
            condition_module(current_admission((source_root/TOP).read_text(),'admission_logic')).encode()).hexdigest(),
        'scope':scope_name,
        'npu_top_sections':['task_accept_conditions 的组合表达式'],
        'complete_rtl_modules':(['frame_address_prepare','ps_window_scheduler','ps_scheduler_any',
                                'ps_scheduler_priority','onehot_check','unsigned_compare',
                                'parallel_prefix_add','regfile'] if complete else []),
        'admission_input_bits':len(CURRENT_FLAGS)+2,
        'admission_input_assumptions':[],
        'top_level_ready_register_included':False,
        'derived_output':'matrix_start_candidate = calc_start && task_accept_conditions && !cfg_vector_enable',
        'frame_address_comparison':('same current complete module; p_ready_mask_abort=1 compared with 0 and 1'
                                    if complete else None)}
    report = {'passed':True,'source_sha256':formal['source_sha256'],'validation_scope':scope,
              **results,'mapping':mapping,
              'scripts_sha256':{str(p.relative_to(ROOT)):digest(p) for p in Path(__file__).parent.glob('*.py')}}
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'passed':True,'scope':scope_name,'checks':list(results),
                      'mapping_executed':bool(mapping and mapping['executed'])}))


if __name__ == '__main__':
    main()
