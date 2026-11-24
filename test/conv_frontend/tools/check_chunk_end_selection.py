#!/usr/bin/env python3
"""验证所有通道范围输入下的行末组合选择及逐位四态传播。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

from check_frontend_range_comparisons import bench, declarations, mapping_wrapper, module, section, CHECKS

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "test"))
from reference_sources import read_reference_file
STREAM = Path("rtl/npu/conv/conv_im2col_stream.sv")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def circuit(source, name, lanes, narrow):
    cache_bytes = max(4, lanes)
    inputs = {"i_narrow_output": 1, "i_past_active_q": 1, "i_word_output_q": 1, "input_s16": 1,
              "column_lane_allowed_q": lanes+1, "active_lane_allowed_q": lanes+1,
              "group_lane_allowed": lanes, "word_available_q": cache_bytes}
    body = section(source, "  for (genvar lane = 0; lane < p_lanes; lane++) begin : g_word_lane",
                   "  // 八位输入的配置偏移范围")
    return inputs, "module " + name + "(\n" + ",\n".join(declarations(inputs, "input ") +
        ["output logic o_chunk_reaches_end"]) + f''');
  localparam int p_lanes={lanes},p_narrow_lanes={narrow},p_tile_count_w=5;
  localparam int p_chunk_count_w=$clog2(p_lanes+1),p_cache_read_bytes={cache_bytes};
  localparam int p_word_shift=$clog2(p_cache_read_bytes);
  localparam bit p_saved_word_range=1;
  typedef struct packed {{logic input_s16;}} configuration_t;
  configuration_t i_c;
  assign i_c.input_s16=input_s16;
  wire [31:0] o_addr='0;
  wire [p_chunk_count_w-1:0] o_chunk_count='0;
  wire [p_tile_count_w-1:0] col_remaining='0;
  logic [p_lanes-1:0] word_lane_s8,word_lane_s16,word_lane_allowed;
  logic [p_lanes-1:0] lane_context_allowed,chunk_data_allowed;
  logic [p_lanes-1:0] chunk_static_end,chunk_end_s8,chunk_end_s16;
''' + body + "\nendmodule\n"


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
    paths = [root/STREAM, root/"rtl/common/onehot_mux.sv", Path(__file__).resolve(),
             Path(__file__).with_name("check_frontend_range_comparisons.py")]
    hashes = {str(path): digest(path) for path in paths}
    source = (root/STREAM).read_text()
    reference = read_reference_file(root, args.reference_ref, str(STREAM), text=True)
    helper = out/"chunk_end_helpers.sv"
    helper.write_text("\n".join(module(source, name) for name in
                     ("conv_im2col_chunk_lane", "conv_im2col_chunk_end_select")))
    cases, mappings = [], {}
    for lanes, narrow in ((2, 4), (8, 4), (8, 8), (16, 4), (16, 8)):
        name = f"lanes{lanes}_narrow{narrow}"
        inputs, candidate = circuit(source, "current_end", lanes, narrow)
        unused_inputs, previous = circuit(reference, "reference_end", lanes, narrow)
        generated = out/(name+"_model.sv")
        text = candidate + previous + "module proof(\n" + ",\n".join(declarations(inputs, "input ") +
            ["output logic equivalent,actual_value,expected_value"]) + ''');
  current_end actual(.o_chunk_reaches_end(actual_value),.*);
  reference_end expected(.o_chunk_reaches_end(expected_value),.*);
  assign equivalent=actual_value===expected_value;
endmodule
'''
        generated.write_text(text.replace("always_comb", "always @*"))
        support = [root/"rtl/common/onehot_mux.sv", helper, generated]
        script, log, tb, binary, build, simulation = [out/(name+suffix) for suffix in
            (".ys", ".formal.log", ".sv", ".vvp", ".build.log", ".four_state.log")]
        script.write_text("read_slang -DSYNTHESIS --top proof " + shlex.join(map(str, support)) +
            "\nsetattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n"
            "prep -top proof -flatten\ncheck -assert\nsat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
        with log.open("w") as handle:
            subprocess.run([sys.executable, str(root/"scripts/fpga/open_fpga_synth.py"), "--worker", str(script)],
                           stdout=handle, stderr=subprocess.STDOUT, check=True, timeout=180)
        if "SAT proof finished - no model found: SUCCESS!" not in log.read_text():
            raise RuntimeError(str(log))
        tb.write_text(bench(inputs, 1, ""))
        with build.open("w") as handle:
            subprocess.run([args.iverilog, "-g2012", "-s", "tb", "-o", str(binary),
                            *map(str, support+[tb])], stdout=handle, stderr=subprocess.STDOUT, check=True)
        with simulation.open("w") as handle:
            subprocess.run([args.vvp, str(binary)], stdout=handle, stderr=subprocess.STDOUT,
                           check=True, timeout=120)
        if "FRONTEND_COMPARISONS_FOUR_STATE_PASS" not in simulation.read_text():
            raise RuntimeError(str(simulation))
        binary.unlink()
        cases.append(dict(lanes=lanes, narrow_lanes=narrow, formal_passed=True,
                          four_state_checks=CHECKS, input_bits=sum(inputs.values()), all_input_bits_x_z=True,
                          model_sha256=digest(generated), formal_log_sha256=digest(log),
                          simulation_log_sha256=digest(simulation)))
        if (lanes, narrow) in ((8, 8), (16, 8)):
            for kind in ("actual", "expected"):
                wrapper = out/(name+"_"+kind+"_mapping.sv")
                wrapper.write_text(mapping_wrapper(inputs, 1, kind))
                mappings[name+"_"+kind] = dict(top="comparison_mapping", options=["-D", "SYNTHESIS=1"],
                    sources=list(map(str, support+[wrapper])), configuration="Complete registered chunk boundary")
        print("CHUNK_END_SELECTION_PASS", name, flush=True)
    (out/"mapping_cases.json").write_text(json.dumps(mappings, indent=2)+"\n")
    if hashes != {path: digest(path) for path in hashes}:
        raise RuntimeError("检查期间源码发生变化")
    report = dict(passed=True, cases=cases, inputs_constrained=False, source_sha256=hashes,
                  sources_unchanged=True, reference_ref=args.reference_ref,
                  reference_sha256=hashlib.sha256(reference.encode()).hexdigest())
    (out/"summary.json").write_text(json.dumps(report, indent=2, ensure_ascii=False)+"\n")


if __name__ == "__main__":
    main()
