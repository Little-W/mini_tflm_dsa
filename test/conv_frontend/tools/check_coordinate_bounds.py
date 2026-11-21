#!/usr/bin/env python3
"""对七组坐标加法和范围检查执行全部输入等价证明。"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'test'))
from rtl_reference import read_rtl_source


def coordinate_block(text):
    start = text.index('  for (genvar axis = 0; axis < 7; axis++) begin : g_coordinate_bound')
    return text[start:text.index('  // 数据字匹配比较读取范围以外的高位', start)]


def wrapper(name, body):
    return '''module ''' + name + ''' #(parameter bit REGISTER_DESCRIPTOR=0) (
    input logic [6:0][34:0] left_operand, right_operand,
    input logic [6:0][15:0] limit,
    output logic [6:0] bound_valid,
    output logic [6:0][34:0] sums
);
    localparam int COORD_W=35;
    logic [34:0] bound_a[7], bound_b[7], bound_sum[7];
    logic [15:0] bound_limit[7];
    for (genvar axis=0;axis<7;axis++) begin : g_operands
        assign bound_a[axis] = left_operand[axis];
        assign bound_b[axis] = axis==1 || axis==3 || axis==4 || axis==6 ?
            {19'd0,right_operand[axis][15:0]} : right_operand[axis];
        assign bound_limit[axis] = limit[axis];
        assign sums[axis] = bound_sum[axis];
    end
''' + body + '\nendmodule\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference-ref', default='415a70a')
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    relative = 'rtl/npu/conv/conv_im2col_frontend.sv'
    source = (root / relative).read_text()
    reference = read_rtl_source(args.reference_ref + ':' + relative, cwd=ROOT, text=True)
    proof = out / 'bounds.sv'
    proof.write_text(wrapper('candidate_bounds', coordinate_block(source)) +
                     wrapper('reference_bounds', coordinate_block(reference)) + '''
module bounds_proof #(parameter bit REGISTER_DESCRIPTOR=0) (
    input logic [6:0][34:0] left_operand, right_operand,
    input logic [6:0][15:0] limit,
    output logic equivalent
);
    logic [6:0] candidate_valid, reference_valid;
    logic [6:0][34:0] candidate_sums, reference_sums;
    candidate_bounds #(.REGISTER_DESCRIPTOR(REGISTER_DESCRIPTOR)) u_candidate(.left_operand,.right_operand,.limit,
        .bound_valid(candidate_valid),.sums(candidate_sums));
    reference_bounds #(.REGISTER_DESCRIPTOR(REGISTER_DESCRIPTOR)) u_reference(.left_operand,.right_operand,.limit,
        .bound_valid(reference_valid),.sums(reference_sums));
    logic [6:0] equivalent_axis;
    for (genvar axis=0;axis<7;axis++) begin : g_compare
        if (axis<4 || !REGISTER_DESCRIPTOR)
            assign equivalent_axis[axis]=candidate_valid[axis]==reference_valid[axis] &&
                candidate_sums[axis]==reference_sums[axis];
        else
            assign equivalent_axis[axis]=candidate_valid[axis]==1'b0 && candidate_sums[axis]=='0;
    end
    assign equivalent=&equivalent_axis;
endmodule
''')
    sources = []
    for name in ('add_equal.sv', 'parallel_prefix_add.sv', 'unsigned_compare.sv'):
        target = out / name
        target.write_bytes((root / 'rtl/common' / name).read_bytes())
        sources.append(target)
    summary = {'source_sha256': hashlib.sha256(source.encode()).hexdigest(),
               'reference_ref': args.reference_ref, 'input_constraints': [], 'input_bits': 602,
               'positive_step_axes': [1, 3, 4, 6], 'coordinate_width': 35, 'runs': []}
    for registered, fpga in ((registered, fpga) for registered in (0, 1) for fpga in (0, 1)):
        script, log = out / f'r{registered}_fpga{fpga}.ys', out / f'r{registered}_fpga{fpga}.log'
        script.write_text('read_slang --top bounds_proof -GREGISTER_DESCRIPTOR=' + str(registered) + ' ' + ('-D XILINX_FPGA=1 ' if fpga else '') +
                          shlex.join(map(str, [*sources, proof])) + '\n' +
                          'prep -top bounds_proof -flatten\ncheck -assert\n' +
                          'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'), '--worker', str(script)],
                           stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=180)
        if 'SAT proof finished - no model found: SUCCESS!' not in log.read_text():
            raise RuntimeError('Coordinate bound proof did not complete')
        summary['runs'].append({'register_descriptor': bool(registered), 'xilinx_fpga': bool(fpga), 'passed': True,
                                'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest()})
        print(f'COORDINATE_BOUNDS_PASS registered={registered} fpga={fpga}', flush=True)
    summary['passed'] = True
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')


if __name__ == '__main__':
    main()
