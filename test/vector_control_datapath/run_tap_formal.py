#!/usr/bin/env python3
"""证明卷积核位置递增、扩展末项比较和模加法末项比较。"""
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
SOURCE = Path('rtl/npu/conv/vector_engine.sv')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = (ROOT / SOURCE).read_text()
    first = source.rfind('  parallel_prefix_add #(', 0, source.index(') u_weight_tap_increment'))
    last = source.index('  assign weights_i_rd_tap', first)
    block = source[first:last]
    wrapper = out / 'tap.sv'
    wrapper.write_text('''module tap #(parameter int TAP_COUNT_W=9)(
input logic [TAP_COUNT_W-1:0] tap, taps);
logic [TAP_COUNT_W-1:0] weight_tap_nxt;
logic unused_weight_tap_carry, tap_last_wide, tap_last_modulo;
logic [TAP_COUNT_W:0] expected_increment;
assign expected_increment = {1'b0,tap} + (TAP_COUNT_W+1)'(1);
''' + block + '''
always_comb begin
    assert({unused_weight_tap_carry,weight_tap_nxt} == expected_increment);
    assert(tap_last_wide == (tap+1==taps));
    assert(tap_last_modulo == (tap+1'b1==taps));
end
endmodule
''')
    dependencies = [ROOT / 'rtl/common/parallel_prefix_add.sv', ROOT / 'rtl/common/add_equal.sv']
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    report = dict(passed=False, inputs_constrained=False,
                  source_sha256={str(p.relative_to(ROOT)): digest(p) for p in [ROOT / SOURCE, *dependencies]},
                  wrapper_sha256=digest(wrapper), runs=[])
    for width in (1, 2, 6, 8, 9, 11, 16, 31, 32):
        script, log = out / f'w{width}.ys', out / f'w{width}.log'
        script.write_text(f'read_slang --top tap -GTAP_COUNT_W={width} ' +
                          shlex.join(map(str, [wrapper, *dependencies])) + '\n'
                          'prep -top tap -flatten\nchformal -lower\nopt -full\n'
                          'sat -verify -prove-asserts -show-inputs\n')
        with log.open('w') as stream:
            result = subprocess.run([sys.executable, ROOT / 'scripts/fpga/open_fpga_synth.py',
                                     '--worker', script], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
        row = dict(width=width, passed=result.returncode == 0 and 'no model found: SUCCESS!' in log.read_text(),
                   log_sha256=digest(log))
        report['runs'].append(row)
        print(json.dumps(row), flush=True)
        if not row['passed']:
            raise RuntimeError(f'卷积核位置检查未完成：{log}')
    if report['source_sha256'] != {str(p.relative_to(ROOT)): digest(p) for p in [ROOT / SOURCE, *dependencies]}:
        raise RuntimeError('验证期间源码发生变化')
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
