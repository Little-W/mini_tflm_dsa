#!/usr/bin/env python3
"""证明描述符译码寄存器与保存描述符后的组合译码逐周期一致。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import sys


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/conv/vector_engine.sv')
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
sys.path.insert(0, str(ROOT / 'test'))
from open_fpga_synth import run_stage
from rtl_reference import read_rtl_source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='415a70a')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    candidate = (ROOT / SOURCE).read_text()
    reference = read_rtl_source(args.reference + ':' + str(SOURCE), cwd=ROOT, text=True)
    first = candidate.index('  // 运算类型和描述符同时保存')
    last = candidate.index('  logic [31:0] position_next;', first)
    candidate_body = candidate[first:last]
    original_modes = re.search(r'  assign spatial\s*=.*?  assign binary_vector\s*=.*?;',
                               reference, re.S).group(0)
    original_pe = re.search(r'    pe_op=PE_MADD;.*?    endcase', reference, re.S).group(0)
    header = '''module mode_control (
  input logic clk, rst_n, start,
  input logic [5:0] state,
  input vector_engine_pkg::vector_engine_cfg_t cfg,
  output logic spatial, depthwise, binary_vector, add_s8, softmax_s8, byte_output,
  output logic avg_pool, max_pool, min_pool, vector_max, vector_min, vector_hadamard,
  output logic [2:0] pe_op
);
  import vector_engine_pkg::*;
  localparam logic [5:0] IDLE=6'd0;
'''
    reference_body = '''
  vector_engine_cfg_t c;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) c <= '0;
    else if (state == IDLE && start) c <= cfg;
  end
''' + original_modes + '''
  assign avg_pool = c.op == AVGPOOL_S8;
  assign max_pool = c.op == MAXPOOL_S8;
  assign min_pool = c.op == MINPOOL_S8;
  assign vector_max = c.op == VEC_MAX;
  assign vector_min = c.op == VEC_MIN;
  assign vector_hadamard = c.op == VEC_HADAMARD;
  always_comb begin
''' + original_pe + '\n  end\n'
    for name, body in [('reference', reference_body), ('candidate', candidate_body)]:
        (out / (name + '.sv')).write_text(header + body + '\nendmodule\n')
    packages = ' '.join(shlex.quote(str(ROOT / 'rtl/npu/conv' / name))
                        for name in ('conv_im2col_pkg.sv', 'vector_engine_pkg.sv'))
    script = out / 'control.ys'
    script.write_text(f'''read_slang --top mode_control {packages} {shlex.quote(str(out / 'reference.sv'))}
prep -top mode_control -flatten
async2sync
rename mode_control gold
design -stash reference
read_slang --top mode_control {packages} {shlex.quote(str(out / 'candidate.sv'))}
prep -top mode_control -flatten
async2sync
rename mode_control gate
design -copy-from reference -as gold gold
equiv_make gold gate proof
hierarchy -top proof
equiv_simple -seq 2
equiv_induct -seq 2
equiv_status -assert
''')
    result = run_stage(script, out / 'control.log', dict(os.environ))
    if candidate != (ROOT / SOURCE).read_text():
        raise RuntimeError('验证期间引擎源码发生变化')
    report = {'passed': True, 'input_constraints': None, 'output_bits': 15,
              'scope': '全部操作码、接收时刻、复位和任务保持条件',
              'source_sha256': hashlib.sha256(candidate.encode()).hexdigest(),
              'reference_revision': args.reference, 'run': result}
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'passed': True, 'output_bits': 15}))


if __name__ == '__main__':
    main()
