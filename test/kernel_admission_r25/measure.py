#!/usr/bin/env python3
"""测量实际核请求、仲裁、空闲、AXIL 开始与顶层接收组合。"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from model import ROOT, REFERENCE, SOURCES, KERNEL_FLAGS, TOP_FLAGS, OUTPUTS, digest, source, wrapper
from run_formal import run

sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from netlist_metrics import connected_paths, register_origins


def execute(folder, name, arguments):
    log = folder / (name + '.log')
    with log.open('w') as stream:
        subprocess.run([sys.executable, *arguments], cwd=ROOT, stdout=stream,
                       stderr=subprocess.STDOUT, check=True, timeout=300)
    return digest(log)


def source_match(cell, key):
    origin = cell.get('attributes', {}).get('fpga_register_origin', '')
    if key == 'all_sources':
        return True
    if key.startswith('prefetch_state['):
        return origin == 'prefetch_state [' + key.split('[',1)[1]
    return origin == key or origin.startswith(key + ' [')


def measure_one(folder, pre):
    data = json.loads((folder / 'mapped.json').read_text())['modules']['measurement_top']
    for name, origin in register_origins(pre).items():
        if name in data['cells']:
            data['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = origin
    summary = json.loads((folder / 'summary.json').read_text())
    result = {'resources': summary['resources'], 'mapping': summary['lut_mapping'],
              'functional_verification': summary['functional_verification'],
              'mapped_sha256': digest(folder / 'mapped.json'), 'pre_lut_sha256': digest(pre),
              'all_paths': connected_paths(data, limit=3, group_limit=10), 'paths': {}}
    assert result['functional_verification']['passed']
    assert result['all_paths']['graph_complete']
    sources = ('prefetch_state', 'prefetch_state[0]', 'prefetch_state[1]', *KERNEL_FLAGS,
               'response_slots_active', 'prefetch_rows', 'prefetch_valid_cols',
               'abort', 'rd_grant_client', 'rd_dma_start_q', *TOP_FLAGS,
               'npu_start_pending_q', 'npu_start_warmup_q', 'calc_start_pulse', 'cfg_conv_enable',
               'all_sources')
    targets = ('sa_ready', 'cfg_start_event', 'vector_start', 'load_weight_req', 'kernel_prefetch_idle')
    for key in sources:
        result['paths'][key] = {}
        for endpoint in targets:
            row = connected_paths(data, limit=1, group_limit=0,
                root_filter=lambda name, cell, port, key=key: source_match(cell, key),
                sink_filter=lambda name, cell, port, endpoint=endpoint: source_match(cell, 'o_'+endpoint))
            assert row['graph_complete']
            result['paths'][key][endpoint] = {
                'connected': bool(row['register_to_register_paths']),
                'levels': row['longest_register_path_cells'],
                'path': row['register_to_register_paths'][:1]}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--formal', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--lock-file', type=Path, required=True)
    args = parser.parse_args()
    formal, folder = args.formal.resolve(), args.out.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    proof = json.loads((formal / 'summary.json').read_text())
    assert proof['passed']
    assert proof['source_sha256']['current'] == {str(p): digest(ROOT/p) for p in SOURCES}
    cases = {}
    for label in ('reference', 'current'):
        current = folder / label
        current.mkdir(exist_ok=True)
        unit = current / 'admission.sv'
        unit.write_bytes((formal / (label + '.sv')).read_bytes())
        ports = current / 'ports.json'
        run(current, 'elaborate', [f'read_slang -DSYNTHESIS=1 -DXILINX_FPGA=1 --top admission_connected {unit} {formal/"models.sv"}',
            'prep -top admission_connected', 'check -assert', f'write_json {ports}'], 'Executing JSON backend.')
        top = current / 'measurement.sv'
        top.write_text(wrapper(json.loads(ports.read_text())['modules']['admission_connected']['ports']))
        cases[label] = {'top': 'measurement_top', 'sources': [str(unit), str(top)],
                        'options': ['-DSYNTHESIS=1','-DXILINX_FPGA=1'],
                        'configuration': '实际核请求、后台空闲、仲裁授予、AXIL 开始与顶层接收表达式'}
    case_path = folder / 'cases.json'
    case_path.write_text(json.dumps(cases, ensure_ascii=False, indent=2)+'\n')
    logs = {}
    logs['pre_lut'] = execute(folder, 'pre_lut', [str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
        '--case-config', str(case_path), '--cases', 'reference', 'current',
        '--out', str(folder / 'pre'), '--through', 'pre_lut', '--lock-file', str(args.lock_file)])
    results = {}
    for label in cases:
        logs[label] = execute(folder, label + '_map', [str(ROOT / 'scripts/fpga/remap_fpga_luts.py'),
            '--source', str(folder / 'pre' / label), '--out', str(folder / 'mapped' / label),
            '--mode', 'physical-cost', '--delay-target-ps', '6667', '--wire-delay-ps', '500',
            '--max-lut-inputs', '6', '--lock-file', str(args.lock_file)])
        results[label] = measure_one(folder / 'mapped' / label, folder / 'pre' / label / 'pre_lut.il')
        print(label, json.dumps({'lut': results[label]['resources']['logic_lut_cells'],
              'maximum': results[label]['all_paths']['longest_register_path_cells'],
              'prefetch_state': {key: x['levels'] for key, x in results[label]['paths']['prefetch_state'].items()}},ensure_ascii=False),flush=True)
    assert proof['source_sha256']['current'] == {str(p): digest(ROOT/p) for p in SOURCES}
    report = {'passed': True, 'reference_commit': REFERENCE, 'source_sha256': proof['source_sha256'],
              'formal_summary_sha256': digest(formal / 'summary.json'), 'results': results,
              'logs_sha256': logs, 'script_sha256': digest(Path(__file__)),
              'scope': '全部核请求与后台空闲实际组合表达式，实际仲裁授予、AXIL 时钟门控开始、顶层就绪/配置开始及向量开始。其余模块状态为任意寄存输入。'}
    (folder / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(folder / 'summary.json', flush=True)


if __name__ == '__main__':
    main()
