#!/usr/bin/env python3
"""证明 PE 累加输入预选的数值、四态行为和使能保持。"""
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
PE = Path('rtl/npu/conv/vector_pe.sv')
ENGINE = Path('rtl/npu/conv/vector_engine.sv')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command, log):
    with log.open('w') as handle:
        handle.write('$ ' + shlex.join(map(str, command)) + '\n')
        handle.flush()
        result = subprocess.run(list(map(str, command)), cwd=ROOT,
                                stdout=handle, stderr=subprocess.STDOUT, timeout=120)
    if result.returncode:
        raise RuntimeError('验证失败：' + str(log))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference-root', type=Path)
    parser.add_argument('--reference-revision', default='c1c0cb91770a7bb1639afb773f907432f9b12d6f')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--iverilog', default='iverilog')
    parser.add_argument('--vvp', default='vvp')
    args = parser.parse_args()
    root = args.source_root.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference = args.reference_root.resolve() if args.reference_root else out / 'reference_tree'
    if not args.reference_root:
        sys.path.insert(0, str(ROOT / 'test'))
        from rtl_reference import read_rtl_source
        for path in (PE, ENGINE):
            destination = reference / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(read_rtl_source(args.reference_revision + ':' + str(path), cwd=ROOT))
    hashes = {str(path): digest(root / path) for path in (PE, ENGINE)}
    original_hashes = {str(path): digest(reference / path) for path in (PE, ENGINE)}
    paths = []
    for label, directory in (('reference', reference), ('selected', root)):
        text = (directory / PE).read_text().split('// 串行归约', 1)[0]
        if label == 'reference':
            text = re.sub(r'\b(vector_pe|registered_vector_pe)\b', r'reference_\1', text)
        target = out / (label + '.sv')
        target.write_text(text + '\n`default_nettype wire\n')
        paths.append(target)

    wrapper = out / 'comparison.sv'
    wrapper.write_text('''module pe_comparison (
    input logic clk, i_en,
    input logic [2:0] op,
    input logic signed [15:0] a, b,
    input logic signed [31:0] acc,
    output wire [31:0] original_default, selected_default,
    output wire [31:0] original_combinational, selected_combinational,
    output wire [31:0] original_registered, selected_registered,
    output wire [31:0] original_positional, selected_positional,
    output wire default_equal, combinational_equal, registered_equal, positional_equal
);
logic signed [31:0] selected_acc;
logic [2:0] op_q;
always_comb begin
    selected_acc = acc;
    case (op)
        3'd4: selected_acc = 32'sd0;
        default: begin end
    endcase
end
always @(posedge clk) if (i_en) op_q <= op;
reference_vector_pe default_reference (.op(op),.a(a),.b(b),.acc(acc),.result(original_default));
vector_pe default_selected (.op(op),.a(a),.b(b),.acc(acc),.result(selected_default));
reference_vector_pe #(.ENABLE_EXTENDED_MULTIPLY(1'b0)) original_comb (
    .op(op),.a(a),.b(b),.acc(acc),.result(original_combinational));
vector_pe #(.ENABLE_EXTENDED_MULTIPLY(1'b0),.p_accumulator_preselected(1'b1)) selected_comb (
    .op(op),.a(a),.b(b),.acc(selected_acc),.result(selected_combinational));
reference_registered_vector_pe original_reg (
    .clk(clk),.i_en(i_en),.i_op(op_q),.i_a(a),.i_b(b),.i_acc(acc),.o_result(original_registered));
registered_vector_pe #(.p_accumulator_preselected(1'b1)) selected_reg (
    .clk(clk),.i_en(i_en),.i_op(op_q),.i_a(a),.i_b(b),.i_acc(selected_acc),.o_result(selected_registered));
reference_registered_vector_pe #(1'b1) positional_reference (
    .clk(clk),.i_en(i_en),.i_op(op_q),.i_a(a),.i_b(b),.i_acc(acc),.o_result(original_positional));
registered_vector_pe #(1'b1) positional_selected (
    .clk(clk),.i_en(i_en),.i_op(op_q),.i_a(a),.i_b(b),.i_acc(acc),.o_result(selected_positional));
assign default_equal = original_default == selected_default;
assign combinational_equal = original_combinational == selected_combinational;
assign registered_equal = original_registered == selected_registered;
assign positional_equal = original_positional == selected_positional;
endmodule
''')
    paths.append(wrapper)
    proofs = []
    script = out / 'combinational.ys'
    script.write_text('read_slang --top pe_comparison ' + shlex.join(map(str, paths)) + '\n'
                      'prep -top pe_comparison -flatten\n'
                      'delete w:original_registered w:selected_registered w:registered_equal '
                      'w:original_positional w:selected_positional w:positional_equal\n'
                      'opt_clean\nopt -full\n'
                      'sat -verify -prove default_equal 1 -prove combinational_equal 1 -show-inputs -show-outputs\n')
    log = script.with_suffix('.log')
    run([sys.executable, ROOT / 'scripts/fpga/open_fpga_synth.py', '--worker', script], log)
    proofs.append({'name': 'all_operation_combinational', 'passed': True, 'log_sha256': digest(log)})
    script = out / 'registered.ys'
    script.write_text('read_slang --top pe_comparison ' + shlex.join(map(str, paths)) + '\n'
                      'prep -top pe_comparison -flatten\nopt -full\n'
                      'sat -verify -seq 6 -set-at 1 i_en 1 -prove-skip 1 '
                      '-prove registered_equal 1 -prove positional_equal 1 -show-inputs -show-outputs\n')
    log = script.with_suffix('.log')
    run([sys.executable, ROOT / 'scripts/fpga/open_fpga_synth.py', '--worker', script], log)
    proofs.append({'name': 'arbitrary_mode_enable_6_cycles', 'passed': True, 'log_sha256': digest(log)})

    source = (root / ENGINE).read_text()
    case = re.search(r'case \(cfg\.op\).*?endcase', source, re.S)[0]
    hadamard = re.search(r'vector_hadamard <= cfg\.op.*?;', source)[0]
    decode = (hadamard + '\n' + case).replace('cfg.op', 'cfg_op').replace('<=', '=')
    decoder = out / 'mode_decoder.sv'
    decoder.write_text('''module mode_decoder (
    input logic [3:0] cfg_op,
    output wire equal
);
import vector_engine_pkg::*;
logic vector_hadamard;
logic [2:0] pe_op;
always_comb begin
''' + decode + '''
end
assign equal = vector_hadamard == (pe_op == PE_MUL);
endmodule
''')
    packages = [root / 'rtl/npu/conv/conv_im2col_pkg.sv', root / 'rtl/npu/conv/vector_engine_pkg.sv']
    script = out / 'mode_decoder.ys'
    script.write_text('read_slang --top mode_decoder ' + shlex.join(map(str, packages + [decoder])) + '\n'
                      'prep -top mode_decoder -flatten\nsat -verify -prove equal 1 -show-inputs -show-outputs\n')
    log = script.with_suffix('.log')
    run([sys.executable, ROOT / 'scripts/fpga/open_fpga_synth.py', '--worker', script], log)
    proofs.append({'name': 'actual_engine_operation_decode', 'passed': True, 'log_sha256': digest(log)})

    bench = out / 'four_state.sv'
    bench.write_text('''module tb;
logic clk=0, i_en=1;
logic [2:0] op=0;
logic signed [15:0] a=0, b=0;
logic signed [31:0] acc=0;
wire [31:0] original_default, selected_default, original_combinational, selected_combinational;
wire [31:0] original_registered, selected_registered;
wire [31:0] original_positional, selected_positional;
wire default_equal, combinational_equal, registered_equal, positional_equal;
pe_comparison dut (.*);
integer seed, seed_result, iteration, comb_checks=0, capture_checks=0, hold_checks=0;
logic [31:0] previous_original, previous_selected;
initial begin
    seed=32'h7a4d83c1;seed_result=$urandom(seed);
    #1;clk=1;#1;clk=0;
    for(iteration=0;iteration<65536;iteration=iteration+1) begin
        previous_original=original_registered;previous_selected=selected_registered;
        i_en=1'($urandom());op=3'($urandom());a=16'($urandom());b=16'($urandom());acc=$urandom();
        case(iteration%7)
            1: a[$urandom()%16]=1'bx;
            2: b[$urandom()%16]=1'bz;
            3: acc[$urandom()%32]=1'bx;
            4: op[$urandom()%3]=1'bx;
            5: op[$urandom()%3]=1'bz;
            6: begin a=16'h8000;b=16'hffff;acc=32'h7fffffff;end
            default: begin end
        endcase
        #1;
        if (original_default !== selected_default || original_combinational !== selected_combinational)
            $fatal(1,"combinational sample %0d",iteration);
        comb_checks=comb_checks+2;
        clk=1;#1;
        if (original_registered !== selected_registered || original_positional !== selected_positional)
            $fatal(1,"registered sample %0d",iteration);
        if (!i_en) begin
            if (original_registered !== previous_original || selected_registered !== previous_selected)
                $fatal(1,"enable hold sample %0d",iteration);
            hold_checks=hold_checks+1;
        end else capture_checks=capture_checks+1;
        clk=0;#1;
    end
    $display("VECTOR_PE_ACCUMULATOR_PASS combinational=%0d captures=%0d holds=%0d",comb_checks,capture_checks,hold_checks);
    $finish;
end
endmodule
''')
    binary = out / 'four_state.vvp'
    run([args.iverilog, '-g2012', '-s', 'tb', '-o', binary, *paths, bench], out / 'compile.log')
    run([args.vvp, binary], out / 'four_state.log')
    matched = re.search(r'VECTOR_PE_ACCUMULATOR_PASS (.*)', (out / 'four_state.log').read_text())
    assert matched is not None
    counts = {name: int(value) for name, value in re.findall(r'(\w+)=(\d+)', matched[1])}
    assert hashes == {str(path): digest(root / path) for path in (PE, ENGINE)}
    assert original_hashes == {str(path): digest(reference / path) for path in (PE, ENGINE)}
    report = {'passed': True, 'source_sha256': hashes, 'reference_sha256': original_hashes,
              'reference_revision': None if args.reference_root else args.reference_revision,
              'formal': proofs, 'strict_four_state': counts, 'test_sha256': digest(Path(__file__)),
              'simulation_log_sha256': digest(out / 'four_state.log')}
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
