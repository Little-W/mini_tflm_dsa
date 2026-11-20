#!/usr/bin/env python3
"""以实际源码和官方 LUT 模型证明公共参数读取选择。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def selection_blocks(source):
    full = source.split('module vec_requant_full #(', 1)[1]
    first = full.index('  logic [VLEN_CNT_W-1:0] input_row_idx_cur;')
    common = full[first:full.index('  logic signed [35:0] rounding_offset;', first)]
    if 'parameter_mux_i_direct' in full:
        declarations = '\n'.join(re.findall(r'^    logic[^;]*\bparameter_mux_\w+[^;]*;', full, re.M))
        first = full.index('    // 通道端只执行二选一')
    else:
        declarations = ''
        first = full.index('    always_comb begin\n      if (cfg_per_channel_eff) begin')
    lane = full[first:full.index('    logic shift_en;', first)]
    return common, declarations + '\n' + lane


def ports(bus_width, lanes, output):
    return f'''(
    input logic cfg_per_channel_eff, is_mode_r,
    input logic [15:0] row_offset_in_group,
    input logic [{lanes.bit_length()-1}:0] row_in_tile_cnt,
    input logic [{103*lanes-1}:0] i_ws,
    input logic [{103*(bus_width//32)-1}:0] i_is,
    input logic [102:0] i_tensor,
    output logic [{103*lanes-1}:0] {output}
);\n'''


def wrapper(source, name, bus_width, lanes):
    common, lane = selection_blocks(source)
    return 'module ' + name + ports(bus_width, lanes, 'o_value') + f'''
    localparam int VLEN={lanes}, PARAM_BANKS={bus_width//32}, REG_WIDTH=32;
    localparam int VLEN_CNT_W=$clog2(VLEN+1), VLEN_SHIFT=$clog2(VLEN), QBUF_IDX_W=$clog2(VLEN*32);
    logic [QBUF_IDX_W-1:0] input_group_idx_cur;
    logic signed [31:0] ch_multiplier_lane_r[VLEN], ch_shift_lane_r[VLEN], ch_product_multiplier_lane_r[VLEN];
    logic [6:0] ch_product_amount_lane_r[VLEN];
    logic signed [31:0] ch_multiplier_is_read[PARAM_BANKS], ch_shift_is_read[PARAM_BANKS];
    logic signed [31:0] ch_product_multiplier_is_read[PARAM_BANKS];
    logic [6:0] ch_product_amount_is_read[PARAM_BANKS];
    logic signed [31:0] pt_multiplier_r, pt_shift_r, pt_product_multiplier_r;
    logic [6:0] pt_product_amount_r;
    logic signed [31:0] quant_multiplier_lane[VLEN], quant_shift_lane[VLEN];
    assign {{pt_multiplier_r,pt_shift_r,pt_product_multiplier_r,pt_product_amount_r}}=i_tensor;
    for(genvar j=0;j<VLEN;j++)begin:g_ws
        assign {{ch_multiplier_lane_r[j],ch_shift_lane_r[j],ch_product_multiplier_lane_r[j],ch_product_amount_lane_r[j]}}=i_ws[j*103+:103];
    end
    for(genvar j=0;j<PARAM_BANKS;j++)begin:g_is
        assign {{ch_multiplier_is_read[j],ch_shift_is_read[j],ch_product_multiplier_is_read[j],ch_product_amount_is_read[j]}}=i_is[j*103+:103];
    end
''' + common + '''
    for(genvar j=0;j<VLEN;j++)begin:LANE
        logic signed [31:0] mult_sel,shift_sel_raw,product_multiplier_sel;
        logic [6:0] product_amount_sel;
''' + lane + '''
        assign o_value[j*103+:103]={quant_multiplier_lane[j],quant_shift_lane[j],product_multiplier_sel,product_amount_sel};
    end
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-rev', default='e644187')
    parser.add_argument('--worker', type=Path)
    args = parser.parse_args()
    if args.worker:
        from pyosys import libyosys
        libyosys.run_pass('script ' + shlex.quote(str(args.worker)))
        return
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    relative = 'rtl/npu/writeback/vec_requant.sv'
    candidate = (ROOT / relative).read_text()
    reference = subprocess.check_output(['git', 'show', args.reference_rev + ':' + relative], cwd=ROOT, text=True)
    helper = re.search(r'^module requant_shift_mux\b.*?^endmodule', candidate, re.M | re.S)[0]
    import pyosys
    library = Path(pyosys.__file__).parent / 'share/xilinx/cells_sim.v'
    model = re.search(r'^module LUT6_2\b.*?^endmodule', library.read_text(), re.M | re.S)[0]
    model = re.sub(r'\bspecify\b.*?\bendspecify\b', '', model, flags=re.S)
    summary = {'reference_rev': args.reference_rev,
               'reference_sha256': hashlib.sha256(reference.encode()).hexdigest(),
               'source_sha256': hashlib.sha256(candidate.encode()).hexdigest(),
               'primitive_library_sha256': hashlib.sha256(library.read_bytes()).hexdigest(),
               'inputs': 'All parameter values, mode bits and input row addresses are unconstrained.',
               'runs': []}
    for bus, lanes in ((32, 16), (64, 16), (96, 16), (128, 16)):
        for fpga in (False, True):
            folder = out / f'bus{bus}_lanes{lanes}_fpga{int(fpga)}'
            folder.mkdir(exist_ok=True)
            top = 'module read_compare ' + ports(bus, lanes, 'o_value') + f'''
                logic [{103*lanes-1}:0] reference_value;
                read_reference u_reference(.*, .o_value(reference_value));
                read_candidate u_candidate(.*);
                always_comb assert(reference_value == o_value);
                endmodule
            '''
            path = folder / 'comparison.sv'
            path.write_text(wrapper(reference, 'read_reference', bus, lanes) +
                            wrapper(candidate, 'read_candidate', bus, lanes) + top + helper + '\n' + model)
            script = folder / 'run.ys'
            script.write_text('read_slang --top read_compare ' + ('-D SYNTHESIS ' if fpga else '') +
                              shlex.quote(str(path)) + '\nprep -top read_compare -flatten\nchformal -lower\nopt -full\n'
                              'sat -set-def-inputs -prove-asserts -verify\n')
            with (folder / 'formal.log').open('w') as log:
                completed = subprocess.run([sys.executable, __file__, '--out', str(out), '--worker', str(script)],
                                           stdout=log, stderr=subprocess.STDOUT)
            log = (folder / 'formal.log').read_text()
            result = {'bus_width': bus, 'lanes': lanes, 'fpga_primitives': fpga,
                      'compared_bits': 103*lanes,
                      'passed': completed.returncode == 0 and 'SUCCESS!' in log}
            summary['runs'].append(result)
            print(json.dumps(result), flush=True)
            if not result['passed']:
                print(log[-10000:])
                raise SystemExit(1)
    summary['passed'] = all(item['passed'] for item in summary['runs'])
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')


if __name__ == '__main__':
    main()
