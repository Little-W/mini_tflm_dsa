#!/usr/bin/env python3
"""检查矩阵偏置保存与计算快照的时序等价和四态行为。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = "rtl/npu/top/npu_matrix_engine.sv"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract(source, name):
    start = source.index(";", source.index("    assign capture_compute_bias =")) + 1
    stop = source.index("  genvar cb_i;", start)
    body = source[start:stop]
    declaration = ("    logic signed [31:0] bias_capture_data [p_size];\n"
                   if "bias_capture_data" in body else "")
    return f"""module {name} #(parameter int unsigned p_size=16) (
    input logic clk, rst_n, init_cfg_bias, bias_group_valid, capture_compute_bias,
    input logic [32*p_size-1:0] i_bias_data,
    output wire [32*p_size-1:0] o_hold, o_capture
);
    wire signed [31:0] bias_data_out [p_size];
    logic signed [31:0] bias_data_hold [p_size], compute_bias_latched [p_size];
    for (genvar lane=0; lane<p_size; lane++) begin : g_port
        assign bias_data_out[lane] = i_bias_data[32*lane+:32];
        assign o_hold[32*lane+:32] = bias_data_hold[lane];
        assign o_capture[32*lane+:32] = compute_bias_latched[lane];
    end
""" + declaration + body + "\nendmodule\n"


BENCH = """module tb;
    parameter integer p_size=16;
    logic clk=0, rst_n=0, next_reset, init_cfg_bias=0, bias_group_valid=0, capture_compute_bias=0;
    logic signed [31:0] bias_data_out [p_size];
    wire [32*p_size-1:0] ref_hold, ref_capture, dut_hold, dut_capture, packed_bias;
    for (genvar lane=0; lane<p_size; lane++) begin : g_pack
        assign packed_bias[32*lane+:32] = bias_data_out[lane];
    end
    integer known_nonzero=0, unknown_controls=0;
    reference #(.p_size(p_size)) u_reference (
        .clk, .rst_n, .init_cfg_bias, .bias_group_valid, .capture_compute_bias,
        .i_bias_data(packed_bias), .o_hold(ref_hold), .o_capture(ref_capture));
    current #(.p_size(p_size)) u_current (
        .clk, .rst_n, .init_cfg_bias, .bias_group_valid, .capture_compute_bias,
        .i_bias_data(packed_bias), .o_hold(dut_hold), .o_capture(dut_capture));
    function automatic logic control_value(input integer value);
        case (value & 15)
            0: control_value=1'bx;
            1: control_value=1'bz;
            default: control_value=value[4];
        endcase
    endfunction
    task automatic compare(input integer cycle);
        for (integer lane=0; lane<p_size; lane=lane+1) begin
            if (ref_hold[32*lane+:32] !== dut_hold[32*lane+:32] ||
                ref_capture[32*lane+:32] !== dut_capture[32*lane+:32])
                $fatal(1,"bias storage mismatch cycle=%0d lane=%0d",cycle,lane);
            if ((^dut_capture[32*lane+:32]) !== 1'bx && dut_capture[32*lane+:32] != 0)
                known_nonzero=known_nonzero+1;
        end
    endtask
    initial begin
        for (integer lane=0; lane<p_size; lane=lane+1) bias_data_out[lane]='0;
        #2; clk=1; #2; compare(-1); clk=0;
        for (integer cycle=0; cycle<20003; cycle=cycle+1) begin
            next_reset=cycle%43 == 0 ? 1'b0 : 1'b1;
            if (cycle%101 == 0) next_reset=control_value($urandom);
            init_cfg_bias=control_value($urandom);
            bias_group_valid=control_value($urandom);
            capture_compute_bias=control_value($urandom);
            if ((^{next_reset,init_cfg_bias,bias_group_valid,capture_compute_bias}) === 1'bx)
                unknown_controls=unknown_controls+1;
            for (integer lane=0; lane<p_size; lane=lane+1) begin
                bias_data_out[lane]=$urandom;
                case ($urandom_range(0,31))
                    0: bias_data_out[lane]='x;
                    1: bias_data_out[lane]='z;
                    2: bias_data_out[lane][15:8]='x;
                    3: bias_data_out[lane][31:24]='z;
                    default: ;
                endcase
            end
            // 数据和资格位先稳定，再施加复位或时钟边沿。
            #2; rst_n=next_reset; #2; compare(cycle); clk=1; #2; compare(cycle); clk=0;
        end
        if (known_nonzero<100 || unknown_controls<100)
            $fatal(1,"insufficient known-data or four-state coverage");
        $display("MATRIX_BIAS_PASS size=%0d cycles=20003 known_nonzero=%0d unknown_controls=%0d",
                 p_size,known_nonzero,unknown_controls);
        $finish;
    end
endmodule
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-ref", default="f3e85795")
    parser.add_argument("--reference-rtl", type=Path)
    parser.add_argument("--rtl", type=Path, default=ROOT / SOURCE)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    original = (args.reference_rtl.read_text() if args.reference_rtl else
                subprocess.check_output(["git", "show", args.reference_ref + ":" + SOURCE],
                                        cwd=ROOT, text=True))
    current_source = args.rtl.read_text()
    source_hash = sha(args.rtl)
    reference, current, bench = out / "reference.sv", out / "current.sv", out / "tb.sv"
    reference.write_text(extract(original, "reference"))
    current.write_text(extract(current_source, "current"))
    bench.write_text(BENCH)
    summary = dict(passed=False, inputs_constrained=False, state_updates_extracted_verbatim=True,
                   reference_sha256=hashlib.sha256(original.encode()).hexdigest(),
                   source_sha256=source_hash, source_path=str(args.rtl.resolve()), runs=[])
    for size in (1, 3, 16, 32):
        folder = out / f"size{size}"
        folder.mkdir(exist_ok=True)
        script = folder / "formal.ys"
        commands = []
        for name, source in (("reference", reference), ("current", current)):
            commands += [f"read_slang --top {name} -Gp_size={size} {source}",
                         f"prep -top {name} -flatten", "async2sync", "opt -full",
                         f"design -stash {name}"]
        commands += ["design -copy-from reference -as reference reference",
                     "design -copy-from current -as current current",
                     "equiv_make reference current proof", "hierarchy -top proof",
                     "equiv_simple -seq 2", "opt_clean", "equiv_induct -seq 3",
                     "equiv_status -assert"]
        script.write_text("\n".join(commands) + "\n")
        formal_log = folder / "formal.log"
        with formal_log.open("w") as log:
            result = subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                                     "--worker", str(script)], cwd=ROOT,
                                    stdout=log, stderr=subprocess.STDOUT)
        match = re.search(r"Of those cells (\d+) are proven and 0 are unproven", formal_log.read_text())
        if result.returncode or not match:
            raise RuntimeError(formal_log.read_text()[-8000:])
        binary = folder / "four_state.vvp"
        compile_log = folder / "compile.log"
        with compile_log.open("w") as log:
            subprocess.run(["iverilog", "-g2012", "-s", "tb", f"-Ptb.p_size={size}",
                            "-o", str(binary), str(reference), str(current), str(bench)],
                           cwd=ROOT, check=True, stdout=log, stderr=subprocess.STDOUT)
        result = subprocess.run(["vvp", str(binary)], cwd=ROOT, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (folder / "four_state.log").write_text(result.stdout)
        if result.returncode or "MATRIX_BIAS_PASS" not in result.stdout:
            raise RuntimeError(result.stdout)
        counters = {key: int(value) for key, value in re.findall(r"(\w+)=(\d+)", result.stdout)}
        record = dict(size=size, formal_equivalent_bits=int(match[1]), four_state=counters,
                      formal_log_sha256=sha(formal_log), passed=True)
        summary["runs"].append(record)
        print(json.dumps(record), flush=True)
    if source_hash != sha(args.rtl):
        raise RuntimeError("Source changed during verification")
    summary["passed"] = True
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    main()
