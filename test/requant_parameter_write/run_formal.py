#!/usr/bin/env python3
"""比较实际 WS 参数写入代码的全部存储状态和任意 DMA 输入。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from requant_test_utils import controller_module

ROOT = Path(__file__).resolve().parents[2]


def write_block(source):
    full = controller_module(source)
    end = full.index('  // 主状态机')
    if 'begin : g_ws_bank_write' in full:
        start = full.index('  if (((PARAM_BANKS & (PARAM_BANKS - 1)) == 0)')
    else:
        start = full.rindex('  always @(posedge clk)', 0, end)
    return full[start:end].rsplit('  // ----------------------------', 1)[0]


def wrapper(block, bus_width, lanes, reuse):
    return f'''module parameter_write (
    input logic clk, rsp_hskd, is_mode_r, load_phase,
    input logic [{max(1, (lanes + 1 - 1).bit_length()) - 1}:0] rd_beats_cnt, beats_expect,
    input logic [{max(1, (lanes * reuse - 1).bit_length()) - 1}:0] quant_rsp_idx,
    input logic [{bus_width - 1}:0] i_value, i_product_multiplier,
    input logic [{7 * (bus_width // 32) - 1}:0] i_product_amount,
    output logic [{32 * lanes - 1}:0] o_multiplier, o_product_multiplier, o_shift,
    output logic [{7 * lanes - 1}:0] o_product_amount
);
    localparam int BUS_WIDTH={bus_width}, VLEN={lanes}, MAX_IA_REUSE={reuse};
    localparam int PARAM_BANKS=BUS_WIDTH/32;
    localparam int p_compute_lanes=VLEN, p_serial_read_ports=0;
    wire [$clog2(VLEN+1)-1:0] serial_element_index[p_compute_lanes];
    wire signed [31:0] serial_product_multiplier[p_compute_lanes];
    wire [6:0] serial_product_amount[p_compute_lanes];
    wire signed [31:0] serial_bank_multiplier[PARAM_BANKS][p_compute_lanes];
    wire [6:0] serial_bank_amount[PARAM_BANKS][p_compute_lanes];
    localparam int VLEN_IDX_W=(VLEN<=1)?1:$clog2(VLEN);
    localparam int QBUF_IDX_W=(VLEN*MAX_IA_REUSE<=1)?1:$clog2(VLEN*MAX_IA_REUSE);
    localparam logic PH_MUL=1'b0;
    logic signed [31:0] ch_multiplier_lane_r[VLEN], ch_product_multiplier_lane_r[VLEN];
    logic signed [31:0] ch_shift_lane_r[VLEN];
    logic [6:0] ch_product_amount_lane_r[VLEN];
    logic signed [31:0] parameter_value[PARAM_BANKS], parameter_product_multiplier[PARAM_BANKS];
    logic [6:0] parameter_product_amount[PARAM_BANKS];
    logic [QBUF_IDX_W-1:0] parameter_index[PARAM_BANKS];
    for(genvar word=0;word<PARAM_BANKS;word++)begin:g_input
        assign parameter_value[word]=i_value[word*32+:32];
        assign parameter_product_multiplier[word]=i_product_multiplier[word*32+:32];
        assign parameter_product_amount[word]=i_product_amount[word*7+:7];
        assign parameter_index[word]=quant_rsp_idx+QBUF_IDX_W'(word);
    end
    for(genvar lane=0;lane<VLEN;lane++)begin:g_output
        assign o_multiplier[lane*32+:32]=ch_multiplier_lane_r[lane];
        assign o_product_multiplier[lane*32+:32]=ch_product_multiplier_lane_r[lane];
        assign o_shift[lane*32+:32]=ch_shift_lane_r[lane];
        assign o_product_amount[lane*7+:7]=ch_product_amount_lane_r[lane];
    end
''' + block + '\nendmodule\n'


def main():
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
    relative = 'rtl/npu/writeback/vec_requant.sv'
    candidate = (ROOT / relative).read_text()
    reference = r"""
    always_ff @(posedge clk)begin
        for(int word=0;word<PARAM_BANKS;word++)begin
            if(rsp_hskd && !is_mode_r &&
               (32'(rd_beats_cnt)+32'(word)) < 32'(beats_expect))begin
                if(load_phase==PH_MUL)begin
                    ch_multiplier_lane_r[VLEN_IDX_W'(parameter_index[word])] <= parameter_value[word];
                    ch_product_multiplier_lane_r[VLEN_IDX_W'(parameter_index[word])] <= parameter_product_multiplier[word];
                end else begin
                    ch_shift_lane_r[VLEN_IDX_W'(parameter_index[word])] <= parameter_value[word];
                    ch_product_amount_lane_r[VLEN_IDX_W'(parameter_index[word])] <= parameter_product_amount[word];
                end
            end
        end
    end
"""
    summary = {'reference_model_sha256': hashlib.sha256(reference.encode()).hexdigest(),
               'source_sha256': hashlib.sha256(candidate.encode()).hexdigest(),
               'inputs': 'All write data, addresses, beat counts, phase and response enables are unconstrained.',
               'compared_state': 'Every raw and preprocessed WS parameter bit after each clock edge.',
               'runs': []}
    for bus, lanes, reuse in [(32, 16, 32), (64, 16, 32), (128, 16, 32),
                              (64, 2, 2), (32, 1, 2), (96, 16, 32), (64, 3, 2), (128, 2, 2)]:
        folder = out / f'bus{bus}_lanes{lanes}_reuse{reuse}'
        folder.mkdir(exist_ok=True)
        commands = []
        for name, source in [('reference', reference), ('candidate', candidate)]:
            path = folder / (name + '.sv')
            content = wrapper(write_block(source) if name == 'candidate' else source, bus, lanes, reuse)
            # 未消费的地址高位可被独立优化；只比较完整存储状态和实际输出。
            content = re.sub(r'\bparameter_index\b', name + '_parameter_index', content)
            path.write_text(content)
            commands += ['read_slang --top parameter_write ' + shlex.quote(str(path)) + ' ' +
                         shlex.quote(str(ROOT / 'rtl/common/regfile.v')),
                         'prep -top parameter_write -flatten', 'memory_map', 'opt -full',
                         'rename -top ' + name, 'design -stash ' + name]
        commands += ['design -copy-from reference -as reference reference',
                     'design -copy-from candidate -as candidate candidate',
                     'equiv_make reference candidate equivalent', 'hierarchy -top equivalent',
                     'equiv_simple -seq 2', 'equiv_induct -seq 2', 'equiv_status -assert']
        script = folder / 'run.ys'
        script.write_text('\n'.join(commands) + '\n')
        with (folder / 'formal.log').open('w') as stream:
            completed = subprocess.run([sys.executable, __file__, '--out', str(out), '--worker', str(script)],
                                       stdout=stream, stderr=subprocess.STDOUT)
        log = (folder / 'formal.log').read_text()
        bits = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', log)
        result = {'bus_width': bus, 'lanes': lanes, 'reuse': reuse,
                  'passed': completed.returncode == 0 and 'Equivalence successfully proven' in log,
                  'state_bits': lanes * 103, 'equivalent_bits': int(bits[1]) if bits else None}
        summary['runs'].append(result)
        print(json.dumps(result), flush=True)
        if not result['passed']:
            print(log[-10000:])
            raise SystemExit(1)
    summary['passed'] = all(result['passed'] for result in summary['runs'])
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')


if __name__ == '__main__':
    main()
