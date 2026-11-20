#!/usr/bin/env python3
"""核对受测源码，汇总配置接收和完整帧地址参数的实际检查结果。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from run_formal import ROOT, TOP, CURRENT_FLAGS, current_admission, digest
sys.path.insert(0, str(ROOT/'scripts/fpga'))
from netlist_metrics import connected_paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    args = parser.parse_args()
    build, source_root = args.build.resolve(), args.source_root.resolve()

    def read(name):
        return json.loads((build/name).read_text())

    formal = read('verified_formal/summary.json')
    if not formal['passed']:
        raise RuntimeError('The complete formal checks must pass')
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

    mapping = None
    if (build/'mapping/manifest.json').exists():
        manifest = read('mapping/manifest.json')
        if manifest['source_sha256'][str(TOP)] != digest(source_root/TOP):
            raise RuntimeError('Mapped admission source differs from the formal source')
        for name, expected in manifest['source_files_sha256'].items():
            if digest(build/'mapping'/name) != expected:
                raise RuntimeError(f'Mapping source changed: {name}')
        mapping = {}
        for label in ('reference','current'):
            folder = build/'mapping/results'/('admission_'+label)
            module = json.loads((folder/'mapped.json').read_text())['modules']['admission_measure']
            bit = module['netnames']['flags_q']['bits'][CURRENT_FLAGS.index('kernel_loader_o_quiescent')]
            paths = connected_paths(module,
                root_filter=lambda _name, cell, _port: bit in cell['connections'].get('Q',[]))
            if not paths['graph_complete']:
                raise RuntimeError('Admission mapping graph is incomplete')
            summary = json.loads((folder/'summary.json').read_text())
            if not summary['functional_verification']['passed']:
                raise RuntimeError('Admission mapping verification did not pass')
            mapping[label] = {'metrics':json.loads((folder/'metrics.json').read_text()),
                'kernel_quiescent_to_output':paths,'mapped_sha256':digest(folder/'mapped.json'),
                'functional_verification':summary['functional_verification']}

    scope = {'rtl_revision':subprocess.check_output(['git','rev-parse','HEAD'],cwd=source_root,text=True).strip(),
        'admission_expression_sha256':hashlib.sha256(
            current_admission((source_root/TOP).read_text(),'admission_logic').encode()).hexdigest(),
        'npu_top_sections':['配置接收表达式','帧命令接受与地址中止表达式'],
        'complete_rtl_modules':['frame_address_prepare','ps_window_scheduler','onehot_check',
                                'parallel_prefix_add','regfile'],
        'admission_input_bits':len(CURRENT_FLAGS)+2,
        'admission_input_assumptions':[],
        'frame_address_comparison':'same current complete module; p_ready_mask_abort=1 compared with 0 and 1'}
    report = {'passed':True,'source_sha256':formal['source_sha256'],'validation_scope':scope,
              **results,'mapping':mapping,
              'scripts_sha256':{str(p.relative_to(ROOT)):digest(p) for p in Path(__file__).parent.glob('*.py')}}
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'passed':True,'checks':list(results),'mapping':mapping is not None}))


if __name__ == '__main__':
    main()
