#!/usr/bin/env python3
"""证明实际帧容量模块与完整 64 位容量表达式对全部输入等价。"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCES = [ROOT / 'rtl/npu/ps_compact/ps_frame_store.sv',
           ROOT / 'rtl/common/regfile.v', ROOT / 'test/ps_raw_store/capacity.sv']
PROFILES = [(1, 1, 1), (1, 2, 2), (4, 4, 3), (10, 8, 3), (14, 10, 4),
            (12, 10, 4), (16, 12, 4), (8, 12, 5), (31, 10, 4),
            (32, 10, 4), (14, 30, 4), (34, 12, 4)]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--worker', type=Path)
    args = parser.parse_args()
    if args.worker:
        from pyosys import libyosys
        libyosys.run_pass('script ' + shlex.quote(str(args.worker)))
        return
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    summary = {'method': 'all-input combinational SAT',
               'source_sha256': {str(p.relative_to(ROOT)): digest(p) for p in SOURCES},
               'profiles': []}
    for initial_w, words_w, banks_w in PROFILES:
        folder = out / f'initial{initial_w}_words{words_w}_banks{banks_w}'
        folder.mkdir(exist_ok=True)
        script = folder / 'prove.ys'
        script.write_text('read_slang --top ps_frame_capacity_formal ' +
            f'-GINITIAL_W={initial_w} -GWORDS_W={words_w} -GBANKS_W={banks_w} ' +
            ' '.join(shlex.quote(str(p)) for p in SOURCES) + '\n' +
            'prep -top ps_frame_capacity_formal -flatten\n' +
            'opt -full\nsat -prove equivalent 1 -verify -show-inputs -show-outputs\n')
        with (folder / 'formal.log').open('w') as log:
            result = subprocess.run([sys.executable, str(Path(__file__).resolve()),
                '--out', str(out), '--worker', str(script)],
                cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        passed = result.returncode == 0 and 'SAT proof finished - no model found: SUCCESS' in (folder / 'formal.log').read_text()
        record = {'initial_row_width': initial_w, 'bank_words_width': words_w,
                  'bank_count_width': banks_w, 'frame_rows_width': 32,
                  'reserve_rows_width': 32, 'passed': passed}
        summary['profiles'].append(record)
        summary['passed'] = all(x['passed'] for x in summary['profiles'])
        (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
        print(json.dumps(record), flush=True)
        if not passed:
            raise SystemExit((folder / 'formal.log').read_text()[-6000:])
    assert summary['source_sha256'] == {str(p.relative_to(ROOT)): digest(p) for p in SOURCES}


if __name__ == '__main__':
    main()
