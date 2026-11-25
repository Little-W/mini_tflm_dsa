#!/usr/bin/env python3
"""逐周期比较实际向量加法 RTL，并证明二态输入下的无限时序等价。"""
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
SOURCE = Path('rtl/npu/compute/registered_vector_add.sv')

HEADER = '''
module comparison #(parameter int LANES=3)(
    input logic clk, rst_n, i_clear, i_valid, i_tile_done,
    input logic signed [31:0] i_lhs [LANES],
    input logic signed [31:0] i_rhs [LANES],
    output wire current_valid, current_tail, reference_valid, reference_tail,
    output wire signed [31:0] current_sum [LANES],
    output wire signed [31:0] reference_sum [LANES]
);
registered_vector_add #(.p_lanes(LANES)) u_current (
    .clk, .rst_n, .i_clear, .i_valid, .i_tile_done, .i_lhs, .i_rhs,
    .o_valid(current_valid), .o_tile_done(current_tail), .o_sum(current_sum)
);
registered_vector_add_reference #(.p_lanes(LANES)) u_reference (
    .clk, .rst_n, .i_clear, .i_valid, .i_tile_done, .i_lhs, .i_rhs,
    .o_valid(reference_valid), .o_tile_done(reference_tail), .o_sum(reference_sum)
);
'''
PROPERTIES = '''
logic have_data;
always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) have_data <= 1'b0;
    else if (i_valid && !i_clear) have_data <= 1'b1;
end
always_comb begin
    assert(current_valid == reference_valid);
    assert(current_tail == reference_tail);
    if (have_data) begin
        for (int lane=0;lane<LANES;lane++) assert(current_sum[lane] == reference_sum[lane]);
    end
end
endmodule
'''
BENCH = '''
module tb;
localparam int LANES=3;
logic clk=0, rst_n=0, i_clear=0, i_valid=0, i_tile_done=0;
logic signed [31:0] i_lhs [LANES], i_rhs [LANES];
wire current_valid, current_tail, reference_valid, reference_tail;
wire signed [31:0] current_sum [LANES], reference_sum [LANES];
integer cycles=0, checks=0;
integer seed=20261125;
logic [31:0] boundary [12];
comparison #(.LANES(LANES)) dut(.*);
task automatic compare_outputs;
    if (current_valid !== reference_valid || current_tail !== reference_tail)
        $fatal(1,"Control mismatch at cycle %0d",cycles);
    for (int lane=0;lane<LANES;lane++) begin
        if (current_sum[lane] !== reference_sum[lane])
            $fatal(1,"Sum mismatch cycle=%0d lane=%0d current=%h reference=%h",
                   cycles,lane,current_sum[lane],reference_sum[lane]);
        checks++;
    end
endtask
task automatic step;
    #1; compare_outputs(); clk=1;
    #1; compare_outputs(); clk=0;
    #1; cycles++;
endtask
initial begin
    boundary[0]=32'h0; boundary[1]=32'h1; boundary[2]=32'hff;
    boundary[3]=32'hffff; boundary[4]=32'hffffff; boundary[5]=32'hffffffff;
    boundary[6]=32'h7fffffff; boundary[7]=32'h80000000;
    boundary[8]=32'hff00ff00; boundary[9]=32'h00ff00ff;
    boundary[10]=32'hfefefefe; boundary[11]=32'h01010101;
    for(int lane=0;lane<LANES;lane++) begin i_lhs[lane]=0; i_rhs[lane]=0; end
    step(); rst_n=1; i_valid=1;
    for(int a=0;a<12;a++) begin
        for(int b=0;b<12;b++) begin
            for(int lane=0;lane<LANES;lane++) begin
                i_lhs[lane]=boundary[(a+lane)%12];
                i_rhs[lane]=boundary[(b+2*lane)%12];
            end
            step();
        end
    end
    for(int trial=0;trial<32768;trial++) begin
        rst_n=(trial%521!=0); i_valid=(trial%7!=0); i_clear=(trial%37==0);
        i_tile_done=(trial%5==0);
        for(int lane=0;lane<LANES;lane++) begin
            i_lhs[lane]=$urandom(seed); i_rhs[lane]=$urandom(seed);
        end
        if (trial%2==0) i_lhs[(trial/2)%LANES][(trial/6)%32]=1'bx;
        if (trial%3==0) i_rhs[(trial/3)%LANES][(trial/9)%32]=1'bz;
        if (trial%41==0) i_valid=1'bx;
        if (trial%43==0) i_clear=1'bz;
        if (trial%47==0) i_tile_done=1'bx;
        if (trial%59==0) i_lhs[0]='x;
        if (trial%61==0) i_rhs[1]='z;
        step();
    end
    $display("VECTOR_ADD_REVISION_PASS cycles=%0d checks=%0d",cycles,checks); $finish;
end
endmodule
'''


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def run(command, path, timeout=180):
    with path.open('w') as stream:
        subprocess.run(list(map(str, command)), cwd=ROOT, stdout=stream,
                       stderr=subprocess.STDOUT, check=True, timeout=timeout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', default='2247144937c2fd04039b9b005151f371d6b51f8f')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = (ROOT / SOURCE).read_text()
    reference = subprocess.check_output(['git', 'show', f'{args.reference}:{SOURCE}'],
                                        cwd=ROOT, text=True)
    reference_named = re.sub(r'\bregistered_vector_add\b',
                             'registered_vector_add_reference', reference)
    combined = current + '\n' + reference_named + '\n' + HEADER
    formal = out / 'formal.sv'
    formal.write_text(combined + PROPERTIES)
    results = []
    for lanes in (1, 3, 8, 16):
        script = out / f'lanes{lanes}.ys'
        script.write_text('read_slang --top comparison -D SYNTHESIS=1 -GLANES=' + str(lanes) +
            ' ' + shlex.quote(str(formal)) + '\n' +
            'prep -top comparison -flatten\nmemory_map\nopt_clean\nasync2sync\ndffunmap\nopt_clean\n' +
            'sat -seq 3 -tempinduct -maxsteps 8 -set-at 1 rst_n 0 -prove-asserts -verify -timeout 90\n')
        log = out / f'lanes{lanes}.log'
        run([sys.executable, ROOT / 'scripts/fpga/open_fpga_synth.py', '--worker', script], log)
        if 'Induction step proven: SUCCESS!' not in log.read_text():
            raise RuntimeError('无限时序证明未完成')
        results.append(dict(lanes=lanes, unbounded_equivalence=True))
    simulation = out / 'simulation.sv'
    simulation.write_text((combined + 'endmodule\n' + BENCH).replace(
        'parameter int unsigned', 'parameter integer').replace(
        'localparam int unsigned', 'localparam integer'))
    binary = out / 'simulation.vvp'
    run(['iverilog', '-g2012', '-s', 'tb', '-o', binary, simulation], out / 'build.log')
    run(['vvp', binary], out / 'simulation.log')
    result = (out / 'simulation.log').read_text().strip()
    if 'VECTOR_ADD_REVISION_PASS' not in result:
        raise RuntimeError('四态仿真未完成')
    if current != (ROOT / SOURCE).read_text():
        raise RuntimeError('验证期间源文件发生变化')
    report = dict(passed=True, reference=args.reference,
        current_sha256=digest(current), reference_sha256=digest(reference),
        formal=results, simulation=result, sources_unchanged=True)
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
