#!/usr/bin/env python3
"""证明写回行分块寄存与截断乘积非零判断的完整输入关系。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]
OA = Path('rtl/npu/writeback/oa_writer.sv')
FIFO = Path('rtl/npu/writeback/vec_s8_to_fifo.sv')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(folder, name, commands):
    script, log = folder / (name + '.ys'), folder / (name + '.log')
    script.write_text('\n'.join(commands) + '\n')
    with log.open('w') as stream:
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                 '--worker', str(script)], cwd=ROOT, stdout=stream,
                                stderr=subprocess.STDOUT, timeout=180)
    if result.returncode or 'SUCCESS' not in log.read_text():
        raise RuntimeError(log.read_text()[-8000:])
    return {'passed': True, 'log_sha256': digest(log)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='9bb1e28a')
    parser.add_argument('--writer-profiles', nargs='+', default=['4:32:8', '8:64:8', '16:32:16',
        '16:64:16', '16:64:28', '16:64:29', '16:64:32', '32:64:32'])
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    old = read_rtl_source(f'{args.reference}:{OA}', cwd=ROOT, text=True)
    summary = {'passed': False, 'reference': args.reference,
               'source_sha256': {str(p): digest(ROOT / p) for p in [OA, FIFO]},
               'writer_reference_sha256': hashlib.sha256(old.encode()).hexdigest(),
               'writer': [], 'truncated_product': []}
    # 写回几何证明覆盖公开输出、行组生效值和准备周期内的状态关系。
    writer_out = out / 'writer'
    subprocess.run([sys.executable, str(ROOT / 'test/oa_writer_geometry/run_formal.py'),
                    '--reference', args.reference, '--out', str(writer_out), '--synthesis',
                    '--profiles', *args.writer_profiles], cwd=ROOT, check=True)
    writer_report = json.loads((writer_out / 'summary.json').read_text())
    if not writer_report['passed']:
        raise RuntimeError('写回器形式证明未通过')
    summary['writer'] = writer_report['profiles']
    summary['writer_report_sha256'] = digest(writer_out / 'summary.json')
    text = (ROOT / FIFO).read_text()
    start = text.index('  wire [BANK_COUNT_WIDTH-1:0] co_tiles =')
    end = text.index('  wire co_start =', start)
    fragment = text[start:end]
    helper = out / 'truncated_product.sv'
    helper.write_text('module truncated_product #(parameter BANK_COUNT_WIDTH=1) (\n'
                      'input [31:0] coalesce_rows, coalesce_cols, output equivalent);\n' +
                      fragment + '\nassign equivalent = (|co_nonzero_terms) == (co_tiles != 0);\nendmodule\n')
    for width in range(1, 13):
        item = {'retained_product_bits': width, 'arbitrary_input_bits': 64,
                **run(out, f'product_w{width}', [
                    f'read_slang --top truncated_product -GBANK_COUNT_WIDTH={width} ' +
                    shlex.quote(str(helper)), 'prep -top truncated_product -flatten',
                    'sat -verify -set-def-inputs -prove equivalent 1 -show-inputs'])}
        summary['truncated_product'].append(item)
        print(json.dumps(item), flush=True)
    if summary['source_sha256'] != {str(p): digest(ROOT / p) for p in [OA, FIFO]}:
        raise RuntimeError('The production sources changed during proof')
    summary['passed'] = True
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')


if __name__ == '__main__':
    main()
