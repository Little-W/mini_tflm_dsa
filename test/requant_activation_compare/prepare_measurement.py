#!/usr/bin/env python3
"""从实际量化通道提取裁剪逻辑，生成相同寄存边界的比较案例。"""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/writeback/vec_requant.sv')
WRAPPER = '''
module activation_measure(
    input logic clk,
    input logic signed [35:0] i_value,
    input logic signed [31:0] i_minimum, i_maximum,
    input logic i_lane_enable,
    output logic signed [7:0] o_s8,
    output logic signed [15:0] o_s16
);
    logic signed [35:0] value_q;
    logic signed [31:0] minimum_q,maximum_q;
    logic lane_enable_q;
    logic signed [7:0] next_s8;
    logic signed [15:0] next_s16;
    always_ff @(posedge clk) begin
        value_q<=i_value;
        minimum_q<=i_minimum;
        maximum_q<=i_maximum;
        lane_enable_q<=i_lane_enable;
        o_s8<=next_s8;
        o_s16<=next_s16;
    end
    activation_output u_output(value_q,minimum_q,maximum_q,lane_enable_q,next_s8,next_s16);
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference', default='cedf4ed33661a53c8194eca1d484cdc2279d7549')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    helper = ROOT / 'test/requant_activation_timing/run.py'
    spec = importlib.util.spec_from_file_location('activation_output_unit', helper)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    reference = subprocess.check_output(['git', 'show', f'{args.reference}:{SOURCE}'],
                                        cwd=ROOT, text=True)
    current = (args.source_root / SOURCE).read_text()
    lane = (ROOT / 'rtl/npu/writeback/requant_compute_lane.sv').read_text()
    cases = {}
    for label, source in [('reference', reference), ('current', current)]:
        path = out / (label + '.sv')
        path.write_text(module.output_unit(source, lane) + WRAPPER)
        cases[label] = {'top': 'activation_measure', 'sources': [str(path)],
                        'options': ['-DSYNTHESIS=1', '-DXILINX_FPGA=1'],
                        'configuration': 'Registered complete S8/S16 activation clipping'}
    (out / 'cases.json').write_text(json.dumps(cases, indent=2) + '\n')


if __name__ == '__main__':
    main()
