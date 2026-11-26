#!/usr/bin/env python3
"""测量完整生产参数的输出写回模块。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = 'rtl/npu/writeback/oa_writer.sv'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='edbef90e')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    (out/'reference.sv').write_bytes(subprocess.check_output(['git', 'show', args.reference+':'+SOURCE], cwd=ROOT))
    (out/'current.sv').write_bytes((ROOT/SOURCE).read_bytes())
    cases = {name: {'top': 'oa_writer', 'sources': [str(out/(name+'.sv'))],
        'options': ['-DSYNTHESIS=1', '-DXILINX_FPGA=1', '-GVLEN=16', '-GBUS_WIDTH=64', '-GCOUNT_WIDTH=29'],
        'configuration': '完整生产参数的输出写回控制'} for name in ('reference', 'current')}
    config = out/'cases.json'
    config.write_text(json.dumps(cases, indent=2)+'\n')
    subprocess.run([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py',
        '--case-config', config, '--cases', *cases, '--out', out/'mapping',
        '--through', 'pre_lut'], check=True, cwd=ROOT)
    records = {}
    for name in cases:
        source, cost = out/'mapping'/name, out/'cost'/name
        subprocess.run([sys.executable, ROOT/'scripts/fpga/remap_fpga_luts.py',
            '--source', source, '--out', cost, '--mode', 'physical-cost',
            '--delay-target-ps', '6667', '--wire-delay-ps', '300', '--max-lut-inputs', '8'], check=True, cwd=ROOT)
        records[name] = {key: json.loads((cost/(key+'.json')).read_text())
                        for key in ('manifest', 'summary', 'metrics')}
    (out/'measurement.json').write_text(json.dumps({'cases': records}, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    main()
