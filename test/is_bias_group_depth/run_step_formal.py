#!/usr/bin/env python3
"""提取实际组间地址更新逻辑，证明任意输入下的回绕与尾组判断。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "test"))
from rtl_reference import read_rtl_source

TOP = Path("rtl/npu/top/npu_top.sv")
PORTS = """
    input logic [REG_WIDTH-1:0] is_bias_group_base, is_bias_last_group_base,
    input logic [IS_BIAS_VALID_W-1:0] is_bias_rows_valid,
    input logic [IS_BIAS_VALID_W-1:0] is_bias_last_rows, is_bias_group_rows_target
"""
PARAMETERS = "parameter int REG_WIDTH=32, IS_BIAS_VALID_W=10"


def extract(text: str, name: str) -> str:
    first = text.index("        wire [REG_WIDTH-1:0] is_bias_group_base_plus")
    last = text.index("    wire signed [31:0] is_bias_scalar =", first)
    return f"module {name} #({PARAMETERS}) (\n{PORTS},\n" + """
    output logic [2*REG_WIDTH+IS_BIAS_VALID_W+1:0] o_result
);
""" + text[first:last] + """
    assign o_result = {is_bias_group_base_plus, is_bias_group_wrap_step,
        is_bias_group_base_step, is_bias_group_step_is_last, is_bias_rows_valid_step};
endmodule
"""


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference", default="415a70a")
    parser.add_argument("--reference-root", type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference = ((args.reference_root / TOP).read_text() if args.reference_root else
                 read_rtl_source(f"{args.reference}:{TOP}", cwd=ROOT, text=True))
    candidate = (ROOT / TOP).read_text()
    for label, source in (("reference", reference), ("candidate", candidate)):
        (out / (label + ".sv")).write_text(extract(source, label))
    formal = out / "formal.sv"
    formal.write_text(f"module bias_step_formal #({PARAMETERS}) (\n{PORTS},\n" + """
    output logic o_equal
);
    logic [2*REG_WIDTH+IS_BIAS_VALID_W+1:0] reference_result, candidate_result;
    reference #(.REG_WIDTH(REG_WIDTH), .IS_BIAS_VALID_W(IS_BIAS_VALID_W))
        u_reference (.*, .o_result(reference_result));
    candidate #(.REG_WIDTH(REG_WIDTH), .IS_BIAS_VALID_W(IS_BIAS_VALID_W))
        u_candidate (.*, .o_result(candidate_result));
    assign o_equal = reference_result == candidate_result;
endmodule
""")
    sources = [out / "reference.sv", out / "candidate.sv", formal,
               ROOT / "rtl/common/unsigned_compare.sv"]
    profiles = [(1, 1), (4, 1), (8, 4), (16, 8), (17, 10), (24, 10),
                (32, 1), (32, 5), (32, 10), (32, 32), (40, 10), (47, 16),
                (48, 16), (64, 10), (64, 32)]
    report = dict(reference=str(args.reference_root) if args.reference_root else args.reference,
                  source_sha256={str(TOP): digest(ROOT / TOP)},
                  reference_source_sha256=hashlib.sha256(reference.encode()).hexdigest(),
                  inputs_constrained=False, runs=[])
    for width, count in profiles:
        for fpga in (False, True):
            folder = out / f"w{width}_c{count}_fpga{int(fpga)}"
            folder.mkdir(exist_ok=True)
            script, log = folder / "run.ys", folder / "formal.log"
            script.write_text("read_slang --top bias_step_formal " +
                              ("-DXILINX_FPGA=1 " if fpga else "") +
                              f"-GREG_WIDTH={width} -GIS_BIAS_VALID_W={count} " +
                              shlex.join(map(str, sources)) +
                              "\nprep -top bias_step_formal -flatten\ncheck -assert\n" +
                              "sat -verify -prove o_equal 1 -show-inputs -show-outputs\n")
            with log.open("w") as stream:
                subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                                "--worker", str(script)], stdout=stream, stderr=subprocess.STDOUT,
                               check=True, timeout=120)
            if "SAT proof finished - no model found: SUCCESS!" not in log.read_text():
                raise RuntimeError(f"组间地址证明未完成：{log}")
            item = dict(width=width, count_bits=count, fpga=fpga, passed=True,
                        log_sha256=digest(log))
            report["runs"].append(item)
            print(json.dumps(item), flush=True)
    report["passed"] = True
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
