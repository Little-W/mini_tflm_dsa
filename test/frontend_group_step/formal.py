#!/usr/bin/env python3
"""证明实际前端增量范围比较在任意通道、阈值和有效通道组合下等价。"""
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
SOURCE = "rtl/npu/conv/conv_im2col_frontend.sv"
START = "      if (source == 5) begin : g_advancing_channel\n"
END = "      end else begin : g_saved_channel"
PORTS = (("ch_q", "16"), ("group_c", "16"), ("last_group_channel_q", "16"),
         ("group_minus_two_q", "16"), ("group_minus_three_q", "16"),
         ("chunk_lane_allowed", "LANES"))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def extract(text):
    start = text.index(START)
    end = text.index(END, start)
    return text[start:end]


def extract_range(text):
    start = text.index("      for (genvar lane = 0; lane < 4; lane++) begin : g_lane", text.index(START))
    end = text.index("    end\n    // 范围标志", start)
    return text[start:end]


def unit(name, body, range_body):
    ports = ",\n".join("  input logic [" + width + "-1:0] " + signal for signal, width in PORTS)
    return "module " + name + """ #(
  parameter int LANES = 4,
  parameter bit p_cfg_idle_use_lut = 1'b0,
  parameter int CHUNK_COUNT_W = $clog2(LANES + 1)
)(
""" + ports + """,
  output logic [7:0] observed
);
  typedef struct packed {logic [15:0] group_c;} config_t;
  config_t c;
  logic [CHUNK_COUNT_W-1:0] chunk_count;
  localparam int source = 5;
  logic [5:0][3:0] group_range_next;
  logic group_has_channel, one_channel, two_channels, three_channels;
  assign c.group_c = group_c;
  always_comb begin
    chunk_count = '0;
    for (int lane = 0; lane < LANES; lane++) begin
      if (chunk_lane_allowed[lane]) chunk_count = CHUNK_COUNT_W'(lane + 1);
    end
  end
""" + body.replace(START, "  if (1) begin : g_advancing_channel\n", 1) + """
  end
""" + range_body + """
  assign observed = {group_range_next[5], three_channels, two_channels, one_channel, group_has_channel};
endmodule
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", default="3c8cafeb")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = (ROOT / SOURCE).read_text()
    reference = read_rtl_source(args.reference + ":" + SOURCE, cwd=ROOT, text=True)
    bodies = {"reference": extract(reference), "current": extract(current)}
    range_bodies = {"reference": extract_range(reference), "current": extract_range(current)}
    normalized = current.replace(bodies["current"], bodies["reference"], 1)
    normalized = normalized.replace(range_bodies["current"], range_bodies["reference"], 1)
    if normalized != reference:
        raise RuntimeError("Additional frontend changes require verification")
    updates = re.findall(r"\bchunk_count\s*=(?!=)\s*([^;]+);", current)
    if updates != ["'0", "CHUNK_COUNT_W'(lane+1)"]:
        raise RuntimeError("The chunk encoder has additional assignments")
    if "if (chunk_lane_allowed[lane]) chunk_count=CHUNK_COUNT_W'(lane+1);" not in current:
        raise RuntimeError("The chunk encoder must select the final valid lane")
    helper = ROOT / "rtl/common/add_equal.sv"
    helper_data = helper.read_bytes()
    if helper_data != read_rtl_source(args.reference + ":rtl/common/add_equal.sv", cwd=ROOT):
        raise RuntimeError("The comparison helper must match the reference")
    (out / "add_equal.sv").write_bytes(helper_data)
    units = {}
    for label, body in bodies.items():
        units[label] = unit(label + "_range", body, range_bodies[label])
        (out / (label + ".sv")).write_text(units[label])
    import pyosys
    model_file = Path(pyosys.__file__).parent / "share/xilinx/cells_sim.v"
    official = model_file.read_text()
    lut_model = re.search(r"module LUT6\s*\(.*?\bendmodule\b", official, re.S)[0]
    models = out / "xilinx_lut6.v"
    models.write_text(lut_model + "\n")
    ports = ",\n".join("  input logic [" + width + "-1:0] " + signal for signal, width in PORTS)
    miter = out / "comparison.sv"
    miter.write_text(units["reference"] + units["current"] + """module range_proof #(
  parameter int LANES = 4,
  parameter bit p_cfg_idle_use_lut = 1'b0
)(
""" + ports + """,
  output logic equivalent
);
  logic [7:0] expected, actual;
  reference_range #(.LANES(LANES), .p_cfg_idle_use_lut(p_cfg_idle_use_lut)) u_reference (
    .*, .observed(expected)
  );
  current_range #(.LANES(LANES), .p_cfg_idle_use_lut(p_cfg_idle_use_lut)) u_current (
    .*, .observed(actual)
  );
  assign equivalent = expected[3:0] == actual[3:0];
