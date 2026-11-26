#!/usr/bin/env python3
"""使用生产 FPGA 编译条件比较双项缓冲的逻辑与分布式存储资源。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/soc/soc_axi_pingpong_chan.sv')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', default='ce47de48')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources = {
        'reference': subprocess.check_output(['git', 'show', f'{args.reference}:{SOURCE}'], cwd=ROOT),
        'current': (ROOT / SOURCE).read_bytes()}
    cases = {}
    for label, text in sources.items():
        path = out / (label + '.sv')
        path.write_bytes(text)
        for width in (2, 24, 35, 54, 64, 67, 73):
            cases[f'{label}_{width}'] = {
                'top': 'soc_axi_pingpong_chan', 'sources': [str(path)],
                'options': ['-DSYNTHESIS=1', '-DXILINX_FPGA=1', f'-GWIDTH={width}'],
                'configuration': {'WIDTH': width, 'fpga': True}}
    configuration = out / 'cases.json'
    configuration.write_text(json.dumps(cases, indent=2) + '\n')
    subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                    '--case-config', str(configuration), '--cases', *cases,
                    '--out', str(out / 'mapping')], cwd=ROOT, check=True)
    report = {'reference': args.reference,
        'source_sha256': {k: hashlib.sha256(v).hexdigest() for k, v in sources.items()},
        'mapping': {}}
    for name in cases:
        metrics = json.loads((out / 'mapping' / name / 'metrics.json').read_text())
        report['mapping'][name] = {
            'resources': metrics['resources'],
            'longest_register_path_cells': metrics['paths']['longest_register_path_cells'],
            'graph_complete': metrics['paths']['graph_complete']}
        if not metrics['paths']['graph_complete']:
            raise RuntimeError('连接图存在未分类单元或组合环')
    report['scope'] = '独立通道的完整映射资源，含分布式存储所需 LUT；布局后的资源数由器件实现报告确定。'
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    if sources['current'] != (ROOT / SOURCE).read_bytes():
        raise RuntimeError('测量期间源码发生变化')


if __name__ == '__main__':
    main()
