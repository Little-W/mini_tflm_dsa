#!/usr/bin/env python3
"""验证矩阵引擎的帧完成选择，并生成用于组合级数测量的实际表达式模型。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("rtl/npu/top/npu_matrix_engine.sv")
CONTROLS = ("o_frame_mode_q", "frame_command_active", "frame_execution_started",
            "frame_compute_seen", "partial_sum_calc_over", "frame_store_seen",
            "ps_frame_complete", "frame_exec_final", "frame_output_seen",
            "frame_output_armed", "oa_calc_over")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def model(source: str, name: str) -> str:
    declarations = "logic " + ", ".join(CONTROLS) + ";\nlogic exec_oa_complete;\n"
    if "assign frame_complete_i_mode =" in source:
        declarations += "\n".join(re.findall(r"    logic frame_complete_[^;]+;", source))
        start = source.index("    assign frame_complete_i_mode =")
        body = source[start:source.index("        assign frame_command_ready =", start)]
    else:
        body = re.search(r"    assign exec_oa_complete\s*=.*?;", source, re.S).group(0)
    return f"""// 直接采用生产矩阵引擎的完成表达式与实例连接。
module {name}(input logic [10:0] i_controls, output logic o_complete);
{declarations}
    assign {{{', '.join(CONTROLS)}}} = i_controls;
{body}
    assign o_complete = exec_oa_complete;
endmodule
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", default="9e3e5d6a6f47befe6c86aceacad7999923206458")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = (ROOT / SOURCE).read_text()
    original = subprocess.check_output(["git", "show", f"{args.reference}:{SOURCE}"], cwd=ROOT, text=True)
    proof = out / "completion.sv"
    proof.write_text(model(original, "completion_reference") + model(source, "completion_current") + """
module completion_proof(input logic [10:0] i_controls, output logic o_equal);
    logic reference_result, current_result;
    completion_reference u_reference(.i_controls(i_controls), .o_complete(reference_result));
    completion_current u_current(.i_controls(i_controls), .o_complete(current_result));
    assign o_equal = reference_result === current_result;
endmodule
""")
    resolver = runpy.run_path(str(ROOT / "scripts/rtl/source_files.py"))["with_dependencies"]
    sources = resolver([proof], ROOT)
    script, log = out / "proof.ys", out / "proof.log"
    script.write_text(shlex.join(["read_slang", "--top", "completion_proof", *map(str, sources)]) +
        "\nprep -top completion_proof -flatten\nsat -verify -prove o_equal 1\n")
    with log.open("w") as stream:
        subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
            "--worker", str(script)], stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=120)
    if "SUCCESS!" not in log.read_text():
        raise RuntimeError("帧完成条件形式证明未完成")
    bench = out / "tb.sv"
    bench.write_text("""// 枚举全部十一位控制输入的 0、1、X、Z 组合。
module tb;
    logic [10:0] controls;
    logic equal_result;
    completion_proof u_proof(.i_controls(controls), .o_equal(equal_result));
    function automatic logic four_state(input logic [1:0] value);
        case (value)
            2'd0: four_state=1'b0;
            2'd1: four_state=1'b1;
            2'd2: four_state=1'bx;
            2'd3: four_state=1'bz;
        endcase
    endfunction
    initial begin
        for (integer pattern=0;pattern<4194304;pattern++) begin
            for (integer bit_index=0;bit_index<11;bit_index++)
                controls[bit_index]=four_state(2'(pattern >> (2*bit_index)));
            #1;
            if (equal_result!==1'b1) $fatal(1,"Completion differs controls=%b",controls);
        end
        $display("MATRIX_FRAME_COMPLETE_PASS checks=4194304");
        $finish;
    end
endmodule
""")
    binary = out / "four_state.vvp"
    with (out / "compile.log").open("w") as stream:
        subprocess.run(["iverilog", "-g2012", "-s", "tb", "-o", str(binary),
            *map(str, sources), str(bench)], stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=120)
    result = subprocess.run(["vvp", str(binary)], capture_output=True, text=True, check=True, timeout=300)
    (out / "run.log").write_text(result.stdout + result.stderr)
    if "MATRIX_FRAME_COMPLETE_PASS checks=4194304" not in result.stdout:
        raise RuntimeError("帧完成条件四态枚举未完成")
    if source != (ROOT / SOURCE).read_text():
        raise RuntimeError("检查期间矩阵引擎发生变化")
    report = {"passed": True, "reference": args.reference, "input_constraints": None,
              "source_sha256": {str(SOURCE): digest(ROOT / SOURCE),
                "rtl/npu/top/npu_frame_complete_select.sv": digest(ROOT / "rtl/npu/top/npu_frame_complete_select.sv")},
              "formal_proven": True, "four_state_checks": 4194304,
              "formal_log_sha256": digest(log), "simulation_log_sha256": digest(out / "run.log")}
    (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
