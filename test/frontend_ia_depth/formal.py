#!/usr/bin/env python3
"""证明预测器配置状态与前端通道范围优化的全部输入行为。"""
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
FRONTEND = "rtl/npu/conv/conv_im2col_frontend.sv"
PREDICTOR = "rtl/npu/dma/cache/conv_next_use_predictor.sv"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(script, log):
    with log.open("w") as stream:
        subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                        "--worker", str(script)], cwd=ROOT, stdout=stream,
                       stderr=subprocess.STDOUT, check=True)


def group_block(text):
    first = text.index("  if (LANES <= 4) begin : g_short_group_lane")
    last = text.index("  end else if (LANES <= 32768)", first)
    return text[first:last] + "  end\n"


def unit(name, block, group_end):
    return "module " + name + """ #(
  parameter int LANES=4,
  localparam int CHUNK_COUNT_W=$clog2(LANES+1)
)(
  input logic [15:0] ch_q, group_c, cfg_group_c,
  input logic [15:0] last_group_channel_q, group_minus_two_q, group_minus_three_q,
  input logic [4:0][15:0] saved_channel,
  input logic [LANES-1:0] chunk_lane_allowed,
  output logic [28+LANES:0] observed
);
  localparam bit p_cfg_idle_use_lut =
`ifdef XILINX_FPGA
    1'b1;
`else
    1'b0;
`endif
  typedef struct packed {logic [15:0] group_c;} cfg_t;
  cfg_t c, cfg;
  logic [5:0][15:0] group_range_channel;
  logic [5:0][3:0] group_range_next;
  logic [3:0] group_range_cfg, group_range_q;
  logic [LANES-1:0] group_lane_allowed;
  logic [CHUNK_COUNT_W-1:0] chunk_count;
  always_comb begin
    chunk_count='0;
    for(int lane=0;lane<LANES;lane++)
      if(chunk_lane_allowed[lane]) chunk_count=CHUNK_COUNT_W'(lane+1);
  end
  assign c.group_c=group_c;
  assign cfg.group_c=cfg_group_c;
  assign group_range_channel[4:0]=saved_channel;
  assign group_range_channel[5]=ch_q+16'(chunk_count);
  assign group_range_q=group_range_next[5];
""" + group_end + block + """
  assign observed={group_end_o_equal,group_range_cfg,group_range_next,group_lane_allowed};
endmodule
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference", default="47e51eff")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    originals = {name: read_rtl_source(args.reference + ":" + name, cwd=ROOT, text=True) for name in (FRONTEND, PREDICTOR)}
    current = (ROOT / FRONTEND).read_text()
    block, reference_block = group_block(current), group_block(originals[FRONTEND])
    group_end = current[current.index("  logic [16:0] group_end_i_a"):
                        current.index("  if (LANES <= 4) begin : g_short_group_lane")]
    normalized = current.replace(block[:-6], reference_block[:-6], 1).replace(group_end, "", 1)
    normalized = normalized.replace("else if (group_end_o_equal)",
                                    "else if (17'(chunk_count)==group_remaining)", 1)
    if normalized.replace("\n\n  if (LANES <= 4)", "\n  if (LANES <= 4)", 1) != \
            originals[FRONTEND].replace("\n\n  if (LANES <= 4)", "\n  if (LANES <= 4)", 1):
        raise RuntimeError("Frontend changes outside the group-range expression require verification")
    reference_end = "  logic group_end_o_equal;\n" + \
        "  assign group_end_o_equal=17'(chunk_count)==({1'b0,c.group_c}-{1'b0,ch_q});\n"
    proof = out / "group_range.sv"
    proof.write_text(unit("current_range", block, group_end) +
                     unit("reference_range", reference_block, reference_end) + """
module range_proof #(parameter int LANES=4, localparam int CHUNK_COUNT_W=$clog2(LANES+1))(
  input logic [15:0] ch_q, group_c, cfg_group_c,
  input logic [15:0] last_group_channel_q, group_minus_two_q, group_minus_three_q,
  input logic [4:0][15:0] saved_channel,
  input logic [LANES-1:0] chunk_lane_allowed,
  output logic equivalent
);
  logic [28+LANES:0] current_value, reference_value;
  current_range #(.LANES(LANES)) u_current(.*,.observed(current_value));
  reference_range #(.LANES(LANES)) u_reference(.*,.observed(reference_value));
  assign equivalent=current_value==reference_value;
