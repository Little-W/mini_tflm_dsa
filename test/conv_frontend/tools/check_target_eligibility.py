#!/usr/bin/env python3
"""证明窗口目标许可保存和描述符地址运算的完整时序行为。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[3]
DESCRIPTOR = Path("rtl/npu/conv/conv_im2col_descriptor.sv")
COMMON = (
    "rtl/npu/conv/conv_im2col_pkg.sv",
    "rtl/npu/conv/conv_im2col_frontend_pkg.sv",
    "rtl/common/add_equal.sv",
    "rtl/common/parallel_prefix_add.sv",
    "rtl/common/parallel_unsigned_compare.sv",
    "rtl/common/unsigned_compare.sv",
    "rtl/common/increment_equal.sv",
    "rtl/common/onehot_mux.sv",
    "rtl/common/onehot_check.sv",
)
PROFILES = {
    "production_direct": (16, 5, 8, 128, 0),
    "production_registered": (16, 5, 8, 128, 1),
    "small_direct": (4, 3, 1, 16, 0),
    "wide_registered": (17, 6, 16, 256, 1),
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(command, log, timeout=900):
    with log.open("w") as stream:
        subprocess.run(list(map(str, command)), cwd=ROOT, stdout=stream,
                       stderr=subprocess.STDOUT, check=True, timeout=timeout)


def window_model(name, text):
    first = text.index(chr(96) + "ifndef SYNTHESIS\n  logic [32:0] reduction_difference;")
    last = text.index("  // 空间分块起点", first)
    target = text[first:last]
    first = text.index("  conv_descriptor_match #(.p_width(32)) u_window_reduction_match")
    last = text.index("  // 完整坐标比较", first)
    directions = text[first:last]
    mux = re.search(r"  onehot_mux #\(\.p_choices\(4\), \.p_width\(1\)\) u_window_match \(.*?\n  \);",
                    text, re.S).group()
    assignments = []
    for signal in ("window_next_q", "window_forward_allowed_q", "window_backward_allowed_q",
                   "window_previous_allowed_q"):
        assignments.append(re.search(r"      " + signal + r" <= .*?;", text).group())
    # 更新条件直接核对实际窗口保存块，测试模型保持相同的四态分支语义。
    window_write = re.search(r"  always_ff @\(posedge i_clk\) begin\s*"
        r"if \(!i_rst_n\) begin\s*end else if \(window_prepare_write\) begin\s*"
        r"window_next_p <=.*?\n    end\n  end", text, re.S)
    if window_write is None or any(statement not in window_write.group() for statement in assignments):
        raise RuntimeError("窗口保存条件或赋值位置不符合当前验证模型")
    return f"""module {name} #(parameter bit p_register_descriptor=0)(
 input logic i_clk,i_rst_n,window_prepare_write,
 input logic [160:0] stimulus,output logic [3:0] observed
);
 import conv_im2col_pkg::*;
 conv_cfg_t i_c;
 logic [31:0] i_q0,i_tile_q0,window_next_q;
 logic [15:0] i_last_group_channel_q,i_kx0_q,i_ky0_q,i_last_kernel_col_q;
 logic [15:0] group_c,kernel_w;
 logic i_group_nonzero_q;
 logic [16:0] negative_group;
 logic [2:0][32:0] target_difference;
 logic [2:0] target_difference_match,target_prepared_match;
 logic [3:0] window_match_select,incoming_tap_match_o_equal;
 logic window_forward_allowed_q,window_backward_allowed_q,window_previous_allowed_q;
 logic incoming_position_same_tap,incoming_position_forward_tap;
 logic incoming_position_backward_tap,incoming_position_previous_row,incoming_window_match;
 assign {{i_q0,i_tile_q0,group_c,i_last_group_channel_q,i_kx0_q,i_ky0_q,
     i_last_kernel_col_q,kernel_w,i_group_nonzero_q}}=stimulus;
 always_comb begin i_c='0;i_c.group_c=group_c;i_c.kernel_w=kernel_w;end
{target}{directions}{mux}
 always_ff @(posedge i_clk) begin
   if (!i_rst_n) begin
   end else if (window_prepare_write) begin
{chr(10).join(assignments)}
   end
 end
 assign observed={{incoming_position_previous_row,incoming_position_backward_tap,
     incoming_position_forward_tap,incoming_window_match}};
