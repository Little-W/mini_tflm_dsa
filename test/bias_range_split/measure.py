#!/usr/bin/env python3
"""以相同生产参数测量完整偏置加载模块的资源和最长组合路径。"""
import argparse
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
relative = 'rtl/npu/loaders/bias_request_end_compare.sv'
reference = out / 'reference.sv'
reference.write_text(subprocess.check_output(['git', 'show', 'c42f5ff9:' + relative], cwd=ROOT, text=True))
options = ['-DSYNTHESIS=1', '-DXILINX_FPGA=1', '-GSIZE=16', '-GBUS_WIDTH=64',
           '-GDATA_WIDTH=32', '-GREG_WIDTH=32', '-GCOUNT_WIDTH=29', '-GGROUP_BLOCKS_MAX=16']
cases = {name: {'top': 'bias_loader', 'sources': [str(ROOT / 'rtl/npu/loaders/bias_loader.sv'), str(source)],
                'options': options, 'configuration': '16 通道、32 位偏置、29 位计数、16 块分组'}
         for name, source in [('reference', reference), ('candidate', ROOT / relative)]}
configuration = out / 'cases.json'
configuration.write_text(json.dumps(cases, indent=2) + '\n')
subprocess.run([sys.executable, ROOT / 'scripts/fpga/open_fpga_synth.py', '--case-config', configuration,
                '--cases', 'reference', 'candidate', '--out', out, '--through', 'pre_lut'], cwd=ROOT, check=True)
results = {}
for name in cases:
    target = out / (name + '_cost')
    subprocess.run([sys.executable, ROOT / 'scripts/fpga/remap_fpga_luts.py', '--source', out / name,
                    '--out', target, '--mode', 'physical-cost', '--delay-target-ps', '6667',
                    '--wire-delay-ps', '300', '--max-lut-inputs', '8'], cwd=ROOT, check=True)
    data = json.loads((target / 'metrics.json').read_text())
    results[name] = {'resources': data['resources'],
                     'longest_register_path_cells': data['paths']['longest_register_path_cells'],
                     'critical_register_path': data['paths']['register_to_register_paths'][0],
                     'manifest': json.loads((out / name / 'manifest.json').read_text()),
                     'full_metrics_sha256': hashlib.sha256((target / 'metrics.json').read_bytes()).hexdigest()}
(out / 'summary.json').write_text(json.dumps({'production_options': options, 'results': results}, indent=2) + '\n')
