#!/usr/bin/env python3
"""证明配置空闲计算和请求元数据选择保持全部输入及结果。"""
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
SOURCE = Path("rtl/npu/conv/conv_im2col_frontend.sv")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def tokens(text):
    return re.sub(r"\s+", "", re.sub(r"//[^\n]*", "", text))


def extract(text):
    common = re.search(r"  always_comb begin\n    current_req_index =.*?\n  end", text, re.S)[0]
    first = text.index("  assign {unused_incoming_epoch_carry, incoming_epoch_channel}")
    last = text.index("    pf_step=pf_step_q;", first)
    return common, text[first:last]


def unit(name, common, expression, declaration):
    header = f"""module {name} #(parameter int LINE_BYTES=16)(
  input logic [31:0] incoming_pixel, pixel_index, incoming_ch, ch, p_fast_y, oy,
  input logic signed [34:0] incoming_iy, iy,
  input logic [15:0] group_offset,
  input logic input_s16, short_pixel_q, incoming_context, window_index_valid_q,
  input logic [4:0] window_index_shift_q,
  output logic [195:0] observed
);
  typedef struct packed {{logic [15:0] group_offset; logic input_s16;}} config_t;
  config_t c;
  logic [31:0] current_req_index, current_req_epoch, req_index, req_epoch;
  logic [31:0] incoming_epoch_channel, incoming_req_epoch, request_output_y;
  logic signed [34:0] request_y;
  logic unused_incoming_epoch_carry, req_index_valid;
  logic [31:0] {declaration};
  assign c.group_offset=group_offset;
  assign c.input_s16=input_s16;
"""
    return header + common + "\n" + expression + "\n  end\n" + """
  assign observed={current_req_index,current_req_epoch,req_index,req_epoch,
                   request_y,request_output_y,req_index_valid};
endmodule
"""


