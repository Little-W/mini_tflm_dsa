#!/usr/bin/env python3
"""检查分组通道比较的完整四态行为和各组合边界的映射深度。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "test"))
from reference_sources import read_reference_file
SOURCE = Path("rtl/npu/conv/conv_channel_range_compare.sv")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(command, log, timeout=300):
    with log.open("w") as output:
        subprocess.run(list(map(str, command)), stdout=output, stderr=subprocess.STDOUT,
                       check=True, timeout=timeout)


def parameters():
    result = set()
    for lanes in range(1, 17):
        saved = 4 if lanes <= 4 else 1 << (lanes - 1).bit_length()
        width = (lanes + saved).bit_length()
        result.update((width, step, lane) for step in range(lanes + 1) for lane in range(saved + 1))
    return sorted(result)


def comparison(cases):
    text = ["""module comparison(
 input logic [5:0] remaining_low,channel_low,
 input logic remaining_borrow,high_nonzero,channel_high_last,
 output logic equivalent
);
""", f"logic [{len(cases)-1}:0] actual,expected;\n"]
    for index, (width, step, lane) in enumerate(cases):
        for label, module in (("actual", "conv_channel_range_compare"),
                              ("expected", "reference_conv_channel_range_compare")):
            text.append(f"""{module} #(.p_width({width}),.p_step({step}),.p_lane({lane})) u_{label}_{index} (
 .i_remaining_low(remaining_low[{width-1}:0]),.i_channel_low(channel_low[{width-1}:0]),
 .i_remaining_borrow(remaining_borrow),.i_high_nonzero(high_nonzero),
 .i_channel_high_last(channel_high_last),.o_allowed({label}[{index}])
);
""")
    text.append("assign equivalent=actual===expected;\nendmodule\n")
    return "".join(text)


def testbench(count):
    return """module tb;
 logic [5:0] remaining_low,channel_low;
 logic remaining_borrow,high_nonzero,channel_high_last,equivalent;
 logic [14:0] pattern;
 integer comparisons=0;
 comparison dut(.*);
 initial begin
  for(integer sample=0;sample<1088;sample++)begin
   if(sample<64)begin
    remaining_low=6'(sample);channel_low=6'h3f;
    remaining_borrow=1;high_nonzero=0;channel_high_last=1'bx;
   end else begin
    pattern=15'($urandom);
    if(sample%3==0)pattern[(sample/3)%15]=1'bx;
    if(sample%5==0)pattern[(sample/5)%15]=1'bz;
    {remaining_borrow,high_nonzero,channel_high_last,remaining_low,channel_low}=pattern;
   end
   #1;
   if(equivalent!==1'b1)$fatal(1,"Range comparison mismatch at sample %0d",sample);
""" + f"   comparisons+={count};\n" + """
  end
  $display("CHANNEL_RANGE_COMPARE_FOUR_STATE_PASS comparisons=%0d",comparisons);
  $finish;
 end
endmodule
"""


def mapping(root, out):
    wrapper = out / "range_compare_top.sv"
    wrapper.write_text("""module range_compare_top #(
 parameter int p_width=6,p_step=7,p_lane=13
)(
 input logic clk,input logic[2*p_width+2:0] data,
 output logic result_q
);
 logic[p_width-1:0] remaining_low_q,channel_low_q;
 logic remaining_borrow_q,high_nonzero_q,channel_high_last_q;
 logic allowed;
 always_ff @(posedge clk)begin
  {remaining_borrow_q,high_nonzero_q,channel_high_last_q,remaining_low_q,channel_low_q}<=data;
  result_q<=allowed;
 end
 conv_channel_range_compare #(.p_width(p_width),.p_step(p_step),.p_lane(p_lane)) u_compare(
  .i_remaining_low(remaining_low_q),.i_channel_low(channel_low_q),
  .i_remaining_borrow(remaining_borrow_q),.i_high_nonzero(high_nonzero_q),
  .i_channel_high_last(channel_high_last_q),.o_allowed(allowed)
 );
