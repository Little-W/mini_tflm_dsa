#!/usr/bin/env python3
"""使用器件完整功能模型证明映射电路的所有结果位与周期。"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

import pyosys

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mapped", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    mapped, out = args.mapped.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((mapped / "manifest.json").read_text())
    parameters = manifest["parameters"]
    for name, value in parameters.items():
        if f"-G{name}={value}" not in manifest["options"]:
            raise RuntimeError("综合参数没有显式写入命令：" + name)
    width, carry = parameters["WIDTH"], parameters["CARRY"]
    if (mapped / "mapped.v").is_file():
        data = (mapped / "mapped.v").read_bytes()
    else:
        data = gzip.decompress((mapped / "mapped.v.gz").read_bytes())
    (out / "mapped.v").write_bytes(data)
    reference = out / "reference.sv"
    reference.write_text(f"""module reference(input logic i_clk,
input logic [{width-1}:0] i_a,i_b,input logic i_carry,output logic [{width}:0] o_sum);
logic [{width-1}:0] saved_a,saved_b;logic saved_carry,selected_carry;
assign selected_carry={carry}<0?saved_carry:({carry}!=0);
always_ff @(posedge i_clk)begin
 saved_a<=i_a;saved_b<=i_b;saved_carry<=i_carry;
 o_sum<={{1'b0,saved_a}}+{{1'b0,saved_b}}+{width+1}'(selected_carry);
end
endmodule
""")
    commands = [f"read_slang --top reference {reference}", "prep -top reference -flatten",
                "opt -full", "rename -hide w:*", "design -stash reference",
                "read_verilog " + str(out / "mapped.v"),
                "read_verilog -overwrite +/xilinx/cells_sim.v",
                "hierarchy -top parallel_high_carry_measure", "rename -top current",
                "setattr -mod -unset keep_hierarchy", "flatten -wb", "proc",
                "memory_map", "async2sync", "opt -full", "rename -hide w:*",
                "design -stash current", "design -copy-from reference -as reference reference",
                "design -copy-from current -as current current",
                "equiv_make reference current proof", "hierarchy -top proof",
                "equiv_simple -seq 4", "opt_clean", "equiv_induct -seq 8",
                "equiv_status -assert"]
    script, log = out / "proof.ys", out / "proof.log"
    script.write_text("\n".join(commands) + "\n")
    with log.open("w") as stream:
        subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                        "--worker", str(script)], stdout=stream, stderr=subprocess.STDOUT,
                       check=True, timeout=300)
    if not re.search(rf"Of those cells {width+1} are proven and 0 are unproven", log.read_text()):
        raise RuntimeError("映射电路的完整结果证明未完成")
    metrics = json.loads((mapped / "metrics.json").read_text())
    library = Path(pyosys.__file__).parent / "share/xilinx/cells_sim.v"
    report = dict(passed=True, unbounded_equivalence=True, compared_bits=width+1,
                  parameters=parameters, external_input_assumptions=[],
                  mapped_verilog_sha256=hashlib.sha256(data).hexdigest(),
                  source_sha256=manifest["sources_sha256"], model_sha256=digest(library),
                  proof_script_sha256=digest(script), proof_log_sha256=digest(log),
                  resources=metrics["resources"],
                  longest_register_path_cells=metrics["paths"]["longest_register_path_cells"])
    (out / "summary.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(dict(passed=True, compared_bits=width+1,
                         longest_register_path_cells=report["longest_register_path_cells"])))


if __name__ == "__main__":
    main()