endmodule
""")
    cases = []
    for fpga in (0, 1):
        for lanes in (1, 2, 3, 4):
            label = f"lanes{lanes}_fpga{fpga}"
            script, log = out / (label + ".ys"), out / (label + ".log")
            script.write_text("read_slang --top range_proof -GLANES=" + str(lanes) +
                " -Gp_cfg_idle_use_lut=" + str(fpga) + " " +
                " ".join(shlex.quote(str(path)) for path in (models, out / "add_equal.sv", miter)) +
                "\nprep -top range_proof -flatten\ndelete t:$specify2\n" +
                "sat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
            with log.open("w") as stream:
                subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                    "--worker", str(script)], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
            if "SAT proof finished - no model found: SUCCESS!" not in log.read_text():
                raise RuntimeError("The range proof did not complete")
            cases.append(dict(lanes=lanes, fpga=bool(fpga), input_bits=80 + lanes,
                observed_bits=4, passed=True, log_sha256=digest(log.read_bytes())))
            print(label, "passed", flush=True)
    merge_units = []
    for label, body in range_bodies.items():
        merge_units.append("module " + label + """_merge #(
  parameter int source = 5,
  parameter bit p_cfg_idle_use_lut = 1'b0
)(input logic group_has_channel, one_channel, two_channels, three_channels,
  output logic [3:0] observed);
  logic [5:0][3:0] group_range_next;
""" + body + "\nassign observed = group_range_next[source];\nendmodule\n")
    merge = out / "range_merge.sv"
    merge.write_text("\n".join(merge_units) + """module merge_proof #(
  parameter int source = 5,
  parameter bit p_cfg_idle_use_lut = 1'b0
)(input logic group_has_channel, one_channel, two_channels, three_channels,
  output logic equivalent);
  logic [3:0] expected, actual;
  reference_merge #(.source(source), .p_cfg_idle_use_lut(p_cfg_idle_use_lut)) u_reference (.*,.observed(expected));
  current_merge #(.source(source), .p_cfg_idle_use_lut(p_cfg_idle_use_lut)) u_current (.*,.observed(actual));
  assign equivalent = expected == actual;
endmodule
""")
    merge_cases = []
    for fpga in (0, 1):
        for source in (0, 5):
            label = f"merge_source{source}_fpga{fpga}"
            script, log = out / (label + ".ys"), out / (label + ".log")
            script.write_text("read_slang --top merge_proof -Gsource=" + str(source) +
                " -Gp_cfg_idle_use_lut=" + str(fpga) + " " +
                shlex.quote(str(models)) + " " + shlex.quote(str(merge)) +
                "\nprep -top merge_proof -flatten\ndelete t:$specify2\n" +
                "sat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
            with log.open("w") as stream:
                subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                    "--worker", str(script)], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
            if "SAT proof finished - no model found: SUCCESS!" not in log.read_text():
                raise RuntimeError("The range merge proof did not complete")
            merge_cases.append(dict(source=source, fpga=bool(fpga), input_bits=4,
                observed_bits=4, passed=True, log_sha256=digest(log.read_bytes())))
            print(label, "passed", flush=True)
    report = dict(passed=True, reference_ref=args.reference,
        reference_commit=subprocess.check_output(["git", "rev-parse", args.reference], cwd=ROOT, text=True).strip(),
        source_sha256=digest(current.encode()), reference_sha256=digest(reference.encode()),
        unchanged_outside_advancing_range=True, actual_source_expressions=True,
        chunk_count_driver_checked=True, inputs_constrained=False, cases=cases,
        compositional_range_merge=True, merge_cases=merge_cases,
        range_merge_sha256=digest(merge.read_bytes()),
        helper_sha256=digest(helper_data), helper_unchanged=True,
        official_lut6_sha256=digest(models.read_bytes()), official_model_sha256=digest(model_file.read_bytes()),
        proof_sha256=digest(miter.read_bytes()))
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
