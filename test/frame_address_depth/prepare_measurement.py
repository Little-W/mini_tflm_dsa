#!/usr/bin/env python3
"""Save complete frame address implementations for ordinary RTL synthesis."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/top/frame_address_prepare.sv')
HELPER = Path('rtl/common/parallel_prefix_add.sv')
REFERENCE = '2297cb12deac56b476f9a2a656da4038a9d8a75c'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default=REFERENCE)
    args = parser.parse_args()
    out = args.out.resolve()
    cases, hashes = {}, {}
    for label in ('reference', 'candidate'):
        data = (subprocess.check_output(['git', 'show', f'{args.reference}:{SOURCE}'], cwd=ROOT)
                if label == 'reference' else (ROOT / SOURCE).read_bytes())
        path = out / label / SOURCE.name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        hashes[label] = hashlib.sha256(data).hexdigest()
        cases[label] = dict(top='frame_address_prepare', options=['-D', 'SYNTHESIS=1'],
                            sources=[str(path), str(HELPER)],
                            configuration='Complete frame address unit, tile16, one registered DSP48E1')
    (out / 'cases.json').write_text(json.dumps(cases, indent=2) + '\n')
    report = dict(reference=args.reference, source_sha256=hashes,
                  helper_sha256=hashlib.sha256((ROOT / HELPER).read_bytes()).hexdigest())
    (out / 'manifest.json').write_text(json.dumps(report, indent=2) + '\n')
    print(out / 'cases.json')


if __name__ == '__main__':
    main()