def readiness_unit(name, parameter, body):
    return "module " + name + """(
  input logic [4:0] state,
  input logic [1:0] cfg_prepare_phase, address_step_phase,
  input logic [3:0] prefetch_phase,
  input logic cache_cfg_ready, pred_busy, pred_cfg_busy, pred_cfg_pending,
  input logic cache_cfg_pending, cache_hint_pending, request_pending,
  output logic [1:0] observed
);
  localparam logic [4:0] IDLE = 5'd0;
  logic cfg_ready, busy;
  wire prefetch_active = prefetch_phase != 4'd0;
""" + parameter + body + "\n  assign observed = {cfg_ready, busy};\nendmodule\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", default="eaba7635")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = (ROOT / SOURCE).read_text()
    reference = read_rtl_source(f"{args.reference}:{SOURCE}", cwd=ROOT, text=True)
    common, current_expression = extract(current)
    reference_common, reference_expression = extract(reference)
    parameter = re.search(r"  localparam bit p_cfg_idle_use_lut =.*?`endif\n", current, re.S)[0]
    current_ready = current[current.index("  // 配置接收与忙状态共用空闲条件"):
                            current.index("  assign finishing_tile=")]
    reference_ready = re.search(r"  assign cfg_ready =.*?;", reference, re.S)[0] + "\n"
    current_busy = re.search(r"  assign busy =.*?;", current, re.S)[0]
    reference_busy = re.search(r"  assign busy =.*?;", reference, re.S)[0]
    normalized = current.replace("  logic [31:0] incoming_req_index;", "  logic [31:0] request_pixel;", 1)
    normalized = normalized.replace(current_expression, reference_expression, 1)
    normalized = normalized.replace(parameter, "", 1).replace(current_ready, reference_ready, 1)
    normalized = normalized.replace(current_busy, reference_busy, 1)
    normalized = normalized.replace('(* fsm_encoding = "none" *) st_t state;', 'st_t state;', 1)
    if common != reference_common or tokens(normalized) != tokens(reference):
        raise RuntimeError("Changes outside readiness and request metadata require verification")
    if "typedef enum logic [4:0] {IDLE," not in current:
        raise RuntimeError("Frontend idle encoding differs")
    proof = out / "metadata.sv"
    proof.write_text(unit("current_metadata", common, current_expression, "incoming_req_index") +
        unit("reference_metadata", reference_common, reference_expression, "request_pixel") + """
module metadata_proof #(parameter int LINE_BYTES=16)(
  input logic [31:0] incoming_pixel, pixel_index, incoming_ch, ch, p_fast_y, oy,
  input logic signed [34:0] incoming_iy, iy,
  input logic [15:0] group_offset,
  input logic input_s16, short_pixel_q, incoming_context, window_index_valid_q,
  input logic [4:0] window_index_shift_q,
  output logic equivalent
);
  logic [195:0] current_observed, reference_observed;
  current_metadata #(.LINE_BYTES(LINE_BYTES)) u_current(.*,.observed(current_observed));
  reference_metadata #(.LINE_BYTES(LINE_BYTES)) u_reference(.*,.observed(reference_observed));
  assign equivalent=current_observed==reference_observed;
endmodule
""")
    cases = []
    for line_bytes in (4, 8, 16, 32, 64, 128):
        script, log_path = out / f"line{line_bytes}.ys", out / f"line{line_bytes}.log"
        script.write_text(f"read_slang --top metadata_proof -GLINE_BYTES={line_bytes} " + shlex.quote(str(proof)) +
            "\nprep -top metadata_proof -flatten\nsat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
        with log_path.open("w") as log:
            subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"), "--worker", str(script)],
                           cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        if "SAT proof finished - no model found: SUCCESS!" not in log_path.read_text():
            raise RuntimeError("Request metadata comparison incomplete")
        cases.append(dict(line_bytes=line_bytes, passed=True, script_sha256=digest(script.read_bytes()),
                          log_sha256=digest(log_path.read_bytes())))
    import pyosys
    library = Path(pyosys.__file__).parent / "share/xilinx/cells_sim.v"
    primitive = re.search(r"^module LUT6\b.*?^endmodule", library.read_text(), re.M | re.S)[0]
    primitive = re.sub(r"\bspecify\b.*?\bendspecify\b", "", primitive, flags=re.S)
    primitive_file = out / "lut6.sv"
    primitive_file.write_text(primitive + "\n")
    readiness = out / "readiness.sv"
    readiness.write_text(readiness_unit("current_readiness", parameter, current_ready + current_busy) +
        readiness_unit("reference_readiness", "", reference_ready + reference_busy) + """
module readiness_proof(
  input logic [4:0] state,
  input logic [1:0] cfg_prepare_phase, address_step_phase,
  input logic [3:0] prefetch_phase,
  input logic cache_cfg_ready, pred_busy, pred_cfg_busy, pred_cfg_pending,
  input logic cache_cfg_pending, cache_hint_pending, request_pending,
  output logic equivalent
);
  logic [1:0] current_observed, reference_observed;
  current_readiness u_current(.*,.observed(current_observed));
  reference_readiness u_reference(.*,.observed(reference_observed));
  assign equivalent = current_observed == reference_observed;
endmodule
""")
    ready_cases = []
    for mode in ("generic", "fpga"):
        script, log_path = out / (mode + "_readiness.ys"), out / (mode + "_readiness.log")
        defines = "-D XILINX_FPGA " if mode == "fpga" else "-D ASIC_SYNTHESIS "
        sources = [readiness, primitive_file] if mode == "fpga" else [readiness]
        script.write_text("read_slang --top readiness_proof " + defines +
            " ".join(shlex.quote(str(path)) for path in sources) +
            "\nprep -top readiness_proof -flatten\nsat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
        with log_path.open("w") as log:
            subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"), "--worker", str(script)],
                           cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        if "SAT proof finished - no model found: SUCCESS!" not in log_path.read_text():
            raise RuntimeError("Readiness comparison incomplete")
        ready_cases.append(dict(mode=mode, passed=True, input_bits=20, observed_bits=2,
            script_sha256=digest(script.read_bytes()), log_sha256=digest(log_path.read_bytes())))
    result = dict(passed=True, reference_ref=args.reference,
        reference_commit=subprocess.check_output(["git", "rev-parse", args.reference], cwd=ROOT, text=True).strip(),
        source_sha256=digest(current.encode()), reference_sha256=digest(reference.encode()),
        unchanged_outside_readiness_and_metadata=True, actual_source_expressions=True,
        input_bits=287, observed_bits=196, inputs_constrained=False,
        proof_sha256=digest(proof.read_bytes()), cases=cases, readiness_cases=ready_cases,
        readiness_source_sha256=digest(readiness.read_bytes()),
        state_encoding="Declared five-bit binary encoding",
        primitive_library_sha256=digest(library.read_bytes()), primitive_sha256=digest(primitive_file.read_bytes()))
    (out / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
