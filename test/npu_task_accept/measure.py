#!/usr/bin/env python3
"""测量实际任务接收控制上下文并检查向量运行到启动信号的组合连接。"""
import argparse
from context import context
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--out', type=Path, required=True)
args = parser.parse_args()
out = args.out.resolve()
out.mkdir(parents=True, exist_ok=True)
extraction = context(out / 'context')
cases = {name: {'top': 'task_accept_property',
                'sources': [str(out / 'context' / (name + '.sv')), str(ROOT / 'rtl/npu/top/npu_task_accept_qualify.sv')],
                'options': ['-DSYNTHESIS=1', '-DXILINX_FPGA=1'],
                'configuration': '实际任务接收状态及全部自由组合输入'}
         for name in ('reference', 'candidate')}
configuration = out / 'cases.json'
configuration.write_text(json.dumps(cases, indent=2) + '\n')
subprocess.run([sys.executable, ROOT / 'scripts/fpga/open_fpga_synth.py', '--case-config', configuration,
                '--cases', 'reference', 'candidate', '--out', out, '--through', 'pre_lut'], cwd=ROOT, check=True)


def has_combinational_path(module, source, target):
    """从起点遍历组合输入到输出连接，时序单元不参与传播。"""
    pending = list(module['ports'][source]['bits'])
    seen = set(pending)
    endpoints = set(module['ports'][target]['bits'])
    for bit in pending:
        for cell in module['cells'].values():
            if cell['type'].startswith(('FD', 'RAM', 'SRL')):
                continue
            inputs = [value for port, values in cell['connections'].items()
                      if cell['port_directions'][port] == 'input' for value in values]
            if bit not in inputs:
                continue
            for port, values in cell['connections'].items():
                if cell['port_directions'][port] == 'output':
                    for value in values:
                        if value not in seen:
                            seen.add(value)
                            pending.append(value)
    return bool(endpoints & seen)


results = {}
for name in cases:
    target = out / (name + '_cost')
    subprocess.run([sys.executable, ROOT / 'scripts/fpga/remap_fpga_luts.py', '--source', out / name,
                    '--out', target, '--mode', 'physical-cost', '--delay-target-ps', '6667',
                    '--wire-delay-ps', '300', '--max-lut-inputs', '8'], cwd=ROOT, check=True)
    data = json.loads((target / 'metrics.json').read_text())
    module = json.loads((target / 'mapped.json').read_text())['modules']['task_accept_property']
    results[name] = {'resources': data['resources'],
                     'longest_register_path_cells': data['paths']['longest_register_path_cells'],
                     'run_vector_to_vector_start': has_combinational_path(module, 'run_vector', 'vector_start_fire'),
                     'manifest': json.loads((out / name / 'manifest.json').read_text()),
                     'full_metrics_sha256': hashlib.sha256((target / 'metrics.json').read_bytes()).hexdigest()}
assert results['reference']['run_vector_to_vector_start']
assert not results['candidate']['run_vector_to_vector_start']
(out / 'summary.json').write_text(json.dumps({'results': results, 'extraction': extraction}, indent=2) + '\n')
