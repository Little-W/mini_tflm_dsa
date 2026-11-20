#!/usr/bin/env python3
"""保存帧调度器的完整普通 RTL 对照和生产参数。"""
import argparse
import hashlib
import json
from pathlib import Path
from prove import ROOT, SOURCE, HELPERS, REFERENCE, digest, read_rtl_source

PARAMETERS = {'SIZE': 16, 'FRAME_COUNT': 16, 'MAX_REUSE_TILES': 32}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default=REFERENCE)
    args = parser.parse_args()
    out = args.out.resolve()
    original = read_rtl_source(f'{args.reference}:{SOURCE}', cwd=ROOT, text=True)
    current = (ROOT / SOURCE).read_text()
    cases, records = {}, {}
    for label, text in [('reference', original), ('current', current)]:
        path = out / label / SOURCE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        records[label + '_sha256'] = hashlib.sha256(text.encode()).hexdigest()
        cases[label] = {'top': 'ps_window_scheduler', 'parameters': PARAMETERS,
                        'options': ['-D', 'SYNTHESIS=1', '-D', 'XILINX_FPGA=1'] +
                                   [f'-G{k}={v}' for k, v in PARAMETERS.items()],
                        'sources': [str(path)],
                        'configuration': '完整帧调度器，生产帧容量与行复用上限'}
    (out / 'cases.json').write_text(json.dumps(cases, indent=2, ensure_ascii=False) + '\n')
    report = {'source': SOURCE, 'reference_commit': args.reference,
              'parameters': PARAMETERS, **records,
              'helper_sha256': {name: digest(ROOT / name) for name in HELPERS},
              'regfile_sha256': digest(ROOT / 'rtl/common/regfile.v')}
    (out / 'inputs.json').write_text(json.dumps(report, indent=2) + '\n')
    print(out / 'cases.json')


if __name__ == '__main__':
    main()
