#!/usr/bin/env python3
"""保存输出写回与含两项输出寄存的完整 FIFO 联合综合输入。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='eaba7635')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    wrapper_text = (ROOT / 'test/oa_fifo_timing/oa_fifo_timing_top.sv').read_text()
    assert wrapper_text.count('vec_s8_to_fifo_full #(') == 1
    assert wrapper_text.count('.start_permitted(start_permitted)') == 1
    wrapper_text = wrapper_text.replace('oa_fifo_timing_top', 'fifo_bank_timing_top')
    wrapper_text = wrapper_text.replace('    input logic start_permitted,\n', '')
    wrapper_text = wrapper_text.replace('vec_s8_to_fifo_full #(', 'vec_s8_to_fifo #(')
    wrapper_text = wrapper_text.replace('.rst_n(rst_n), .start_permitted(start_permitted),', '.rst_n(rst_n),')
    wrapper = out / 'fifo_bank_timing_top.sv'
    wrapper.write_text(wrapper_text)
    cases, hashes = {}, {}
    for label in ('reference', 'current'):
        sources = [wrapper]
        for relative in ('rtl/npu/writeback/oa_writer.sv', 'rtl/npu/writeback/vec_s8_to_fifo.sv'):
            path = out / (label + '_' + Path(relative).name)
            content = subprocess.check_output(['git', 'show', args.reference + ':' + relative], cwd=ROOT) \
                if label == 'reference' else (ROOT / relative).read_bytes()
            path.write_bytes(content)
            sources.append(path)
        hashes[label] = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
        cases[label] = {'top': 'fifo_bank_timing_top',
                        'options': ['-GVLEN=16', '-GBUS_WIDTH=64', '-GCOUNT_WIDTH=28'],
                        'sources': list(map(str, sources)),
                        'configuration': '完整输出写回与32个银行的循环INT8 FIFO，包含两项输出寄存'}
    (out / 'cases.json').write_text(json.dumps(cases, indent=2) + '\n')
    (out / 'manifest.json').write_text(json.dumps({'reference': args.reference, 'sources_sha256': hashes}, indent=2) + '\n')


if __name__ == '__main__':
    main()
