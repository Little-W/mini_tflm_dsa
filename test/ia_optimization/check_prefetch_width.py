#!/usr/bin/env python3
"""证明预取尾部宽度与范围判断，并比较已知值及 X/Z 输入。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = "rtl/npu/loaders/ia_loader.sv"
CASES = ((8, 2), (8, 8), (32, 16), (64, 32), (32, 3))


def extract(source, name):
    first = source.index("    logic [REG_WIDTH-1:0] next_cols_inverse")
    last = source.index("\n\n    always_ff", first)
    return f"""module {name} #(
    parameter int unsigned REG_WIDTH=32, SIZE=16
) (
    input logic [REG_WIDTH-1:0] cfg_global_reduction, cfg_q0_base,
    output logic [REG_WIDTH-1:0] next_cols_comb
);
    localparam int LOG2_SIZE=$clog2(SIZE);
    localparam bit p_parallel_prefetch_tail =
        (SIZE > 1) && ((SIZE & (SIZE - 1)) == 0) && (REG_WIDTH > LOG2_SIZE);
    logic [REG_WIDTH-1:0] next_remaining_cols;
""" + source[first:last] + "\nendmodule\n"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract_range(source, name):
    first = source.index("    logic [REG_WIDTH-1:0] next_q0;")
    last = source.index("    wire [REG_WIDTH-1:0] next_beats", first)
    body = source[first:last]
    if "logic prefetch_next_in_range;" in body:
        body = body.replace("    logic prefetch_next_in_range;\n", "")
    else:
        body += "    assign prefetch_next_in_range = (next_q0 > q0_base_q) && (next_q0 < global_reduction_q);\n"
    return f"""module {name} #(
    parameter int unsigned REG_WIDTH=32, SIZE=16
) (
    input logic [REG_WIDTH-1:0] global_reduction_q, q0_base_q,
    output logic prefetch_next_in_range
);
    localparam int LOG2_SIZE=$clog2(SIZE);
    localparam bit p_parallel_prefetch_tail =
        (SIZE > 1) && ((SIZE & (SIZE - 1)) == 0) && (REG_WIDTH > LOG2_SIZE);
""" + body + "\nendmodule\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference", default="7ddc0d8d")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference = subprocess.check_output(["git", "show", f"{args.reference}:{SOURCE}"],
                                        cwd=ROOT, text=True)
    current = (ROOT / SOURCE).read_text()
    design = out / "prefetch_width.sv"
    design.write_text(extract(reference, "reference_width") + extract(current, "current_width") +
                      extract_range(reference, "reference_range") + extract_range(current, "current_range") + """
module miter #(parameter int unsigned REG_WIDTH=32, SIZE=16)(
    input logic [REG_WIDTH-1:0] cfg_global_reduction, cfg_q0_base,
    output logic o_equal
);
    wire [REG_WIDTH-1:0] reference_value, current_value;
    wire reference_in_range, current_in_range;
    reference_width #(.REG_WIDTH(REG_WIDTH), .SIZE(SIZE)) u_reference(
        .cfg_global_reduction, .cfg_q0_base, .next_cols_comb(reference_value));
    current_width #(.REG_WIDTH(REG_WIDTH), .SIZE(SIZE)) u_current(
        .cfg_global_reduction, .cfg_q0_base, .next_cols_comb(current_value));
    reference_range #(.REG_WIDTH(REG_WIDTH), .SIZE(SIZE)) u_reference_range(
        .global_reduction_q(cfg_global_reduction), .q0_base_q(cfg_q0_base),
        .prefetch_next_in_range(reference_in_range));
    current_range #(.REG_WIDTH(REG_WIDTH), .SIZE(SIZE)) u_current_range(
        .global_reduction_q(cfg_global_reduction), .q0_base_q(cfg_q0_base),
        .prefetch_next_in_range(current_in_range));
    assign o_equal = (reference_value == current_value) && (reference_in_range == current_in_range);
