#!/usr/bin/env python3
"""证明实际 IA 预取列宽计算保留完整模宽和尾列选择结果。"""
from pathlib import Path
import argparse
import hashlib
import json
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'rtl/npu/loaders/ia_loader.sv'
HELPER = ROOT / 'rtl/common/parallel_prefix_add.sv'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = SOURCE.read_text()
    first = source.index('    logic [REG_WIDTH-1:0] next_cols_inverse')
    last = source.index('    always_ff @(posedge clk or negedge rst_n)', first)
    body = source[first:last]
    hashes = {str(path.relative_to(ROOT)): digest(path) for path in (SOURCE, HELPER)}
    copied_helper = out / 'parallel_prefix_add.sv'
    copied_helper.write_bytes(HELPER.read_bytes())
    runs = []
    profiles = ((1, 1), (1, 2), (4, 1), (4, 3), (4, 16), (8, 4),
                (16, 16), (32, 1), (32, 3), (32, 16), (32, 64), (64, 16))
    for width, size in profiles:
        folder = out / f'width{width}_size{size}'
        folder.mkdir(exist_ok=True)
        rtl = folder / 'compare.sv'
        rtl.write_text(f'''module compare (
    input logic [{width-1}:0] cfg_global_reduction, cfg_q0_base,
    output logic equivalent
);
    localparam int REG_WIDTH = {width}, SIZE = {size}, LOG2_SIZE = $clog2(SIZE);
    logic [REG_WIDTH-1:0] next_remaining_cols, next_cols_comb;
    logic [REG_WIDTH-1:0] expected_remaining, expected_cols;
{body}
    assign expected_remaining = cfg_global_reduction - (cfg_q0_base + REG_WIDTH'(SIZE));
    assign expected_cols = expected_remaining >= REG_WIDTH'(SIZE) ? REG_WIDTH'(SIZE) : expected_remaining;
    assign equivalent = {{next_remaining_cols, next_cols_comb}} == {{expected_remaining, expected_cols}};
endmodule
''')
        script, log = folder / 'run.ys', folder / 'run.log'
        script.write_text('read_slang --top compare ' + shlex.join([str(rtl), str(copied_helper)]) +
                          '\nprep -top compare -flatten\ncheck -assert\n'
                          'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                            '--worker', str(script)], cwd=ROOT, stdout=stream,
                           stderr=subprocess.STDOUT, check=True)
        assert 'SAT proof finished - no model found: SUCCESS!' in log.read_text()
        row = dict(register_width=width, size=size, compared_bits=2*width,
                   passed=True, script_sha256=digest(script), log_sha256=digest(log))
        runs.append(row)
        print(json.dumps(row), flush=True)
    assert hashes == {str(path.relative_to(ROOT)): digest(path) for path in (SOURCE, HELPER)}
    report = dict(passed=True, input_assumptions=[], source_sha256=hashes, runs=runs)
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
