#!/usr/bin/env python3
"""证明接收数量的完整回绕等式，并生成寄存器之间的面积与路径测量。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("rtl/npu/conv/vector_engine.sv")
DECLARATIONS = """  logic [31:0] window_count_i_value, window_count_i_increment, window_count_i_target;
  logic window_count_i_carry, window_count_o_equal;
"""


def normalize(source):
    return re.sub(r"\s+", "", re.sub(r"/\*.*?\*/|//[^\n]*", "", source, flags=re.S))


def unit(block, name, width, registered):
    header = f"""module {name}(input logic clk,
input logic [31:0] i_count, input logic [2:0] i_increment,
input logic [{width-1}:0] i_target, output logic o_equal);
logic [31:0] window_received;
logic [2:0] window_response_count;
logic [{width-1}:0] active;
logic equal_value;
"""
    capture = """always_ff @(posedge clk) begin
  window_received <= i_count;
  window_response_count <= i_increment;
  active <= i_target;
  o_equal <= equal_value;
end
""" if registered else """assign window_received = i_count;
assign window_response_count = i_increment;
assign active = i_target;
assign o_equal = equal_value;
"""
    return header + DECLARATIONS + capture + block + "\nendmodule\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference", default="b430b80d")
    parser.add_argument("--synthesis", action="store_true")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = (ROOT / SOURCE).read_text()
    reference = read_rtl_source(f"{args.reference}:{SOURCE}", cwd=ROOT, text=True)
    first = current.index("  // 完成条件逐位检查所需进位")
    last = current.index("  logic next_window_valid;", first)
    actual = current[first:last]
    restored = current.replace(DECLARATIONS, "", 1).replace(actual, "", 1)
    restored = restored.replace("(win_rsp_error || !window_count_o_equal)",
                                "(win_rsp_error || window_received+32'(window_response_count)!=active)", 1)
    if normalize(restored) != normalize(reference):
        raise RuntimeError("存在接收完成条件以外的修改")
    actual += "assign equal_value = window_count_o_equal;\n"
    original = "assign equal_value = window_received + 32'(window_response_count) == 32'(active);\n"
    helper = ROOT / "rtl/common/add_equal.sv"
    report = {"source_sha256": hashlib.sha256(current.encode()).hexdigest(),
              "reference_commit": subprocess.check_output(["git", "rev-parse", args.reference], cwd=ROOT, text=True).strip(),
              "helper_sha256": hashlib.sha256(helper.read_bytes()).hexdigest(),
              "inputs_constrained": False, "only_completion_condition_changed": True, "checks": []}
    for width in (1, 2, 5, 6, 7):
        folder = out / f"width{width}"
        folder.mkdir(exist_ok=True)
        proof = folder / "proof.sv"
        proof.write_text(unit(original, "reference_count", width, False) +
                         unit(actual, "current_count", width, False) + f"""
module count_proof(input logic clk,input logic [31:0] i_count,
input logic [2:0] i_increment,input logic [{width-1}:0] i_target,
output logic equivalent);
logic reference_equal,current_equal;
reference_count u_reference(.*,.o_equal(reference_equal));
current_count u_current(.*,.o_equal(current_equal));
assign equivalent = reference_equal == current_equal;
endmodule
""")
        script = folder / "run.ys"
        script.write_text("read_slang --top count_proof " +
                          " ".join(shlex.quote(str(p)) for p in (proof, helper)) +
                          "\nprep -top count_proof -flatten\nsat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
        log = folder / "formal.log"
        with log.open("w") as stream:
            subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"), "--worker", str(script)],
                           cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
        if "SUCCESS!" not in log.read_text():
            raise RuntimeError("完成数量形式比较未通过")
        report["checks"].append({"active_width": width, "passed": True,
                                  "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest()})
    if args.synthesis:
        cases = {}
        for label, block in (("reference", original), ("current", actual)):
            path = out / f"{label}.sv"
            path.write_text(unit(block, "registered_count", 5, True))
            cases[label] = {"top": "registered_count", "options": [],
                            "sources": [str(path), str(helper)],
                            "configuration": "32-bit received count, 3-bit increment, 5-bit active count"}
        config = out / "cases.json"
        config.write_text(json.dumps(cases, indent=2) + "\n")
        subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                        "--case-config", str(config), "--cases", "reference", "current",
                        "--out", str(out / "synthesis")], cwd=ROOT, check=True)
        report["synthesis"] = {label: json.loads((out / "synthesis" / label / "metrics.json").read_text())
                               for label in ("reference", "current")}
    report["passed"] = True
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"passed": True, "checks": len(report["checks"])}), flush=True)


if __name__ == "__main__":
    main()
