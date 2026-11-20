#!/usr/bin/env python3
"""证明 FIFO 空间预留比较在全部输入编码下等价。"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT/'build/fifo_watermark_formal')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources = [ROOT/'rtl/npu/writeback/vec_s8_to_fifo.sv', ROOT/'rtl/common/REGFILE.v',
               Path(__file__).with_name('watermark_formal.sv')]
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    results = []
    for banks in (1, 2, 3, 4, 5, 16, 31, 32, 64):
        script = out/f'banks{banks}.ys'
        script.write_text(f'read_slang --top fifo_watermark_formal -Gp_banks={banks} ' +
            ' '.join(shlex.quote(str(p)) for p in sources) + '\n' +
            'prep -top fifo_watermark_formal -flatten\n' +
            'sat -verify -prove equivalent 1 -show-inputs\n')
        with (out/f'banks{banks}.log').open('w') as log:
            subprocess.run([sys.executable, str(ROOT/'scripts/fpga/open_fpga_synth.py'),
                            '--worker', str(script)], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        results.append(dict(banks=banks, passed=True))
    if hashes != {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}:
        raise RuntimeError('Sources changed during verification')
    report = dict(passed=True, source_sha256=hashes, cases=results,
                  inputs='All 32-bit reservation values and all count/partial-write encodings; no assumptions')
    (out/'summary.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