endmodule
""")
    import pyosys
    library = Path(pyosys.__file__).parent / "share/xilinx/cells_sim.v"
    primitive = re.search(r"^module LUT6\b.*?^endmodule", library.read_text(), re.M | re.S)[0]
    model = out / "lut6.sv"
    model.write_text(re.sub(r"\bspecify\b.*?\bendspecify\b", "", primitive, flags=re.S) + "\n")
    cases = []
    for lanes in (1, 2, 3, 4):
        for fpga in (False, True):
            label = f"lanes{lanes}_" + ("fpga" if fpga else "generic")
            script, log = out / (label + ".ys"), out / (label + ".log")
            script.write_text(f"read_slang --top range_proof -GLANES={lanes} " +
                ("-D XILINX_FPGA " if fpga else "") +
                " ".join(map(shlex.quote, (str(proof), str(ROOT / "rtl/common/add_equal.sv"), str(model)))) +
                "\nprep -top range_proof -flatten\ntechmap\nopt\nabc -g simple\nopt_clean\n" +
                "sat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
            run(script, log)
            if "SAT proof finished - no model found: SUCCESS!" not in log.read_text():
                raise RuntimeError("Channel range comparison is incomplete")
            cases.append(dict(lanes=lanes, fpga=fpga, passed=True, log_sha256=digest(log)))
    wide_proof = out / "wide_group_end.sv"
    wide_proof.write_text("""module wide_group_end_proof(
  input logic [15:0] ch_q, group_c,
  input logic [16:0] chunk_count,
  output logic equivalent
);
  localparam int LANES=8;
  localparam bit p_cfg_idle_use_lut =
`ifdef XILINX_FPGA
    1'b1;
`else
    1'b0;
`endif
  typedef struct packed {logic [15:0] group_c;} cfg_t;
  cfg_t c;
  assign c.group_c=group_c;
""" + group_end + """
  assign equivalent=group_end_o_equal==(chunk_count==({1'b0,group_c}-{1'b0,ch_q}));
endmodule
""")
    wide_cases = []
    for fpga in (False, True):
        label = "wide_end_" + ("fpga" if fpga else "generic")
        script, log = out / (label + ".ys"), out / (label + ".log")
        script.write_text("read_slang --top wide_group_end_proof " +
            ("-D XILINX_FPGA " if fpga else "") + " ".join(map(shlex.quote,
            (str(wide_proof), str(ROOT / "rtl/common/add_equal.sv"), str(model)))) +
            "\nprep -top wide_group_end_proof -flatten\ntechmap\nopt\nabc -g simple\nopt_clean\n" +
            "sat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
        run(script, log)
        if "SAT proof finished - no model found: SUCCESS!" not in log.read_text():
            raise RuntimeError("Wide group-end comparison is incomplete")
        wide_cases.append(dict(fpga=fpga, passed=True, unconstrained_input_bits=49,
                               log_sha256=digest(log)))
    folder = out / "predictor"
    folder.mkdir(exist_ok=True)
    saved = folder / "reference.sv"
    saved.write_text(originals[PREDICTOR])
    commands = []
    for name, source in (("reference", saved), ("current", ROOT / PREDICTOR)):
        commands += ["read_slang --top conv_next_use_predictor " + " ".join(map(shlex.quote,
            (str(ROOT / "rtl/npu/conv/conv_im2col_pkg.sv"), str(ROOT / "rtl/common/onehot_check.sv"), str(source)))),
            "prep -top conv_next_use_predictor -flatten", "async2sync", "opt_clean",
            "rename conv_next_use_predictor " + name, "design -stash " + name]
    commands += ["design -copy-from reference -as reference reference",
                 "design -copy-from current -as current current", "equiv_make reference current equivalent",
                 "hierarchy -top equivalent", "equiv_simple -seq 1", "opt_clean",
                 "equiv_induct -seq 2", "equiv_status -assert"]
    script, log = folder / "run.ys", folder / "formal.log"
    script.write_text("\n".join(commands) + "\n")
    run(script, log)
    if "Equivalence successfully proven" not in log.read_text():
        raise RuntimeError("Predictor temporal equivalence is incomplete")
    report = dict(passed=True, reference_commit=subprocess.check_output(
        ["git", "rev-parse", args.reference], cwd=ROOT, text=True).strip(), inputs_constrained=False,
        source_sha256={name: digest(ROOT / name) for name in (FRONTEND, PREDICTOR)},
        reference_sha256={name: hashlib.sha256(text.encode()).hexdigest() for name, text in originals.items()},
        group_range_cases=cases, wide_group_end_cases=wide_cases, unchanged_frontend_outside_group_range=True,
        predictor_full_module_equivalent=True, predictor_log_sha256=digest(log),
        primitive_source_sha256=digest(library), primitive_model_sha256=digest(model))
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
