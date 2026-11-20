#!/usr/bin/env python3
"""比较生产参数下 INT16 输出队列的存储资源与组合路径。"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='8215cb95')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    cases = {}
    for variant in ('reference', 'current'):
        sources = []
        for name in ('vec_s8_to_fifo.sv', 'vec_s16_to_fifo.sv'):
            path = Path('rtl/npu/writeback') / name
            source = read_rtl_source(f'{args.reference}:{path}', cwd=ROOT) if variant == 'reference' else (ROOT / path).read_bytes()
            target = out / f'{variant}_{name}'
            target.write_bytes(source)
            sources.append(str(target))
        sources.append('rtl/common/regfile.v')
        cases[variant] = {
            'top': 'vec_s16_to_fifo', 'sources': sources,
            'options': ['-D', 'SYNTHESIS=1', '-D', 'XILINX_FPGA=1',
                        '-GVLEN=16', '-GBANKS=4', '-GBUS_WIDTH=64'],
            'configuration': '16 INT16 lanes, four banks, 64-bit bus',
        }
    config = out / 'cases.json'
    config.write_text(json.dumps(cases, indent=2) + '\n')
    subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                    '--case-config', str(config), '--cases', 'reference', 'current',
                    '--out', str(out / 'results')], cwd=ROOT, check=True)


if __name__ == '__main__':
    main()
