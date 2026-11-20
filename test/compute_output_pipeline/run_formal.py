#!/usr/bin/env python3
"""证明实际计算核心的输出周期和分组完成关系，PS 输出作为任意值输入。"""
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
CORE = Path('rtl/npu/compute/compute_core.sv')
sys.path.insert(0, str(ROOT / 'test'))
from rtl_reference import read_rtl_source


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def extracted_stage(text, name):
    begin = text.index('    logic signed [31:0] bias_or_ps_sum')
    end = text.index('`ifdef NPU_SIM_ASSERT', begin)
    body = text[begin:end]
    for module in ('bias_mux', 'ws_systolic_array', 'ps_buffer'):
        body, count = re.subn(r'\n    ' + module + r'\s+#\(.*?\n    \);', '', body,
                             count=1, flags=re.S)
        if count != 1:
            raise ValueError('Cannot locate core submodule: ' + module)
    header = f'''module {name} #(parameter int SIZE=16, PS_FRAME_COUNT=4, MAX_IA_REUSE=2)(
        input logic clk, rst_n, ia_row_valid, ia_calc_done, ia_is_init_data,
        input logic ia_sending_done, final_output_overlap, direct_final_stream,
        input logic signed [31:0] i_ps_data [SIZE],
        input logic i_ps_valid, i_ps_tile_done,
        output logic signed [31:0] acc_data_out [SIZE],
        output logic acc_data_valid, partial_sum_calc_over, partial_sum_advance_ready,
        output logic tile_calc_over, o_final_component, o_nonfinal_component
    );
'''
    connections = '''
    assign ps_acc_out = i_ps_data;
    assign ps_acc_data_valid = i_ps_valid;
    assign ps_tile_calc_over = i_ps_tile_done;
    assign o_final_component = final_group_complete_q ||
        (ps_group_switch_d && ps_calc_done_d && final_output_overlap);
    assign o_nonfinal_component = ps_group_switch_d && !ps_calc_done_d;
endmodule
'''
    return header + body + connections


HARNESS = '''
module pipeline_properties #(parameter int SIZE=16)(
    input logic clk, rst_n, ia_row_valid, ia_calc_done, ia_is_init_data,
    input logic ia_sending_done, final_output_overlap, direct_final_stream,
    input logic signed [31:0] i_ps_data [SIZE],
    input logic i_ps_valid, i_ps_tile_done
);
    wire signed [31:0] reference_data [SIZE], current_data [SIZE];
    wire reference_valid, current_valid, reference_tile, current_tile;
    wire reference_complete, current_complete, reference_advance, current_advance;
    wire reference_final, reference_nonfinal, current_final, current_nonfinal;
    logic signed [31:0] delayed_data [SIZE];
    logic delayed_valid, delayed_tile, delayed_final;
    reference_stage #(.SIZE(SIZE)) u_reference (
        .clk(clk), .rst_n(rst_n), .ia_row_valid(ia_row_valid), .ia_calc_done(ia_calc_done),
        .ia_is_init_data(ia_is_init_data), .ia_sending_done(ia_sending_done),
        .final_output_overlap(final_output_overlap), .direct_final_stream(direct_final_stream),
        .i_ps_data(i_ps_data), .i_ps_valid(i_ps_valid), .i_ps_tile_done(i_ps_tile_done),
        .acc_data_out(reference_data), .acc_data_valid(reference_valid),
        .tile_calc_over(reference_tile), .partial_sum_calc_over(reference_complete),
        .partial_sum_advance_ready(reference_advance),
        .o_final_component(reference_final), .o_nonfinal_component(reference_nonfinal)
    );
    current_stage #(.SIZE(SIZE)) u_current (
        .clk(clk), .rst_n(rst_n), .ia_row_valid(ia_row_valid), .ia_calc_done(ia_calc_done),
        .ia_is_init_data(ia_is_init_data), .ia_sending_done(ia_sending_done),
        .final_output_overlap(final_output_overlap), .direct_final_stream(direct_final_stream),
        .i_ps_data(i_ps_data), .i_ps_valid(i_ps_valid), .i_ps_tile_done(i_ps_tile_done),
        .acc_data_out(current_data), .acc_data_valid(current_valid),
        .tile_calc_over(current_tile), .partial_sum_calc_over(current_complete),
        .partial_sum_advance_ready(current_advance),
        .o_final_component(current_final), .o_nonfinal_component(current_nonfinal)
    );
    always_ff @(posedge clk) delayed_data <= reference_data;
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            delayed_valid <= 0;
            delayed_tile <= 0;
            delayed_final <= 0;
        end else begin
            delayed_valid <= reference_valid;
            delayed_tile <= reference_tile;
            delayed_final <= reference_final;
        end
    end
    always_comb begin
        if (rst_n) begin
            assert(reference_complete == (reference_final || reference_nonfinal));
            assert(current_valid == delayed_valid);
            assert(current_tile == delayed_tile);
            assert(current_complete == (delayed_final || reference_nonfinal));
            assert(current_advance == reference_advance);
            assert(current_nonfinal == reference_nonfinal);
            assert(current_final == reference_final);
            for (int lane=0;lane<SIZE;lane++) assert(current_data[lane] == delayed_data[lane]);
        end
    end
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='9a6437f48722b3f53d4084b48c72cfb1d4b1fa5a')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = (ROOT / CORE).read_text()
    reference = read_rtl_source(f'{args.reference}:{CORE}', cwd=ROOT).decode()
    source = out / 'pipeline_properties.sv'
    source.write_text(extracted_stage(reference, 'reference_stage') +
                      extracted_stage(current, 'current_stage') + HARNESS)
    runs = []
    for size in (1, 2, 3, 4, 16, 32):
        folder = out / f'size{size}'
        folder.mkdir(exist_ok=True)
        script = folder / 'run.ys'
        script.write_text(
            'read_slang --top pipeline_properties -GSIZE=' + str(size) + ' ' + shlex.quote(str(source)) + '\n'
            'hierarchy -top pipeline_properties\nproc\nflatten\nopt\nasync2sync\ndffunmap\nopt_clean\n'
            f'sat -seq 2 -tempinduct -maxsteps {size+4} -set-at 1 rst_n 0 '
            '-prove-asserts -verify -timeout 60\n')
        command = [sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'), '--worker', str(script)]
        with (folder / 'formal.log').open('w') as stream:
            subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
        log = (folder / 'formal.log').read_text()
        if 'Induction step proven: SUCCESS!' not in log:
            raise RuntimeError('Induction did not finish: ' + str(folder))
        row = dict(size=size, passed=True, unbounded_induction=True,
                   output_data_bits=32*size, output_latency_cycles=1,
                   final_completion_latency_cycles=1, intermediate_completion_latency_cycles=0,
                   command=command)
        runs.append(row)
        print(json.dumps(row), flush=True)
    if (ROOT / CORE).read_text() != current:
        raise RuntimeError('Source changed during proof')
    summary = dict(passed=True, reference=args.reference, reference_sha256=digest(reference),
                   source_sha256=digest(current), extracted_source_sha256=digest(source.read_text()),
                   checker_source_sha256=digest(Path(__file__).read_text()),
                   scope='实际 RTL 的输出寄存与元数据；部分和输出为任意二态数据和控制输入',
                   sources_unchanged=True, assumptions='仅第一个采样周期复位', runs=runs)
    (out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
