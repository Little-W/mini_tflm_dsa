#!/usr/bin/env python3
"""证明激活范围检查及完整配置检查器的逐周期等价性。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import sys


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/conv/vector_config_check.sv')
sys.path.insert(0, str(ROOT / 'test'))
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from rtl_reference import read_rtl_source
from open_fpga_synth import run_stage


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='4dee27ffec4dc891daf2681379f8b3fd27fd41f2')
    parser.add_argument('--stable-config', action='store_true', help='按照接口要求，在 start 至 done 期间保持 cfg')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference = out / 'reference.sv'
    current = out / 'current.sv'
    reference.write_bytes(read_rtl_source(args.reference + ':' + str(SOURCE), cwd=ROOT))
    current.write_bytes((ROOT / SOURCE).read_bytes())
    bounds = out / 'activation_bounds.sv'
    bounds.write_text('''module activation_bounds (
    input logic signed [31:0] minimum, maximum,
    output logic equal
);
    logic original, selected;
    assign original = minimum >= -32'sd128 && maximum <= 32'sd127 && minimum <= maximum;
    assign selected = (minimum[31:8] == {24{minimum[7]}}) &&
                      (maximum[31:8] == {24{maximum[7]}}) &&
                      ($signed(minimum[7:0]) <= $signed(maximum[7:0]));
    assign equal = original == selected;
endmodule
''')
    script = out / 'activation_bounds.ys'
    script.write_text(f'''read_verilog -sv {shlex.quote(str(bounds))}
prep -top activation_bounds
sat -verify -prove equal 1 -show-inputs -show-outputs
''')
    runs = [{'name': 'activation_bounds', 'input_bits': 64, 'input_constraints': None,
             **run_stage(script, script.with_suffix('.log'), dict(os.environ))}]
    dependencies = [ROOT / 'rtl/npu/conv' / name
                    for name in ('conv_im2col_pkg.sv', 'vector_engine_pkg.sv')]
    dependencies.append(ROOT / 'rtl/common/parallel_prefix_add.sv')
    packages = ' '.join(shlex.quote(str(path)) for path in dependencies)
    wrapper = out / 'config_context.sv'
    wrapper.write_text('''module config_context #(
  parameter int TILE=16
)(
  input logic clk, rst_n, start, i_input_range,
  input vector_engine_pkg::vector_engine_cfg_t cfg,
  output logic ready, done, error,
  output logic [31:0] kernel_count, position_count,
  output logic [63:0] input_bytes, output_bytes, weight_bytes,
  output logic [32:0] o_read_end[4]
);
  vector_engine_pkg::vector_engine_cfg_t held_cfg, current_cfg;
  assign current_cfg = ready ? cfg : held_cfg;
  always_ff @(posedge clk) begin
    if (ready) held_cfg <= cfg;
  end
  vector_config_check #(.TILE(TILE)) u_check (
    .clk(clk), .rst_n(rst_n), .start(start), .i_input_range(i_input_range), .cfg(current_cfg),
    .ready(ready), .done(done), .error(error), .kernel_count(kernel_count), .position_count(position_count),
    .input_bytes(input_bytes), .output_bytes(output_bytes), .weight_bytes(weight_bytes), .o_read_end(o_read_end)
  );
endmodule
''')
    top = 'config_context' if args.stable_config else 'vector_config_check'
    extra = shlex.quote(str(wrapper)) if args.stable_config else ''
    hide = '\n'.join(('rename -hide w:*fields_ok*',
                       'rename -hide w:*output_x_in_range',
                       'rename -hide w:*output_y_in_range')) if args.stable_config else ''
    induction = 4
    for tile in (4, 16, 64):
        script = out / f'checker_tile{tile}.ys'
        script.write_text(f'''read_slang --top {top} -GTILE={tile} {packages} {shlex.quote(str(reference))} {extra}
prep -top {top} -flatten
async2sync
{hide}
rename {top} gold
design -stash reference
read_slang --top {top} -GTILE={tile} {packages} {shlex.quote(str(current))} {extra}
prep -top {top} -flatten
async2sync
{hide}
rename {top} gate
design -copy-from reference -as gold gold
equiv_make gold gate proof
hierarchy -top proof
equiv_simple -seq 2
equiv_induct -seq {induction}
equiv_status -assert
''')
        runs.append({'name': f'checker_tile{tile}',
                     'input_constraints': 'cfg held from accepted start through done' if args.stable_config else None,
                     **run_stage(script, script.with_suffix('.log'), dict(os.environ))})
    if current.read_bytes() != (ROOT / SOURCE).read_bytes():
        raise RuntimeError('验证期间配置检查器发生变化')
    report = {'passed': True, 'reference': args.reference,
              'source_sha256': hashlib.sha256(current.read_bytes()).hexdigest(),
              'reference_sha256': hashlib.sha256(reference.read_bytes()).hexdigest(),
              'scope': '激活范围的全部64位输入及完整检查器的公开输出与寄存状态',
              'stable_config': args.stable_config,
              'runs': runs}
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'passed': True, 'proofs': len(runs)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