endmodule
""")
    bench = out / "tb.sv"
    bench.write_text("""module tb;
    parameter integer REG_WIDTH=32, SIZE=16;
    reg [REG_WIDTH-1:0] cfg_global_reduction, cfg_q0_base;
    wire [REG_WIDTH-1:0] reference_value, current_value;
    wire reference_in_range, current_in_range;
    reg [31:0] random_state=32'd20261125;
    integer checks=0;
    reference_width #(.REG_WIDTH(REG_WIDTH), .SIZE(SIZE)) u_reference(
        .cfg_global_reduction, .cfg_q0_base, .next_cols_comb(reference_value));
    current_width #(.REG_WIDTH(REG_WIDTH), .SIZE(SIZE)) u_current(
        .cfg_global_reduction, .cfg_q0_base, .next_cols_comb(current_value));
    reference_range #(.REG_WIDTH(REG_WIDTH), .SIZE(SIZE)) u_reference_range(
        .global_reduction_q(cfg_global_reduction), .q0_base_q(cfg_q0_base),
        .prefetch_next_in_range(reference_in_range));
    current_range #(.REG_WIDTH(REG_WIDTH), .SIZE(SIZE)) u_current_range(
        .global_reduction_q(cfg_global_reduction), .q0_base_q(cfg_q0_base),
        .prefetch_next_in_range(current_in_range));
    function automatic [31:0] random_word;
        begin
            random_state = random_state ^ (random_state << 13);
            random_state = random_state ^ (random_state >> 17);
            random_state = random_state ^ (random_state << 5);
            random_word = random_state;
        end
    endfunction
    task check;
        begin
            #1;
            if (reference_value !== current_value)
                $fatal(1, "Prefetch width differs: reduction=%h offset=%h ref=%h current=%h",
                    cfg_global_reduction, cfg_q0_base, reference_value, current_value);
            if (reference_in_range !== current_in_range)
                $fatal(1, "Prefetch range differs: reduction=%h offset=%h",cfg_global_reduction,cfg_q0_base);
            checks = checks + 1;
        end
    endtask
    initial begin
        for (integer i=0; i<64; i=i+1) begin
            for (integer j=0; j<64; j=j+1) begin
                cfg_global_reduction = REG_WIDTH'(i);
                cfg_q0_base = REG_WIDTH'(j);
                check();
                cfg_global_reduction = ~REG_WIDTH'(i);
                cfg_q0_base = ~REG_WIDTH'(j);
                check();
            end
        end
        for (integer i=0; i<20000; i=i+1) begin
            cfg_global_reduction = REG_WIDTH'({random_word(),random_word()});
            cfg_q0_base = REG_WIDTH'({random_word(),random_word()});
            check();
            if (i%2 == 0) cfg_global_reduction[random_word()%REG_WIDTH] = 1'bx;
            else cfg_q0_base[random_word()%REG_WIDTH] = 1'bz;
            if (i%3 == 0) cfg_q0_base[random_word()%REG_WIDTH] = 1'bx;
            check();
        end
        $display("PASS checks=%0d", checks);
        $finish;
    end
endmodule
""")
    common = [ROOT / "rtl/common/parallel_prefix_add.sv", ROOT / "rtl/common/add_equal.sv",
              ROOT / "rtl/common/parallel_unsigned_compare.sv"]
    hashes = {SOURCE: hashlib.sha256(current.encode()).hexdigest(),
              **{str(path.relative_to(ROOT)): digest(path) for path in common}}
    report = dict(passed=False, source_sha256=hashes,
                  reference_sha256=hashlib.sha256(reference.encode()).hexdigest(), seed=20261125, runs=[])
    for width, size in CASES:
        label = f"w{width}_s{size}"
        script, log = out / (label + ".ys"), out / (label + "_formal.log")
        commands = [shlex.join(["read_slang", "--top", "miter", f"-GREG_WIDTH={width}",
                               f"-GSIZE={size}", str(design), *map(str, common)]),
                    "prep -top miter -flatten", "sat -verify -prove o_equal 1 -show-inputs -show-outputs"]
        script.write_text("\n".join(commands) + "\n")
        with log.open("w") as stream:
            subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                            "--worker", str(script)], cwd=ROOT, stdout=stream,
                           stderr=subprocess.STDOUT, check=True)
        binary = out / (label + ".vvp")
        with (out / (label + "_compile.log")).open("w") as stream:
            subprocess.run(["iverilog", "-g2012", "-s", "tb", f"-Ptb.REG_WIDTH={width}",
                            f"-Ptb.SIZE={size}", "-o", str(binary), str(bench), str(design),
                            *map(str, common)], cwd=ROOT, stdout=stream,
                           stderr=subprocess.STDOUT, check=True)
        simulation = subprocess.check_output(["vvp", str(binary)], text=True)
        (out / (label + "_four_state.log")).write_text(simulation)
        record = dict(width=width, size=size, formal_passed="SUCCESS!" in log.read_text(),
                      four_state_passed="PASS checks=48192" in simulation,
                      four_state_vectors=48192, four_state_comparisons=96384)
        report["runs"].append(record)
        report["passed"] = all(r["formal_passed"] and r["four_state_passed"] for r in report["runs"])
        (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(record), flush=True)
        if not report["passed"]:
            raise RuntimeError("Prefetch arithmetic verification did not complete")
    if hashes != {SOURCE: digest(ROOT / SOURCE),
                  **{str(path.relative_to(ROOT)): digest(path) for path in common}}:
        raise RuntimeError("RTL changed during prefetch verification")


if __name__ == "__main__":
    main()
