#!/usr/bin/env python3
"""按独立量化模块配置比较移位溢出检查的资源与组合深度。"""
import argparse
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
reference = out/'reference.sv'
reference.write_text(subprocess.check_output(['git', 'show',
    '548bda54:rtl/npu/writeback/requant_shift_pipeline.sv'], cwd=ROOT, text=True))
options = ['-DSYNTHESIS=1', '-DXILINX_FPGA=1', '-GBUS_WIDTH=64', '-GVLEN=16',
           '-GMAX_IA_REUSE=32', '-GENABLE_S16=1', '-Gp_compute_lanes=2',
           '-Gp_input_rows=512', '-Gp_parameter_output=0']
cases = {name: {'top': 'vec_requant', 'sources': [str(ROOT/'rtl/npu/writeback/vec_requant.sv'), str(source)],
               'options': options, 'configuration': '16通道、2个计算通道、512行缓冲、64位总线'}
         for name, source in [('reference', reference), ('candidate', ROOT/'rtl/npu/writeback/requant_shift_pipeline.sv')]}
configuration = out/'cases.json'
configuration.write_text(json.dumps(cases, indent=2)+'\n')
subprocess.run([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--case-config', configuration,
                '--cases', 'reference', 'candidate', '--out', out, '--through', 'pre_lut'], cwd=ROOT, check=True)
results = {}
for name in cases:
    target = out/(name+'_cost')
    subprocess.run([sys.executable, ROOT/'scripts/fpga/remap_fpga_luts.py', '--source', out/name,
                    '--out', target, '--mode', 'physical-cost', '--delay-target-ps', '6667',
                    '--wire-delay-ps', '300', '--max-lut-inputs', '8'], cwd=ROOT, check=True)
    data = json.loads((target/'metrics.json').read_text())
    results[name] = {'resources': data['resources'], 'paths': data['paths'],
                    'manifest': json.loads((target/'manifest.json').read_text()),
                    'verification': json.loads((target/'verification.json').read_text())}
(out/'summary.json').write_text(json.dumps({'production_options': options, 'results': results}, indent=2)+'\n')