endmodule
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--reference-ref", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--profiles", nargs="+", choices=tuple(PROFILES), default=list(PROFILES))
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    original = subprocess.check_output(["git", "show", args.reference_ref + ":" + str(DESCRIPTOR)],
                                       cwd=ROOT).decode()
    candidate = (root / DESCRIPTOR).read_text()
    dependencies = [root / name for name in COMMON]
    source_files = [root / DESCRIPTOR, *dependencies, root / "include/conv_im2col_prepared_tile.svh"]
    source_hashes = {str(path.relative_to(root)): digest(path) for path in source_files}

    # 原寄存器的组合观察值也参与归纳证明，不增加输入约束或改变公开输出。
    declaration = "      logic unused_target_carry;\n"
    if original.count(declaration) != 1:
        raise RuntimeError("未找到唯一的窗口目标保存块")
    observed_reference = original.replace(declaration, declaration + """
      (* keep *) logic target_eligible;
      assign target_eligible = !target_q[32] && (target == 0 ? window_forward_allowed_q :
          target == 1 ? window_backward_allowed_q : window_previous_allowed_q);
""")
    snapshots = {}
    for name, text in (("reference", observed_reference), ("candidate", candidate)):
        snapshots[name] = out / (name + "_descriptor.sv")
        snapshots[name].write_text(text)
    results = []
    for profile in args.profiles:
        size, slot_width, lanes, line_bytes, registered = PROFILES[profile]
        commands = []
        for side, label in (("reference", "gold"), ("candidate", "gate")):
            options = ["--top", "conv_im2col_descriptor", "--single-unit", "--allow-use-before-declare",
                       "-D", "SYNTHESIS=1", "-I" + str(root / "include"),
                       f"-Gp_size={size}", f"-Gp_slot_w={slot_width}", f"-Gp_lanes={lanes}",
                       f"-Gp_line_bytes={line_bytes}", f"-Gp_register_descriptor={registered}"]
            commands += ["read_slang " + shlex.join(options + list(map(str, [*dependencies, snapshots[side]]))),
                         "setattr -mod -unset keep_hierarchy", "setattr -unset keep_hierarchy",
                         "prep -top conv_im2col_descriptor -flatten", "memory_map", "async2sync", "opt",
                         "rename -hide w:u_* w:*.u_* w:incoming_tap_match_o_equal "
                         "w:target_prepared_match w:window_match_select",
                         f"rename conv_im2col_descriptor {label}", f"design -stash {label}"]
        commands += ["design -copy-from gold -as gold gold", "design -copy-from gate -as gate gate",
                     "equiv_make gold gate equivalence", "hierarchy -top equivalence",
                     "equiv_simple -short -seq 1", "equiv_induct -seq 3", "equiv_status -assert"]
        script, log = out / (profile + ".ys"), out / (profile + ".log")
        script.write_text("\n".join(commands) + "\n")
        run([sys.executable, ROOT / "scripts/fpga/open_fpga_synth.py", "--worker", script], log)
        match = re.search(r"Of those cells (\d+) are proven and (\d+) are unproven", log.read_text())
        if not match or int(match[2]) or "Equivalence successfully proven!" not in log.read_text():
            raise RuntimeError("完整描述符时序证明未完成：" + profile)
        results.append({"profile": profile, "parameters": dict(zip(
            ("p_size", "p_slot_w", "p_lanes", "p_line_bytes", "p_register_descriptor"),
            (size, slot_width, lanes, line_bytes, registered))), "passed": True,
            "proven_points": int(match[1]), "log_sha256": digest(log)})
        print("DESCRIPTOR_TARGET_EQUIVALENCE_PASS", profile, match[1], flush=True)

    helper = re.search(r"(?m)^module conv_descriptor_match\b.*?endmodule", candidate, re.S).group()
    model = out / "window_eligibility.sv"
    model.write_text(window_model("reference", original) + window_model("candidate", candidate) + helper + "\n")
    bench = ROOT / "test/conv_frontend/tb_target_eligibility.sv"
    executable = out / "four_state.vvp"
    run(["iverilog", "-g2012", "-s", "tb", "-o", executable, dependencies[0],
         root / "rtl/common/add_equal.sv", root / "rtl/common/parallel_prefix_add.sv",
         root / "rtl/common/onehot_mux.sv", model, bench], out / "four_state_compile.log")
    run(["vvp", executable], out / "four_state.log")
    if "WINDOW_ELIGIBILITY_FOUR_STATE_PASS checks=32769 modes=2" not in (out / "four_state.log").read_text():
        raise RuntimeError("窗口目标资格四态比较未完成")
    if any(digest(root / name) != value for name, value in source_hashes.items()):
        raise RuntimeError("检查期间源文件发生变化")
    result = {"passed": True, "reference_ref": args.reference_ref, "inputs_constrained": False,
              "reference_source_sha256": hashlib.sha256(original.encode()).hexdigest(),
              "reference_observation_sha256": digest(snapshots["reference"]),
              "source_sha256": source_hashes, "profiles": results,
              "scope": "全部公开输出和语义一致的内部信号，包含目标许可保存关系的无限时序证明",
              "four_state": {"checks": 32769, "configurations": 2, "passed": True,
                             "model_sha256": digest(model), "bench_sha256": digest(bench),
                             "log_sha256": digest(out / "four_state.log")},
              "checker_sha256": digest(__file__)}
    (out / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print("DESCRIPTOR_TARGET_VALIDATION_PASS", out / "summary.json", flush=True)


if __name__ == "__main__":
    main()
