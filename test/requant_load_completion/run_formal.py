#!/usr/bin/env python3
"""证明实际装载末拍比较对全部三十二位计数、偏移和步长成立。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
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
    source = ROOT / 'rtl/npu/writeback/vec_requant.sv'
    text = source.read_text()
    names = ('remaining_words', 'load_advance', 'load_remainder_greater', 'load_has_more')
    assignments = [re.search(r'\bassign\s+' + name + r'\s*=.*?;', text, re.S)[0] for name in names]
    wrapper = out / 'load_completion.sv'
    wrapper.write_text('''module load_completion(
input logic [31:0] quant_need_load_r, load_offset, beats_expect
);
localparam int REG_WIDTH = 32;
logic [32:0] remaining_words, load_advance;
logic load_remainder_greater, load_has_more;
logic [31:0] next_offset;
logic expected_more;
assign next_offset = load_offset + beats_expect;
assign expected_more = next_offset < quant_need_load_r;
''' + '\n'.join(assignments) + '''
always_comb begin
    assert(load_has_more == expected_more);
end
endmodule
''')
    script = out / 'compare.ys'
    script.write_text('read_verilog -formal -sv ' + shlex.quote(str(wrapper)) + '\n'
                      'prep -top load_completion\nflatten\nchformal -lower\nopt -full\n'
                      'sat -verify -prove-asserts -show-inputs\n')
    log = out / 'compare.log'
    with log.open('w') as stream:
        subprocess.run([sys.executable, __file__, '--out', str(out), '--worker', str(script)],
                       cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
    assert 'SAT proof finished - no model found: SUCCESS!' in log.read_text()
    result = {'passed': True, 'input_bits': 96, 'inputs_constrained': False,
              'register_width': 32, 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
              'formal_wrapper_sha256': hashlib.sha256(wrapper.read_bytes()).hexdigest(),
              'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest()}
    (out / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
