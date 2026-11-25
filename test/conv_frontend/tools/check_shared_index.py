#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""证明缓存索引共享移位的逐位等价性，并检查含未知值的输入。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[3]
SOURCE = Path("rtl/npu/conv/conv_im2col_frontend.sv")
PORTS = {
    "short_pixel_q": 1, "request_descriptor_metadata_context": 1,
    "request_row_metadata_context": 1, "request_tap_context": 1,
    "window_index_shift_q": 5, "incoming_pixel_select": 10,
    "incoming_pixel_candidates": (10, 32), "incoming_y_candidates": (10, 35),
    "next_row_pixel": 32, "next_tap_pixel": 32, "pixel_index": 32,
    "incoming_pixel": 32, "next_row_iy": 35, "next_tap_iy": 35, "iy": 35,
}


def declarations(names=PORTS, prefix="input "):
    values = []
    for name in names:
        width = PORTS[name]
        dimensions = width if isinstance(width, tuple) else (() if width == 1 else (width,))
        values.append(prefix + "logic " + "".join(f"[{size-1}:0]" for size in dimensions) + " " + name)
    return values


def region(text):
    start = text.index("  if (!REGISTER_DESCRIPTOR) begin : g_parallel_request_index")
    return text[start:text.index("  // 两个描述符纪元", start)]


def model(name, text):
    return (f"module {name}(" + ",\n".join(declarations()) + ",\n"
            "output logic [31:0] incoming_req_index,request_index_selected,\n"
            "output logic [34:0] request_y_selected);\n"
            "localparam int COORD_W=35; localparam bit REGISTER_DESCRIPTOR=0;\n"
            "logic [31:0] current_req_index;\n"
            "always_comb begin\n"
            "  if (short_pixel_q) current_req_index=pixel_index>>window_index_shift_q;\n"
            "  else current_req_index=pixel_index;\nend\n" + region(text) + "\nendmodule\n")


def run(command, log, timeout=180):
    with log.open("w") as stream:
        subprocess.run(list(map(str, command)), cwd=ROOT, stdout=stream,
                       stderr=subprocess.STDOUT, check=True, timeout=timeout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-source-root", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--four-state-samples", type=int, default=1024)
    args = parser.parse_args()
    if args.four_state_samples < 1:
        parser.error("--four-state-samples must be positive")
    root, reference_root, out = args.source_root.resolve(), args.reference_source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    candidate, reference = root / SOURCE, reference_root / SOURCE
    helper = root / "rtl/common/onehot_mux.sv"
    sources = [candidate, reference, helper]
    hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    connections = ",".join("." + name for name in PORTS)
    text = model("candidate", candidate.read_text()) + model("reference", reference.read_text())
    text += ("module proof(" + ",\n".join(declarations()) + ",output logic equivalent);\n"
             "logic [98:0] a,b;\n"
             f"candidate ca({connections},.incoming_req_index(a[31:0]),.request_index_selected(a[63:32]),.request_y_selected(a[98:64]));\n"
             f"reference re({connections},.incoming_req_index(b[31:0]),.request_index_selected(b[63:32]),.request_y_selected(b[98:64]));\n"
             "assign equivalent=a===b;\nendmodule\n")
    names = [name for name in PORTS if name not in ("short_pixel_q", "window_index_shift_q")]
    text += ("module fixed #(parameter bit p_short=1,parameter int p_shift=0)(" +
             ",\n".join(declarations(names)) + ",input logic [4:0] disabled_shift,output logic equivalent);\n"
             "proof dut(" + ",".join("." + name for name in names) +
             ",.short_pixel_q(p_short),.window_index_shift_q(p_short ? 5'(p_shift) : disabled_shift),"
             ".equivalent(equivalent));\nendmodule\n")
    model_path = out / "model.sv"
    model_path.write_text(text)
    partitions = [(0, 0)] + [(1, shift) for shift in range(32)]
    for enabled, shift in partitions:
        script = out / f"shift_{enabled}_{shift}.ys"
        script.write_text(f"read_slang -D SYNTHESIS=1 --top fixed -Gp_short={enabled} -Gp_shift={shift} {helper} {model_path}\n"
                          "prep -top fixed -flatten\ncheck -assert\n"
                          "sat -verify -prove equivalent 1 -timeout 60\n")
        run([sys.executable, ROOT / "scripts/fpga/open_fpga_synth.py", "--worker", script], script.with_suffix(".log"))
    # 关闭移位及全部32种移位量覆盖完整控制空间，每项保留所有数据和选择位为自由输入。
    total = sum(width[0] * width[1] if isinstance(width, tuple) else width for width in PORTS.values())
    words = (total + 31) // 32
    bench = out / "tb.sv"
    bench.write_text("module tb;\n" + ";\n".join(declarations(prefix="")) + ";\n"
                     f"logic equivalent;logic [{words*32-1}:0] pattern;logic [319:0] pixel_pattern;\nproof dut(.*);\ninitial begin\n"
                     f"for(integer sample=0;sample<{args.four_state_samples};sample++)begin\n"
                     f"for(integer n=0;n<{words};n++)pattern[32*n+:32]=$urandom;\n" +
                     "{" + ",".join(PORTS) + "}=pattern;\n"
                     "if(sample%3==0)window_index_shift_q[sample%5]=1'bx;\n"
                     "if(sample%5==0)incoming_pixel_select[sample%10]=1'bz;\n"
                     "if(sample%7==0)short_pixel_q=1'bx;\n"
                     "if(sample%11==0)request_descriptor_metadata_context=1'bz;\n"
                     "pixel_pattern=incoming_pixel_candidates;\n"
                     "if(sample%13==0)pixel_pattern[(sample%10)*32+sample%32]=1'bx;\n"
                     "incoming_pixel_candidates=pixel_pattern;\n"
                     "#1;if(equivalent!==1'b1)$fatal(1,\"Index comparison differs at sample %0d\",sample);\n"
                     f"end\n$display(\"SHARED_INDEX_FOUR_STATE_PASS checks={args.four_state_samples}\");$finish;\nend\nendmodule\n")
    simulation_model = out / "simulation_model.sv"
    simulation_model.write_text(text.replace("always_comb", "always @*"))
    binary = out / "comparison.vvp"
    run([shutil.which("iverilog") or "iverilog", "-g2012", "-s", "tb", "-o", binary,
         helper, simulation_model, bench], out / "four_state_build.log")
    run([shutil.which("vvp") or "vvp", binary], out / "four_state.log", timeout=max(300, args.four_state_samples))
    if f"SHARED_INDEX_FOUR_STATE_PASS checks={args.four_state_samples}" not in (out / "four_state.log").read_text():
        raise RuntimeError("Four-state comparison did not complete")
    if any(hashlib.sha256(Path(path).read_bytes()).hexdigest() != value for path, value in hashes.items()):
        raise RuntimeError("RTL source changed during comparison")
    result = {"passed": True, "formal_control_partitions": partitions,
              "disabled_shift_is_unconstrained": True,
              "four_state_checks": args.four_state_samples, "source_sha256": hashes,
              "model_sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
              "checker_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (out / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    print("SHARED_INDEX_PASS", out / "summary.json", flush=True)


if __name__ == "__main__":
    main()
