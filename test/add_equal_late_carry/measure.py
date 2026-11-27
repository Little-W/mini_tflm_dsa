#!/usr/bin/env python3
"""测量末级进位比较的完整输入路径，以及卷积数据字低位加法至比较结果的路径。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("rtl/common/add_equal.sv")
REFERENCE = "9e3e5d6a6f47befe6c86aceacad7999923206458"
sys.path.insert(0, str(ROOT / "scripts/fpga"))
from netlist_metrics import connected_paths, register_origins


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference = out / "reference.sv"
    reference.write_text(subprocess.check_output(
        ["git", "show", f"{REFERENCE}:{SOURCE}"], cwd=ROOT, text=True
    ).replace("module add_equal #(", "module add_equal_reference #("))
    resolver = runpy.run_path(str(ROOT / "scripts/rtl/source_files.py"))["with_dependencies"]
    cases, hashes, settings = {}, {}, {}
    for word_shift in (3, 4):
        for scope in ("carry", "word"):
            for variant in ("reference", "default", "late_kept", "late_free"):
                width = 32-word_shift
                name = f"{scope}{width}_{variant}"
                top = "registered_match"
                options = f".p_width({width}), .p_preserve_bits(1'b1)"
                if variant.startswith("late"):
                    options += f", .p_late_carry(1'b1), .p_keep_bits(1'b{int(variant == 'late_kept')})"
                data_width = width if scope == "carry" else 32
                expression = "" if scope == "carry" else f"""
    logic [{word_shift}:0] low_sum;
    assign low_sum = {{1'b0,a_q[{word_shift-1}:0]}} + {{1'b0,b_q[{word_shift-1}:0]}};
"""
                operand = lambda field: field + "_q" if scope == "carry" else f"{field}_q[31:{word_shift}]"
                carry = "carry_q" if scope == "carry" else f"low_sum[{word_shift}]"
                model = out / (name + ".sv")
                model.write_text(f"""// 比较实例与生产数据字匹配采用相同的层次边界，全部输入及结果由寄存器限定。
module {top} (
    input logic clk, // 测量时钟
    input logic [{data_width-1}:0] i_a, // 完整第一操作数
    input logic [{data_width-1}:0] i_b, // 完整第二操作数
    input logic [{data_width-1}:0] i_target, // 完整比较目标
    input logic i_carry, // 独立输入进位
    output logic o_equal // 保存的比较结果
);
    logic [{data_width-1}:0] a_q, b_q, target_q;
    logic carry_q, equal_value;
    always_ff @(posedge clk) begin
        a_q <= i_a; b_q <= i_b; target_q <= i_target; carry_q <= i_carry;
        o_equal <= equal_value;
    end
{expression}
    (* keep_hierarchy = "yes" *)
    {"add_equal_reference" if variant == "reference" else "add_equal"} #({options}) u_match (
        .i_a({operand('a')}), .i_b({operand('b')}), .i_target({operand('target')}),
        .i_carry_in({carry}), .o_equal(equal_value));
endmodule
""")
                implementation = reference if variant == "reference" else ROOT / SOURCE
                sources = resolver([model, implementation], ROOT)
                hashes.update({str(path): digest(path) for path in sources})
                cases[name] = {"top": top, "sources": list(map(str, sources)),
                    "options": ["-DSYNTHESIS=1", "-DXILINX_FPGA=1"],
                    "configuration": f"{width} 位比较，{scope} 输入路径，{variant} 结构"}
                settings[name] = {"width": width, "word_shift": word_shift,
                                  "scope": scope, "variant": variant}
    case_file = out / "cases.json"
    case_file.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n")
    with (out / "synthesis.log").open("w") as stream:
        subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
            "--case-config", str(case_file), "--cases", *cases, "--through", "pre_lut",
            "--out", str(out / "pre")], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
    report = {"reference_commit": REFERENCE, "source_sha256": hashes, "cases": {}}
    for name, case in cases.items():
        mapped = out / "mapped" / name
        with (out / (name + ".log")).open("w") as stream:
            subprocess.run([sys.executable, str(ROOT / "scripts/fpga/remap_fpga_luts.py"),
                "--source", str(out / "pre" / name), "--out", str(mapped), "--mode", "physical-cost",
                "--delay-target-ps", "6667", "--max-lut-inputs", "8", "--small-lut-area-cost", "1",
                "--discard-abc9-temporaries"], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
        module = json.loads((mapped / "mapped.json").read_text())["modules"][case["top"]]
        for cell, origin in register_origins(out / "pre" / name / "pre_lut.il", case["top"]).items():
            if cell in module["cells"]:
                module["cells"][cell].setdefault("attributes", {})["fpga_register_origin"] = origin
        setting = settings[name]

        def carry_source(cell_name, cell, port):
            origin = cell.get("attributes", {}).get("fpga_register_origin", "")
            if setting["scope"] == "carry":
                return origin == "carry_q"
            return origin in {f"{operand}_q [{bit}]" for operand in ("a", "b")
                              for bit in range(setting["word_shift"])}

        paths = connected_paths(module, limit=1, group_limit=1, root_filter=carry_source)
        metrics = json.loads((mapped / "metrics.json").read_text())
        if not paths["graph_complete"] or not paths["register_to_register_paths"] or \
                not metrics["paths"]["graph_complete"]:
            raise RuntimeError("进位比较路径分析不完整")
        report["cases"][name] = {**setting, "resources": metrics["resources"],
            "all_input_maximum_cells": metrics["paths"]["longest_register_path_cells"],
            "carry_maximum_cells": paths["longest_register_path_cells"],
            "carry_paths": paths}
        print(name, "LUT", metrics["resources"]["logic_lut_cells"],
              "all", metrics["paths"]["longest_register_path_cells"],
              "carry", paths["longest_register_path_cells"], flush=True)
    if hashes != {path: digest(Path(path)) for path in hashes}:
        raise RuntimeError("综合测量期间输入文件发生变化")
    (out / "measurement.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
