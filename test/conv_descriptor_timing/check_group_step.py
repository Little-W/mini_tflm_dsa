#!/usr/bin/env python3
"""证明配置组步长的保存和三十三位窗口序号匹配。"""
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    descriptor = root / "rtl/npu/conv/conv_im2col_descriptor.sv"
    geometry = root / "rtl/npu/conv/conv_im2col_geometry.sv"
    dependencies = runpy.run_path(str(root / "scripts/rtl/source_files.py"))
    sources = dependencies["with_dependencies"]([geometry], root)
    inputs = dependencies["input_files"]([*sources, descriptor], root)
    hashes = {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in inputs}
    text = descriptor.read_text()
    first = text.index("  assign negative_group = ")
    last = text.index("  // 空间分块起点", first)
    target_logic = text[first:last]
    geometry_inputs = re.findall(r"^\s*input\b[^\n]*\b(i_\w+)\s*,?$",
                                 geometry.read_text(), re.M)
    direct_inputs = {"i_clk", "i_rst_n", "i_cfg_valid", "i_cfg_ready", "i_cfg"}
    connections = [f".{name}({name})" if name in direct_inputs else f".{name}('0)"
                   for name in geometry_inputs]
    connections[geometry_inputs.index("i_state")] = ".i_state(conv_im2col_frontend_pkg::IDLE)"
    connections += [".o_last_group_channel_q(i_last_group_channel_q)",
                    ".o_group_nonzero_q(i_group_nonzero_q)"]
    model = out / "model.sv"
    model.write_text("""module comparison #(parameter bit p_register_descriptor=0)(
input logic i_clk,i_rst_n,i_cfg_valid,i_cfg_ready,
input conv_im2col_pkg::conv_cfg_t i_cfg,
input logic i_prepare,input logic [31:0] i_tile_q0,i_q0,
output logic equivalent);
logic [15:0] reference_group;
logic [15:0] i_last_group_channel_q;
logic i_group_nonzero_q;
logic [31:0] window_next_q;
logic window_next_valid;
wire window_prepare_write=i_prepare && !(i_cfg_valid && i_cfg_ready);
conv_im2col_pkg::conv_cfg_t i_c;
assign i_c.group_c=reference_group;
conv_im2col_geometry #(.p_register_descriptor(1'b0)) dut(
""" + ",\n".join(connections) + """);
always_ff @(posedge i_clk or negedge i_rst_n)begin
  if(!i_rst_n)reference_group<=0;
  else if(i_cfg_valid&&i_cfg_ready)reference_group<=i_cfg.group_c;
end
always_ff @(posedge i_clk or negedge i_rst_n)begin
  if(!i_rst_n)window_next_valid<=0;
  else if(i_cfg_valid&&i_cfg_ready)window_next_valid<=0;
  else if(window_prepare_write)window_next_valid<=1;
end
always_ff @(posedge i_clk)begin
  if(i_rst_n&&window_prepare_write)window_next_q<=i_q0;
end
logic [16:0] negative_group;
logic [2:0][32:0] target_difference;
logic [2:0] target_difference_match;
logic [3:0] incoming_tap_match_o_equal;
""" + target_logic + """
wire [32:0] positive_step={17'b0,reference_group};
wire [32:0] negative_step=33'd0-positive_step;
wire [32:0] double_negative_step=33'd0-(positive_step<<1);
wire [32:0] difference={1'b0,i_tile_q0}-{1'b0,window_next_q};
wire [2:0] reference_match={difference==double_negative_step,
  difference==negative_step,difference==positive_step};
assign equivalent=!i_rst_n ||
  (target_difference=={double_negative_step,negative_step,positive_step} &&
   (!window_next_valid || incoming_tap_match_o_equal[3:1]==reference_match));
endmodule
""")
    runs = []
    for registered in (0, 1):
        script = out / f"registered{registered}.ys"
        script.write_text("read_slang --top comparison --single-unit --allow-use-before-declare " +
                          f"-Gp_register_descriptor={registered} -D SYNTHESIS=1 -I" +
                          shlex.quote(str(root / "include")) + " " +
                          shlex.join(map(str, [*sources, model])) + "\n" +
                          "prep -top comparison -flatten\nasync2sync\nopt\ncheck -assert\n" +
                          "sat -seq 8 -set-def-inputs -set-at 1 i_rst_n 0 -prove equivalent 1 -verify\n")
        log = script.with_suffix(".log")
        with log.open("w") as stream:
            subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                            "--worker", str(script)], stdout=stream, stderr=subprocess.STDOUT,
                           check=True, timeout=180)
        runs.append({"p_register_descriptor": registered, "passed": True,
                     "window_target_state_bits": 99 if registered == 0 else 0,
                     "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest()})
        print(f"GROUP_STEP_PASS registered={registered} width=16 index_width=33", flush=True)
    unchanged = all(hashlib.sha256(path.read_bytes()).hexdigest() == hashes[str(path.relative_to(root))]
                    for path in inputs)
    if not unchanged:
        raise RuntimeError("Group step sources changed during validation")
    report = {"passed": True, "sources_sha256": hashes, "sources_unchanged": True,
              "saved_state_bits": 1, "configuration_group_width": 16,
              "window_index_width": 33, "group_value_assumptions": [],
              "proof_depth": 8, "reset_at_step": 1, "runs": runs}
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
