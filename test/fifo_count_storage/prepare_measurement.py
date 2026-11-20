#!/usr/bin/env python3
"""准备32个银行的完整FIFO与生产输出写回控制的联合综合。"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='cc0d4f69')
    args = parser.parse_args()
    out = args.out.resolve()
    subprocess.run([sys.executable, str(ROOT / 'test/fifo_bank_depth/prepare_measurement.py'),
                    '--reference', args.reference, '--out', str(out)], cwd=ROOT, check=True)
    config = out / 'cases.json'
    cases = json.loads(config.read_text())
    for case in cases.values():
        case['options'] = ['-D', 'XILINX_FPGA=1', '-GVLEN=16', '-GBUS_WIDTH=64', '-GCOUNT_WIDTH=29']
        case['sources'].append('rtl/npu/writeback/vec_s16_to_fifo.sv')
    config.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
