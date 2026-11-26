#!/usr/bin/env python3
"""保存部分和帧存储两版完整模块的相同参数测量输入。"""
import argparse
import hashlib
import json
from pathlib import Path
import runpy
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='8847f9ac')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    relative = 'rtl/npu/ps_compact/ps_frame_store.sv'
    resolve = runpy.run_path(str(ROOT / 'scripts/rtl/source_files.py'))['with_dependencies']
    parameters = dict(MAX_FRAME_ROWS=512, FRAME_COUNT=16, POOL_BYTES=49152,
                      BANK_BYTES=8192, EXTERNAL_RAM=1, p_fixed_ps_channels=1)
    cases, hashes = {}, {}
    for label in ('reference', 'current'):
        data = (subprocess.check_output(['git', 'show', f'{args.reference}:{relative}'], cwd=ROOT)
                if label == 'reference' else (ROOT / relative).read_bytes())
        source = out / (label + '.sv')
        source.write_bytes(data)
        files = resolve([source], ROOT)
        cases[label] = dict(top='ps_frame_store', sources=list(map(str, files)), parameters=parameters,
            options=['-DSYNTHESIS=1', '-DXILINX_FPGA=1'] + [f'-G{key}={value}' for key, value in parameters.items()],
            configuration='完整固定通道部分和帧存储，16 帧，每帧最多 512 行')
        hashes[label] = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    (out / 'cases.json').write_text(json.dumps(cases, ensure_ascii=False, indent=2) + '\n')
    (out / 'manifest.json').write_text(json.dumps(hashes, indent=2) + '\n')


if __name__ == '__main__':
    main()
