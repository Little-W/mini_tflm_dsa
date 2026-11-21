#!/usr/bin/env python3
"""验证真实仲裁器三位在途计数的全部状态和事件组合。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/dma/axi_block_dma_arbiter.sv')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--reference', default='dde5e7c9')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = (ROOT / SOURCE).read_text()
    reference = subprocess.check_output(['git', 'show', f'{args.reference}:{SOURCE}'], cwd=ROOT, text=True)
    first = current.index('    assign rd_pending_increment =')
    last = current.index('    always_ff @(posedge clk)', first)
    candidate = current[first:last]
    first = reference.index('            case ({rd_dma_start, rd_dma_done, rd_dma_cancel})')
    last = reference.index('            endcase', first) + len('            endcase')
    original = reference[first:last].replace('rd_pending_count_q <=', 'expected =')
    wrapper = out / 'count.sv'
    wrapper.write_text('''module count(input logic [2:0] rd_pending_count_q,
input logic rd_dma_start, rd_dma_done, rd_dma_cancel);
logic [2:0] rd_pending_count_next, expected;
logic rd_pending_increment, rd_pending_decrement, rd_pending_decrement_two;
''' + candidate + '''
always_comb begin
    expected = rd_pending_count_q;
''' + original + '''
    assert(rd_pending_count_next == expected);
end
endmodule
''')
    script, log = out / 'count.ys', out / 'count.log'
    script.write_text('read_slang --top count ' + shlex.quote(str(wrapper)) + '\n'
                     'prep -top count\nflatten\nchformal -lower\nopt -full\n'
                     'sat -verify -prove-asserts -show-inputs\n')
    with log.open('w') as stream:
        result = subprocess.run([sys.executable, ROOT / 'scripts/fpga/open_fpga_synth.py',
                                 '--worker', script], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
    passed = result.returncode == 0 and 'SAT proof finished - no model found: SUCCESS!' in log.read_text()
    if current != (ROOT / SOURCE).read_text():
        raise RuntimeError('验证期间仲裁器源码发生变化')
    report = dict(passed=passed, reference=args.reference, inputs_constrained=False,
                  input_bits=6, combinations=64,
                  source_sha256=hashlib.sha256(current.encode()).hexdigest(),
                  reference_sha256=hashlib.sha256(reference.encode()).hexdigest(),
                  wrapper_sha256=hashlib.sha256(wrapper.read_bytes()).hexdigest(),
                  log_sha256=hashlib.sha256(log.read_bytes()).hexdigest())
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    if not passed:
        raise RuntimeError(f'计数等价检查未完成：{log}')


if __name__ == '__main__':
    main()
