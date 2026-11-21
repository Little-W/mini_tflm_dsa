#!/usr/bin/env python3
"""保存 Softmax 完整模块的参考与当前综合输入。"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/conv/vector_softmax.sv')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--baseline-ref', default='aa0a169c')
    parser.add_argument('--reference-root', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out, root = args.out.resolve(), args.source_root.resolve()
    reference = ((args.reference_root / SOURCE).read_bytes() if args.reference_root else
                 subprocess.check_output(['git', 'show', f'{args.baseline_ref}:{SOURCE}'], cwd=ROOT))
    current = (root / SOURCE).read_bytes()
    cases = {}
    hashes = {}
    for label, data in (('reference', reference), ('current', current)):
        path = out / label / SOURCE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        hashes[label] = hashlib.sha256(data).hexdigest()
        parameters = dict(MAX_DEPTH=16, MULTIPLIER_LATENCY=2)
        cases[label] = dict(top='vector_softmax', sources=[str(path)], parameters=parameters,
            options=['-DSYNTHESIS=1', '-DXILINX_FPGA=1'] +
                [f'-G{name}={value}' for name, value in parameters.items()],
            configuration='完整 Softmax，16 元素与两级乘法结果等待')
    shutil.copytree(root / 'rtl/common', out / 'current/rtl/common', dirs_exist_ok=True)
    (out / 'cases.json').write_text(json.dumps(cases, ensure_ascii=False, indent=2) + '\n')
    (out / 'inputs.json').write_text(json.dumps(dict(source_sha256=hashes,
        reference_revision=str(args.reference_root or args.baseline_ref)), indent=2) + '\n')
    print(json.dumps(hashes))


if __name__ == '__main__':
    main()