endmodule
""")
    cases = {}
    for width, step, lane in ((3, 1, 4), (4, 3, 8), (5, 0, 8), (5, 3, 5),
                              (5, 8, 8), (6, 1, 16), (6, 7, 13), (6, 16, 16)):
        name = f"width{width}_step{step}_lane{lane}"
        cases[name] = {"top": "range_compare_top", "sources": [str(wrapper), str(SOURCE)],
                       "options": [f"-Gp_width={width}", f"-Gp_step={step}", f"-Gp_lane={lane}"],
                       "configuration": "Registered inputs and output around the preserved range comparison"}
    configuration = out / "mapping_cases.json"
    configuration.write_text(json.dumps(cases, indent=2) + "\n")
    mapped = out / "mapping"
    run([sys.executable, root / "scripts/fpga/open_fpga_synth.py", "--source-root", root,
         "--out", mapped, "--case-config", configuration, "--cases", *cases], out / "mapping.log", timeout=600)
    rows = []
    for name in cases:
        directory = mapped / name
        measured = directory / "selected_paths.json"
        run([sys.executable, root / "test/conv_frontend/tools/measure_complete_paths.py",
             "--mapped", directory / "mapped.json", "--pre-lut", directory / "pre_lut.il",
             "--top", "range_compare_top", "--out", measured,
             "--scope", "high_nonzero", "high_nonzero_q", "result_q",
             "--scope", "low", "(remaining_low_q|channel_low_q)", "result_q", "--path-limit", "2"],
            directory / "selected_paths.log")
        report = json.loads(measured.read_text())
        high = report["critical_scopes"]["high_nonzero"]
        low = report["critical_scopes"]["low"]
        if (not report["graph_complete"] or not high["scope_available"] or not low["scope_available"] or
                high["maximum_combinational_cells"] != 1 or low["maximum_combinational_cells"] > 2):
            raise RuntimeError(f"Unexpected connected path depth: {measured}")
        rows.append({"case": name, "high_nonzero_cells": high["maximum_combinational_cells"],
                     "low_cells": low["maximum_combinational_cells"], "graph_complete": True,
                     "paths_sha256": digest(measured)})
        print("CHANNEL_RANGE_COMPARE_MAPPING_PASS", name, flush=True)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--reference-ref", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--iverilog", default=shutil.which("iverilog") or "iverilog")
    parser.add_argument("--vvp", default=shutil.which("vvp") or "vvp")
    parser.add_argument("--map", action="store_true", help="Map eight small registered range comparisons")
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = root / SOURCE
    tracked = [source, Path(__file__).resolve()]
    hashes = {str(path): digest(path) for path in tracked}
    reference = read_reference_file(root, args.reference_ref, str(SOURCE), text=True)
    renamed = reference
    for module in re.findall(r"\bmodule\s+(\w+)", reference):
        renamed = re.sub(r"\b" + re.escape(module) + r"\b", "reference_" + module, renamed)
    reference_file = out / "reference.sv"
    reference_file.write_text(renamed)
    cases = parameters()
    model, tb = out / "comparison.sv", out / "tb.sv"
    model.write_text(comparison(cases))
    tb.write_text(testbench(len(cases)))
    ys = out / "comparison.ys"
    ys.write_text("read_slang --top comparison " + shlex.join(map(str, [source, reference_file, model])) +
                  "\nsetattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n" +
                  "prep -top comparison -flatten\ncheck -assert\nsat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
    formal = out / "formal.log"
    run([sys.executable, root / "scripts/fpga/open_fpga_synth.py", "--worker", ys], formal)
    if "SAT proof finished - no model found: SUCCESS!" not in formal.read_text():
        raise RuntimeError(str(formal))
    print("CHANNEL_RANGE_COMPARE_FORMAL_PASS", "configurations=" + str(len(cases)), flush=True)
    binary, simulation = out / "comparison.vvp", out / "four_state.log"
    run([args.iverilog, "-g2012", "-s", "tb", "-o", binary, source, reference_file, model, tb], out / "build.log")
    run([args.vvp, binary], simulation)
    comparisons = 1088 * len(cases)
    if f"CHANNEL_RANGE_COMPARE_FOUR_STATE_PASS comparisons={comparisons}" not in simulation.read_text():
        raise RuntimeError(str(simulation))
    print("CHANNEL_RANGE_COMPARE_FOUR_STATE_PASS", "comparisons=" + str(comparisons), flush=True)
    mapped = mapping(root, out) if args.map else []
    if hashes != {str(path): digest(path) for path in tracked}:
        raise RuntimeError("Sources changed during verification")
    (out / "summary.json").write_text(json.dumps({"passed": True, "source_sha256": hashes,
        "reference_ref": args.reference_ref, "reference_sha256": hashlib.sha256(reference.encode()).hexdigest(),
        "parameter_configurations": len(cases), "parameters": cases, "formal_passed": True,
        "four_state_comparisons": comparisons, "formal_sha256": digest(formal),
        "four_state_log_sha256": digest(simulation), "mapped_cases": mapped}, indent=2) + "\n")


if __name__ == "__main__":
    main()
