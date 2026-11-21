#!/usr/bin/env python3
"""比较窗口写入地址和范围资格的全部二值输入及四态传播。"""
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
PROFILES = ((2, 8, 4), (16, 64, 4), (16, 64, 8), (32, 128, 8), (64, 256, 16))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command, log):
    with log.open('w') as stream:
        result = subprocess.run(list(map(str, command)), cwd=ROOT, stdout=stream,
                                stderr=subprocess.STDOUT, timeout=180)
    if result.returncode:
        raise RuntimeError('窗口写入范围比较未通过：' + str(log))


def fragment(source, label):
    first = source.index('  for (genvar lane=0;lane<WINDOW_LANES;lane++) begin : g_window_write_address')
    last = source.index('  localparam int WINDOW_BANK_W=', first)
    return '''module window_bounds_''' + label + ''' #(
    parameter integer TILE=16, DMA_SIZE=64, WINDOW_LANES=8,
    INPUT_INDEX_W=$clog2(DMA_SIZE), ACTIVE_COUNT_W=$clog2(TILE+1)
)(
    input logic window_response_fire,
    input logic [31:0] win_rsp_col,
    input logic [WINDOW_LANES-1:0] win_rsp_mask,
    input logic [ACTIVE_COUNT_W-1:0] active,
    input logic [INPUT_INDEX_W-1:0] input_response_base,
    output wire [WINDOW_LANES-1:0] window_write_valid,
    output wire [INPUT_INDEX_W-1:0] window_write_index[WINDOW_LANES]
);
''' + source[first:last] + '\nendmodule\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference-revision', default='cedf4ed33661a53c8194eca1d484cdc2279d7549')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--iverilog', default='iverilog')
    parser.add_argument('--vvp', default='vvp')
    args = parser.parse_args()
    source = args.source_root.resolve() / SOURCE
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = source.read_text()
    original = subprocess.check_output(['git', 'show', args.reference_revision + ':' + str(SOURCE)],
                                       cwd=ROOT, text=True)
    modules = []
    for label, text in (('reference', original), ('selected', current)):
        path = out / (label + '.sv')
        path.write_text(fragment(text, label))
        modules.append(path)
    comparison = out / 'comparison.sv'
    comparison.write_text('''module comparison #(
    parameter integer TILE=16, DMA_SIZE=64, WINDOW_LANES=8,
    INPUT_INDEX_W=$clog2(DMA_SIZE), ACTIVE_COUNT_W=$clog2(TILE+1)
)(
    input logic window_response_fire,
    input logic [31:0] win_rsp_col,
    input logic [WINDOW_LANES-1:0] win_rsp_mask,
    input logic [ACTIVE_COUNT_W-1:0] active,
    input logic [INPUT_INDEX_W-1:0] input_response_base,
    output wire [WINDOW_LANES-1:0] reference_valid, selected_valid,
    output wire [INPUT_INDEX_W-1:0] reference_index[WINDOW_LANES],
    output wire [INPUT_INDEX_W-1:0] selected_index[WINDOW_LANES],
    output wire equal
);
window_bounds_reference #(.TILE(TILE),.DMA_SIZE(DMA_SIZE),.WINDOW_LANES(WINDOW_LANES)) original (
    .window_response_fire,.win_rsp_col,.win_rsp_mask,.active,.input_response_base,
    .window_write_valid(reference_valid),.window_write_index(reference_index));
window_bounds_selected #(.TILE(TILE),.DMA_SIZE(DMA_SIZE),.WINDOW_LANES(WINDOW_LANES)) selected (
    .window_response_fire,.win_rsp_col,.win_rsp_mask,.active,.input_response_base,
    .window_write_valid(selected_valid),.window_write_index(selected_index));
wire [WINDOW_LANES-1:0] index_equal;
for(genvar lane=0;lane<WINDOW_LANES;lane++) begin:g_compare
    assign index_equal[lane]=reference_index[lane]==selected_index[lane];
end
assign equal=(reference_valid==selected_valid)&&(&index_equal);
endmodule
''')
    modules.append(comparison)
    report = dict(source_sha256=sha(source), reference_revision=args.reference_revision,
                  reference_sha256=hashlib.sha256(original.encode()).hexdigest(),
                  inputs_constrained=False, profiles=[])
    declarations, checks = [], []
    for number, (tile, dma, lanes) in enumerate(PROFILES):
        folder = out / f'tile{tile}_dma{dma}_lanes{lanes}'
        folder.mkdir(exist_ok=True)
        script = folder / 'proof.ys'
        script.write_text(f'read_slang --top comparison -GTILE={tile} -GDMA_SIZE={dma} '
                          f'-GWINDOW_LANES={lanes} ' + shlex.join(map(str, modules)) + '\n'
                          'prep -top comparison -flatten\nopt -full\n'
                          'sat -verify -prove equal 1 -show-inputs -show-outputs\n')
        run([sys.executable, ROOT / 'scripts/fpga/open_fpga_synth.py', '--worker', script],
            folder / 'proof.log')
        assert 'SUCCESS' in (folder / 'proof.log').read_text()
        report['profiles'].append(dict(TILE=tile, DMA_SIZE=dma, WINDOW_LANES=lanes,
                                       passed=True, log_sha256=sha(folder / 'proof.log')))
        index_width, count_width = (dma-1).bit_length(), tile.bit_length()
        declarations.append(f'''wire [{lanes-1}:0] original_valid{number}, selected_valid{number};
wire [{index_width-1}:0] original_index{number}[{lanes}], selected_index{number}[{lanes}];
comparison #(.TILE({tile}),.DMA_SIZE({dma}),.WINDOW_LANES({lanes})) dut{number} (
    .window_response_fire,.win_rsp_col,.win_rsp_mask(win_rsp_mask[{lanes-1}:0]),
    .active(active[{count_width-1}:0]),.input_response_base(input_response_base[{index_width-1}:0]),
    .reference_valid(original_valid{number}),.selected_valid(selected_valid{number}),
    .reference_index(original_index{number}),.selected_index(selected_index{number}),.equal());''')
        checks.append(f'''if(original_valid{number} !== selected_valid{number}) $fatal(1,"valid profile {number} iteration %0d",iteration);
for(lane=0;lane<{lanes};lane=lane+1)
    if(original_index{number}[lane] !== selected_index{number}[lane]) $fatal(1,"index profile {number} iteration %0d",iteration);''')
    bench = out / 'four_state.sv'
    bench.write_text('''module tb;
logic window_response_fire;
logic [31:0] win_rsp_col;
logic [15:0] win_rsp_mask;
logic [6:0] active;
logic [7:0] input_response_base;
integer seed, seed_result, iteration, lane, comparisons=0;
''' + '\n'.join(declarations) + '''
initial begin
    seed=32'h418d299b;seed_result=$urandom(seed);
    for(iteration=0;iteration<65536;iteration=iteration+1) begin
        window_response_fire=1'($urandom());
        win_rsp_col=$urandom();
        if(iteration%2==0) win_rsp_col=32'($urandom()%256);
        win_rsp_mask=16'($urandom());active=7'($urandom());input_response_base=8'($urandom());
        case(iteration%10)
            1:win_rsp_col[$urandom()%32]=1'bx;
            2:win_rsp_col[$urandom()%32]=1'bz;
            3:active[$urandom()%7]=1'bx;
            4:active[$urandom()%7]=1'bz;
            5:win_rsp_mask[$urandom()%16]=1'bx;
            6:win_rsp_mask[$urandom()%16]=1'bz;
            7:window_response_fire=1'bx;
            8:window_response_fire=1'bz;
            9:input_response_base[$urandom()%8]=1'bx;
            default:begin end
        endcase
        #1;
''' + '\n'.join(checks) + f'''
        comparisons=comparisons+{len(PROFILES)};
    end
    $display("VECTOR_WINDOW_BOUNDS_PASS comparisons=%0d",comparisons);
    $finish;
end
endmodule
''')
    run([args.iverilog, '-g2012', '-s', 'tb', '-o', out / 'four_state.vvp', *modules, bench],
        out / 'compile.log')
    run([args.vvp, out / 'four_state.vvp'], out / 'four_state.log')
    assert 'VECTOR_WINDOW_BOUNDS_PASS comparisons=327680' in (out / 'four_state.log').read_text()
    assert current == source.read_text()
    report.update(passed=True, four_state_comparisons=327680,
                  test_sha256=sha(Path(__file__)), four_state_log_sha256=sha(out / 'four_state.log'))
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
