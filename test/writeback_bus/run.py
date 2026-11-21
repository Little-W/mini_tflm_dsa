#!/usr/bin/env python3
"""Verify 32/64-bit output FIFOs with exact byte masks and backpressure."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source


ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--bus-width', type=int, choices=(32, 64), required=True)
    parser.add_argument('--verilator', default='verilator')
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--reference', help='Compare every output cycle with this git revision')
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    sources = [ROOT/'rtl/npu/writeback/vec_s8_to_fifo.sv',
               ROOT/'rtl/common/regfile.v',
               ROOT/'rtl/common/parallel_prefix_add.sv',
               ROOT/'rtl/npu/writeback/vec_s16_to_fifo.sv',
               Path(__file__).with_name('tb_writeback_bus.sv')]
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sources}
    reference_hashes = {}
    reference_sources = []
    if args.reference:
        for filename in ('vec_s8_to_fifo.sv', 'vec_s16_to_fifo.sv'):
            original = read_rtl_source(f'{args.reference}:rtl/npu/writeback/{filename}', cwd=ROOT, text=True)
            renamed = original.replace('vec_s8_to_fifo', 'vec_s8_to_fifo_ref').replace(
                'vec_s16_to_fifo', 'vec_s16_to_fifo_ref').replace('vec_s8_fifo_row_ram', 'vec_s8_fifo_row_ram_ref').replace(
                'fifo_bank_watermark', 'fifo_bank_watermark_ref')
            reference = args.out/(filename.removesuffix('.sv')+'_ref.sv')
            reference.write_text(renamed)
            reference_sources.append(reference)
            reference_hashes[filename] = hashlib.sha256(original.encode()).hexdigest()
    command = [args.verilator, '--binary', '--timing', '--assert', '-Wno-fatal',
               '--top-module', 'tb_writeback_bus', f'-DTB_BUS_WIDTH={args.bus_width}',
               '--Mdir', str(args.out/'obj'), '-j', str(args.jobs), *map(str, sources), *map(str, reference_sources)]
    if args.reference:
        command.append('-DWRITEBACK_COMPARE_REFERENCE')
    with (args.out/'build.log').open('w') as log:
        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
    binary = args.out/'obj/Vtb_writeback_bus'
    run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=120)
    (args.out/'run.log').write_text(run.stdout+run.stderr)
    match = re.search(r'WRITEBACK_BUS_PASS bus_width=(\d+) cases=(\d+) checked_bytes=(\d+)', run.stdout)
    result = dict(passed=run.returncode == 0 and match is not None,
                  bus_width=args.bus_width, returncode=run.returncode,
                  command=command, source_sha256=hashes, reference=args.reference, reference_sha256=reference_hashes,
                  sources_unchanged=all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest() == h
                                        for p, h in hashes.items()))
    if match:
        result.update(cases=int(match[2]), checked_bytes=int(match[3]))
    result['passed'] &= result['sources_unchanged']
    (args.out/'result.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))
    if not result['passed']:
        raise RuntimeError(run.stdout+run.stderr)


if __name__ == '__main__':
    main()
