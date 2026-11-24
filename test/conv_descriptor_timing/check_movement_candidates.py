#!/usr/bin/env python3
"""验证行与卷积核移动地址的并行候选、完整模加法及四态传播。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "test"))
from reference_sources import read_reference_file
sys.path.insert(0, str(ROOT / "test/conv_frontend/tools"))
from check_frontend_range_comparisons import (  # noqa: E402
    CHECKS, bench, declarations, mapping_wrapper, module, section,
)

GEOMETRY = Path("rtl/npu/conv/conv_im2col_geometry.sv")
INPUTS = {
    **{name: 32 for name in (
        "i_pixel_index", "i_tap_group_base", "i_row_base_pixel", "i_row_group_base",
        "i_row_base_addr", "i_row_wrap_bytes", "i_row_step_bytes",
        "i_tap_wrap_bytes", "i_tap_step_bytes")},
    "i_row_wrap_pixels": 33, "i_tap_wrap_pixels": 33,
    "stride_w": 16, "dilation_w": 16,
    "i_row_wrap_q": 1, "i_tap_wrap_q": 1,
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def movement_model(source, name):
    body = section(source, "  assign movement_i_a =",
                   "  // 配置阶段保存乘积，输出传输期间")
    return "module " + name + "(\n" + ",\n".join(
        declarations(INPUTS, "input ") + ["output logic [159:0] result"]) + """);
  typedef struct packed {logic [15:0] stride_w,dilation_w;} configuration_t;
  configuration_t i_c;
  logic o_row_wrap,o_tap_wrap;
  logic [4:0][31:0] movement_i_a,movement_i_b,movement_o_sum;
  logic [4:0][31:0] movement_step_delta,movement_wrap_delta;
  logic [4:0] movement_wrap_select;
  assign i_c.stride_w=stride_w;
  assign i_c.dilation_w=dilation_w;
  assign o_row_wrap=i_row_wrap_q;
  assign o_tap_wrap=i_tap_wrap_q;
""" + body + "\nassign result=movement_o_sum;\nendmodule\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--reference-ref", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--iverilog", default=shutil.which("iverilog") or "iverilog")
    parser.add_argument("--vvp", default=shutil.which("vvp") or "vvp")
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    tracked = [root / GEOMETRY, root / "rtl/common/parallel_prefix_add.sv",
               Path(__file__).resolve(),
               ROOT / "test/conv_frontend/tools/check_frontend_range_comparisons.py"]
    hashes = {str(path): digest(path) for path in tracked}
    current = (root / GEOMETRY).read_text()
    previous = read_reference_file(root, args.reference_ref, str(GEOMETRY), text=True)
    helper = out / "movement_helper.sv"
    helper.write_text(module(current, "conv_geometry_movement_add"))
    model = out / "movement_model.sv"
    text = movement_model(current, "current_movement") + movement_model(previous, "reference_movement")
    text += "module proof(\n" + ",\n".join(declarations(INPUTS, "input ") + [
        "output logic equivalent", "output logic [159:0] actual_value,expected_value"]) + """);
  current_movement actual(.result(actual_value),.*);
  reference_movement expected(.result(expected_value),.*);
  assign equivalent=actual_value===expected_value;
endmodule
"""
    model.write_text(text.replace("always_comb", "always @*"))
    support = [root / "rtl/common/parallel_prefix_add.sv", helper, model]
    formal = []
    for row_wrap in (0, 1):
        for tap_wrap in (0, 1):
            name = f"row{row_wrap}_tap{tap_wrap}"
            script, log = out / (name + ".ys"), out / (name + ".formal.log")
            script.write_text("read_slang -DSYNTHESIS --top proof " + shlex.join(map(str, support)) +
                "\nsetattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n"
                "prep -top proof -flatten\ncheck -assert\nsat -verify -prove equivalent 1 "
                f"-set i_row_wrap_q {row_wrap} -set i_tap_wrap_q {tap_wrap} -show-inputs -show-outputs\n")
            with log.open("w") as stream:
                subprocess.run([sys.executable, str(root / "scripts/fpga/open_fpga_synth.py"),
                                "--worker", str(script)], stdout=stream, stderr=subprocess.STDOUT,
                               check=True, timeout=180)
            if "SAT proof finished - no model found: SUCCESS!" not in log.read_text():
                raise RuntimeError(str(log))
            formal.append(dict(row_wrap=row_wrap, tap_wrap=tap_wrap, passed=True,
                               log_sha256=digest(log)))
            print("MOVEMENT_CANDIDATES_FORMAL_PASS", name, flush=True)
    tb, binary = out / "four_state.sv", out / "four_state.vvp"
    tb.write_text(bench(INPUTS, 160, """
if(sample%8==0)begin
  i_row_base_addr='1;i_row_step_bytes=1;i_row_wrap_bytes=0;
  i_tap_group_base='1;i_tap_step_bytes=1;i_tap_wrap_bytes=0;
end
if(sample%8==1)begin
  i_row_step_bytes=i_row_wrap_bytes;
  i_tap_step_bytes=i_tap_wrap_bytes;
end
""" + "if(sample%8==2){" + ",".join(INPUTS) + "}='0;\n"))
    build, simulation = out / "four_state_compile.log", out / "four_state.log"
    with build.open("w") as stream:
        subprocess.run([args.iverilog, "-g2012", "-s", "tb", "-o", str(binary),
                        *map(str, support + [tb])], stdout=stream, stderr=subprocess.STDOUT, check=True)
    with simulation.open("w") as stream:
        subprocess.run([args.vvp, str(binary)], stdout=stream, stderr=subprocess.STDOUT,
                       check=True, timeout=180)
    if "FRONTEND_COMPARISONS_FOUR_STATE_PASS" not in simulation.read_text():
        raise RuntimeError(str(simulation))
    binary.unlink()
    mapping = {}
    for kind in ("actual", "expected"):
        wrapper = out / (kind + "_mapping.sv")
        wrapper.write_text(mapping_wrapper(INPUTS, 160, kind))
        mapping[kind] = dict(top="comparison_mapping", options=["-D", "SYNTHESIS=1"],
            sources=list(map(str, support + [wrapper])),
            configuration="Complete registered movement address candidates")
    (out / "mapping_cases.json").write_text(json.dumps(mapping, indent=2) + "\n")
    if hashes != {path: digest(path) for path in hashes}:
        raise RuntimeError("检查期间源码发生变化")
    report = dict(passed=True, formal=formal, formal_all_binary_wrap_combinations=True,
        independent_input_bits=sum(INPUTS.values()), observed_output_bits=160,
        four_state_checks=CHECKS, all_input_bits_x_z=True, source_sha256=hashes,
        sources_unchanged=True, reference_ref=args.reference_ref,
        reference_sha256=hashlib.sha256(previous.encode()).hexdigest(),
        model_sha256=digest(model), simulation_log_sha256=digest(simulation))
    (out / "summary.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print("MOVEMENT_CANDIDATES_PASS", json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
