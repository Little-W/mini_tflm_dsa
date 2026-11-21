#!/usr/bin/env python3
"""汇总共享存储访问控制的形式检查、功能结果和连接路径测量。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

from run_formal import ROOT, SOURCE

sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from netlist_metrics import connected_paths, register_origins

TOP = 'rtl/npu/top/npu_top.sv'


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    value = json.loads(path.read_text())
    if value.get('passed') is False:
        raise RuntimeError(f'检查未通过: {path}')
    return value


def timing(folder: Path) -> dict:
    metrics = read(folder / 'metrics.json')
    module = read(folder / 'mapped.json')['modules']['measurement_top']
    for name, origin in register_origins(folder / 'pre_lut.il').items():
        if name in module['cells']:
            module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = origin
    def source_match(name, cell, port):
        return cell.get('attributes', {}).get('fpga_register_origin') == 'i_access_enable'
    selections = {
        'all_endpoints': lambda n, c, p: True,
        'capacity_fault': lambda n, c, p:
            'o_capacity_fault' in c.get('attributes', {}).get('fpga_register_origin', ''),
        'memory_write_enable': lambda n, c, p:
            c['type'].startswith('RAMB') and p in ('WEA', 'WEBWE', 'ENAWREN', 'ENBWREN'),
    }
    paths = {}
    for label, sink in selections.items():
        result = connected_paths(module, limit=1, group_limit=0,
                                 root_filter=source_match, sink_filter=sink)
        if not result['graph_complete'] or not result['register_to_register_paths']:
            raise RuntimeError(f'缺少完整路径: {folder}/{label}')
        paths[label] = {'combinational_cells': result['longest_register_path_cells'],
                        'path': result['register_to_register_paths'][0]}
    fields = ('logic_lut_cells', 'flip_flops', 'ramb36e1', 'ramb18e1', 'dsp48e1', 'carry4')
    return {'resources': {key: metrics['resources'][key] for key in fields},
            'longest_register_path_cells': metrics['paths']['longest_register_path_cells'],
            'access_enable_paths': paths,
            'mapped_sha256': digest(folder / 'mapped.json'),
            'pre_lut_sha256': digest(folder / 'pre_lut.il')}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--formal', type=Path, required=True)
    parser.add_argument('--memory', type=Path, required=True)
    parser.add_argument('--measurement', type=Path, required=True)
    parser.add_argument('--fpga', type=Path, required=True)
    parser.add_argument('--cosim', type=Path, nargs='+', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    expected = {name: digest(ROOT / name) for name in (SOURCE, TOP)}
    formal, memory = read(args.formal / 'summary.json'), read(args.memory / 'summary.json')
    inputs = read(args.measurement / 'inputs.json')
    fpga = read(args.fpga / 'summary.json')
    fpga_build = read(args.fpga / 'npu/s16/build.json')
    for report in (formal, memory, inputs, fpga_build):
        for name, sha in expected.items():
            if name in report['source_sha256'] and report['source_sha256'][name] != sha:
                raise RuntimeError(f'源码与验证记录不一致: {name}')
    cosim = []
    for folder in args.cosim:
        report = read(folder / 'summary.json')
        for name, sha in expected.items():
            if report['source_sha256'][name] != sha:
                raise RuntimeError(f'协同仿真源码不一致: {name}')
        runs = []
        for run in report['runs']:
            marker = next(line for line in run['case_lines']
                          if line.startswith('VECTOR_ENGINE_C_RTL_COSIM_PASS'))
            counts = {name: int(value) for name, value in re.findall(r'(\w+)=(\d+)', marker)}
            runs.append({'name': run['name'], 'passed': run['passed'], **counts})
        cosim.append({'target': report['implementation_target'], 'runs': runs,
                      'report_sha256': digest(folder / 'summary.json')})
    report = {
        'passed': True,
        'source_sha256': expected,
        'reference_revision': inputs['reference_revision'],
        'formal': {'cases': len(formal['cases']), 'input_constraints': formal['input_constraints'],
                   'scope': formal['scope'], 'report_sha256': digest(args.formal / 'summary.json')},
        'memory': {'profiles': memory['profiles'],
                   'cycles': sum(row['cycles'] for row in memory['profiles']),
                   'checked_bytes': sum(row['checked_bytes'] for row in memory['profiles']),
                   'report_sha256': digest(args.memory / 'summary.json')},
        'fpga_integration': {'tasks': fpga['tasks'], 'int32_checks': fpga['int32_checks'],
                             'source_manifest_sha256': digest(args.fpga / 'npu/s16/build.json'),
                             'report_sha256': digest(args.fpga / 'summary.json')},
        'vector_cosim': cosim,
        'measurement': {label: timing(args.measurement / 'synthesis' / label)
                        for label in ('reference', 'current')},
        'measurement_scope': '共享存储模块及同样的输入输出测量寄存器；访问使能前移与末级控制使用同一接口',
        'physical_timing_measured': False,
        'runner_sha256': digest(Path(__file__)),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'passed': True, 'formal_cases': report['formal']['cases'],
                      'memory_cycles': report['memory']['cycles'],
                      'vector_targets': [item['target'] for item in cosim]}))


if __name__ == '__main__':
    main()
