#!/usr/bin/env python3
"""按前端的原位置更新规则证明完整描述符公开输出及对应状态等价。"""
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
RTL = Path("rtl/npu/conv/conv_im2col_descriptor.sv")
PROFILES = (
    {"p_size": 16, "p_slot_w": 5, "p_lanes": 8, "p_line_bytes": 128, "p_register_descriptor": 0},
    {"p_size": 16, "p_slot_w": 5, "p_lanes": 8, "p_line_bytes": 128, "p_register_descriptor": 1},
    {"p_size": 8, "p_slot_w": 3, "p_lanes": 3, "p_line_bytes": 16, "p_register_descriptor": 0},
)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def wrapper(source, independent=False):
    header = source[source.index("module conv_im2col_descriptor"):source.index(");") + 2]
    header = header.replace("module conv_im2col_descriptor", "module descriptor_contract", 1)
    if not independent:
        header = re.sub(r"(?m)^\s*input[^\n]*\bi_(?:p0|rows_q)\b[^\n]*\n", "", header)
    header_lines = header[:header.rfind(");")].rstrip().splitlines()
    declaration, marker, comment = header_lines[-1].partition("//")
    header_lines[-1] = declaration.rstrip() + "," + (" //" + comment if marker else "")
    header = "\n".join(header_lines) + "\n  output logic [31:0] contract_position_end // 验证保存终点与位置状态的关系\n);"
    position = "u_descriptor.u_position.position_end" if " u_position (" in source else \
        "i_p0 + 32'(i_rows_q)"
    declarations = "" if independent else """
  logic [31:0] i_p0;
  logic [p_tile_count_w-1:0] i_rows_q;
"""
    state = "" if independent else """
  // 此处直接复现前端对这两个输入状态的拥有关系及更新优先级。
  always_ff @(posedge i_clk or negedge i_rst_n) begin
    if (!i_rst_n) begin
      i_p0 <= '0;
      i_rows_q <= '0;
    end else if (i_cfg_valid && i_cfg_ready) begin
    end else if (o_tile_commit) begin
      if (committed.invalid) begin
      end else begin
        i_p0 <= committed.position;
        i_rows_q <= committed.rows;
      end
    end
  end
"""
    return header + """
  localparam int p_prepared_count_w = p_tile_count_w;
  localparam int p_prepared_slot_w = p_slot_w;
  localparam int p_prepared_coord_w = p_coord_w;
  `include "conv_im2col_prepared_tile.svh"
""" + declarations + """
  prepared_tile_t committed;
  assign committed = o_committing_tile_packed;
  conv_im2col_descriptor #(
    .p_size(p_size), .p_slot_w(p_slot_w), .p_lanes(p_lanes),
    .p_line_bytes(p_line_bytes), .p_cache_policy(p_cache_policy),
    .p_register_descriptor(p_register_descriptor), .p_rw(p_rw)
  ) u_descriptor (.*);
""" + state + "  assign contract_position_end = " + position + ";\nendmodule\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-root", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--candidate-descriptor", type=Path)
    parser.add_argument("--independent-position-inputs", action="store_true",
                        help="结构变换验证中保留位置和行数为每周期任意的输入")
    parser.add_argument("--profiles", type=int, nargs="+", default=list(range(len(PROFILES))))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    root, reference = args.source_root.resolve(), args.reference_root.resolve()
    candidate = args.candidate_descriptor.resolve() if args.candidate_descriptor else root / RTL
    snapshots = {}
    hashes = {}
    for side, tree, original in (("gold", reference, reference / RTL), ("gate", root, candidate)):
        generated = out / (side + "_contract.sv")
        generated.write_text(wrapper(original.read_text(), args.independent_position_inputs))
        dependency = runpy.run_path(str(tree / "scripts/rtl/source_files.py"))["with_dependencies"]
        sources = dependency([original, generated], tree)
        snapshots[side] = (tree, sources)
        includes = runpy.run_path(str(tree / "scripts/rtl/source_files.py"))["input_files"](sources, tree)
        hashes[side] = {str(path): digest(path) for path in includes}
    results = []
    for index in args.profiles:
        parameters = PROFILES[index]
        folder = out / f"profile_{index}"
        folder.mkdir(exist_ok=True)
        commands = []
        for side, (tree, sources) in snapshots.items():
            options = ["--top", "descriptor_contract", "-DSYNTHESIS=1", "-I" + str(tree / "include")]
            options += [f"-G{name}={value}" for name, value in parameters.items()]
            commands += ["read_slang " + shlex.join(options + list(map(str, sources))),
                         "prep -top descriptor_contract -flatten", "memory_map", "async2sync", "opt",
                         "rename descriptor_contract " + side, "design -stash " + side]
        commands += ["design -copy-from gold gold", "design -copy-from gate gate",
                     "equiv_make gold gate equivalent", "hierarchy -top equivalent",
                     "opt_merge", "equiv_simple -short -seq 1", "opt_clean",
                     "equiv_induct -seq 3", "equiv_status -assert"]
        script, log = folder / "proof.ys", folder / "proof.log"
        script.write_text("\n".join(commands) + "\n")
        with log.open("w") as output:
            subprocess.run([sys.executable, str(root / "scripts/fpga/open_fpga_synth.py"),
                            "--worker", str(script)], cwd=root, stdout=output,
                           stderr=subprocess.STDOUT, check=True, timeout=900)
        content = log.read_text()
        points = re.search(r"Of those cells (\d+) are proven and (\d+) are unproven", content)
        if "Equivalence successfully proven!" not in content or points is None or int(points[2]) != 0:
            raise RuntimeError(f"完整描述符等价证明未完成：{log}")
        results.append({"profile": index, "parameters": parameters, "passed": True,
                        "proven_points": int(points[1]), "log_sha256": digest(log)})
        print(json.dumps(results[-1], ensure_ascii=False), flush=True)
    for sources in hashes.values():
        if any(digest(Path(path)) != value for path, value in sources.items()):
            raise RuntimeError("验证期间输入源码发生变化")
    scope = ("完整描述符公开输出和对应状态；所有公开输入均未附加限制" if args.independent_position_inputs else
             "完整描述符公开输出和对应状态；p0 与 rows 按实际前端更新，其他输入未附加限制")
    report = {"passed": True, "cases": results, "source_sha256": hashes,
              "scope": scope,
              "all_public_outputs_compared": True, "source_unchanged": True}
    (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
