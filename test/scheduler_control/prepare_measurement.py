#!/usr/bin/env python3
"""保存帧调度器完整模块的参考与当前综合输入。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-rev', default='e6fd2b1f')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    cases = {}
    hashes = {}
    relative = Path('rtl/npu/control/ps_window_scheduler.sv')
    for label in ('reference', 'current'):
        folder = out/label
        folder.mkdir(exist_ok=True)
        data = (subprocess.check_output(['git', 'show', f'{args.reference_rev}:{relative}'], cwd=ROOT)
                if label == 'reference' else (ROOT/relative).read_bytes())
        path = folder/relative.name
        path.write_bytes(data)
        hashes[label] = {str(relative): hashlib.sha256(data).hexdigest()}
        cases['scheduler_'+label] = {
            'top': 'ps_window_scheduler',
            'options': ['-D', 'SYNTHESIS=1', '-DXILINX_FPGA=1', '-GSIZE=16',
                        '-GFRAME_COUNT=16', '-GMAX_REUSE_TILES=32'],
            'parameters': {'SIZE': 16, 'FRAME_COUNT': 16, 'MAX_REUSE_TILES': 32},
            'sources': [str(path)],
            'configuration': '完整十六帧调度器，包含预测、命令与所有帧进度存储',
        }
    (out/'cases.json').write_text(json.dumps(cases, ensure_ascii=False, indent=2)+'\n')
    (out/'input_manifest.json').write_text(json.dumps(hashes, indent=2)+'\n')


if __name__ == '__main__':
    main()
