#!/usr/bin/env python3
"""证明舍入加法的完整输入范围、四态行为及实际 DSP 映射结果。"""
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


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command, log):
    with log.open("w") as stream:
        subprocess.run([str(value) for value in command], cwd=ROOT,
                       stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=600)


def proof(commands, folder):
    script = folder / "proof.ys"
    script.write_text("\n".join(commands) + "\n")
    run([sys.executable, ROOT / "scripts/fpga/open_fpga_synth.py", "--worker", script],
        folder / "formal.log")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources = [ROOT / "rtl/common/parallel_prefix_add.sv",
               ROOT / "rtl/npu/writeback/requant_round_add.sv"]
    hashes = {str(path.relative_to(ROOT)): digest(path) for path in sources}
    profiles = []
    for width, low in [(2, 1), (3, 2), (16, 8), (32, 16),
                       (33, 17), (35, 17), (35, 18), (46, 23)]:
        folder = out / f"width{width}_low{low}"
        folder.mkdir(exist_ok=True)
        model = folder / "check.sv"
        model.write_text(f"""module check(input wire [{width-1}:0] a,b,
    input wire increment, output wire [{width-1}:0] actual, expected,
    output wire equal);
    requant_round_add #(.p_width({width}), .p_low_width({low})) dut(
        .i_a(a), .i_b(b), .i_increment(increment), .o_sum(actual));
    assign expected=a+b+{width}'(increment);
    assign equal=actual==expected;
endmodule
""")
        proof(["read_slang -D SYNTHESIS=1 --top check " + shlex.join(map(str, [*sources, model])),
               "setattr -mod -unset keep_hierarchy", "setattr -unset keep_hierarchy",
               "prep -top check -flatten", "opt -full",
               "sat -prove equal 1 -verify -show-inputs -show-outputs"], folder)
        bench = folder / "tb.sv"
        bench.write_text(f"""module tb;
    reg [{width-1}:0] a,b,saved_a,saved_b;
    reg increment;
    wire [{width-1}:0] actual,expected;
    wire equal;
    integer comparisons=0;
    check dut(.*);
    task verify; begin
        #1;
        if(actual !== expected) $fatal(1,"舍入加法结果不一致");
        comparisons++;
    end endtask
    initial begin
        for(integer sample=0;sample<10000;sample++) begin
            a={{$urandom,$urandom}};b={{$urandom,$urandom}};increment=sample[0];
            case(sample%5)
                0:a='0;
                1:a='1;
                2:b='0;
                3:b='1;
                default:begin end
            endcase
            verify();saved_a=a;saved_b=b;
            a[sample%{width}]=1'bx;verify();a=saved_a;
            b[sample%{width}]=1'bz;verify();b=saved_b;
            increment=1'bx;verify();
        end
        $display("ROUND_ADD_PASS comparisons=%0d",comparisons);$finish;
    end
endmodule
""")
        binary = folder / "simulation"
        run(["iverilog", "-g2012", "-s", "tb", "-o", binary, *sources, model, bench],
            folder / "compile.log")
        run(["vvp", binary], folder / "simulation.log")
        if "ROUND_ADD_PASS comparisons=40000" not in (folder / "simulation.log").read_text():
            raise RuntimeError("舍入加法四态比较未完成")
        profiles.append(dict(width=width, low_width=low, passed=True,
                             unconstrained_input_bits=2*width+1, comparisons=40000,
                             formal_log_sha256=digest(folder / "formal.log")))
    case_file = out / "cases.json"
    case_file.write_text(json.dumps({"round_add": {
        "top": "requant_round_add_measure",
        "sources": ["test/requant_compute_lane/round_add_measure.sv"],
        "options": ["-D", "SYNTHESIS=1"],
        "configuration": "完整三十五位输入、舍入位和寄存输出"
    }}, indent=2, ensure_ascii=False) + "\n")
    run([sys.executable, ROOT / "scripts/fpga/open_fpga_synth.py", "--source-root", ROOT,
         "--case-config", case_file, "--cases", "round_add", "--out", out / "mapping"],
        out / "mapping.log")
    mapped = out / "mapping/round_add/mapped.json"
    metrics = json.loads((mapped.parent / "metrics.json").read_text())
    if metrics["resources"]["dsp48e1"] != 1:
        raise RuntimeError("三十五位舍入加法未推断为一个 DSP")
    reference = out / "reference.sv"
    reference.write_text("""module reference(input wire clk,
    input wire [34:0] i_a,i_b,input wire i_increment,output reg [34:0] o_sum);
    reg [34:0] a_q,b_q;reg increment_q;
    always @(posedge clk) begin
        a_q<=i_a;b_q<=i_b;increment_q<=i_increment;
        o_sum<=a_q+b_q+35'(increment_q);
    end
endmodule
""")
    folder = out / "mapped_proof"
    folder.mkdir(exist_ok=True)
    proof(["read_slang --top reference " + shlex.quote(str(reference)),
           "prep -top reference -flatten", "rename -hide w:*", "design -stash reference",
           "read_json " + shlex.quote(str(mapped)), "delete =A:blackbox",
           "read_verilog -overwrite +/xilinx/cells_sim.v",
           "hierarchy -top requant_round_add_measure", "rename -top current",
           "setattr -mod -unset keep_hierarchy", "flatten -wb", "proc",
           "memory_map", "async2sync", "opt -full", "rename -hide w:*",
           "design -stash current", "design -copy-from reference -as reference reference",
           "design -copy-from current -as current current", "equiv_make reference current proof",
           "hierarchy -top proof", "equiv_simple -seq 4", "opt_clean",
           "equiv_induct -seq 8", "equiv_status -assert"], folder)
    if not re.search(r"Of those cells 35 are proven and 0 are unproven", (folder / "formal.log").read_text()):
        raise RuntimeError("实际映射结果的三十五位输出未全部完成证明")
    if hashes != {str(path.relative_to(ROOT)): digest(path) for path in sources}:
        raise RuntimeError("检查期间生产源码发生变化")
    result = dict(passed=True, source_sha256=hashes, profiles=profiles,
                  comparisons=sum(row["comparisons"] for row in profiles),
                  mapped_sha256=digest(mapped), mapped_output_bits=35,
                  mapped_unbounded_equivalence=True, resources=metrics["resources"],
                  longest_register_path_cells=metrics["paths"]["longest_register_path_cells"])
    (out / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
