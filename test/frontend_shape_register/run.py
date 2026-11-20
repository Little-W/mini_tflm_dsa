#!/usr/bin/env python3
"""证明配置形状判断寄存前后逐周期等价，并核对完整前端源码。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("rtl/npu/conv/conv_im2col_frontend.sv")
CHECK = Path("rtl/common/onehot_check.sv")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def shape_block(source):
    start = source.index("  logic [15:0] group_shape_i_value;")
    end = source.index("  function automatic logic [4:0] power_shift", start)
    return source[start:end]


def verify_config_state(source):
    assignments = re.findall(r"\bc\s*<=\s*([^;]+);", source)
    if assignments != ["'0", "cfg"]:
        raise RuntimeError("Configuration storage requires an explicit proof")
    reset = source.index("c<='0;")
    block = source.rfind("  always_ff @(posedge clk or negedge rst_n) begin", 0, reset)
    if not re.fullmatch(r"\s*if\s*\(!rst_n\)\s*begin\s*state<=IDLE;\s*",
                        source[block:].split("begin", 1)[1].split("c<='0;", 1)[0]):
        raise RuntimeError("Configuration reset guard changed")
    update = source.index("c<=cfg;")
    guard = source.rfind("if (cfg_valid && cfg_ready) begin", block, update)
    if guard < block or re.search(r"\b(begin|end)\b", source[guard:].split("begin", 1)[1].split("c<=cfg;", 1)[0]):
        raise RuntimeError("Configuration acceptance guard changed")
    return assignments


def unit(name, block, assignments):
    return f"""module {name}(
    input logic clk, rst_n, cfg_valid, cfg_ready,
    input logic [15:0] cfg_group_c, cfg_kernel_w,
    output logic [33:0] observed
);
  typedef struct packed {{logic [15:0] group_c, kernel_w;}} cfg_t;
  cfg_t c, cfg;
  assign cfg.group_c = cfg_group_c;
  assign cfg.kernel_w = cfg_kernel_w;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) c <= {assignments[0]};
    else if (cfg_valid && cfg_ready) c <= {assignments[1]};
  end
{block}
  assign observed = {{c, group_shape_o_valid, kernel_shape_o_valid}};
endmodule
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", default="a0742c45")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = (ROOT / SOURCE).read_text()
    reference = subprocess.check_output(["git", "show", f"{args.reference}:{SOURCE}"], cwd=ROOT, text=True)
    current_block, reference_block = shape_block(current), shape_block(reference)
    if current.replace(current_block, reference_block, 1) != reference:
        raise RuntimeError("Changes outside the shape checks require separate verification")
    current_assignments = verify_config_state(current)
    reference_assignments = verify_config_state(reference)
    proof = out / "shape_register_proof.sv"
    proof.write_text(unit("shape_reference", reference_block, reference_assignments) +
                     unit("shape_current", current_block, current_assignments) + """
module shape_register_proof(
    input logic clk, rst_n, cfg_valid, cfg_ready,
    input logic [15:0] cfg_group_c, cfg_kernel_w,
    output logic equivalent
);
  logic [33:0] reference_observed, current_observed;
  shape_reference u_reference(
    .clk(clk), .rst_n(rst_n), .cfg_valid(cfg_valid), .cfg_ready(cfg_ready),
    .cfg_group_c(cfg_group_c), .cfg_kernel_w(cfg_kernel_w), .observed(reference_observed));
  shape_current u_current(
    .clk(clk), .rst_n(rst_n), .cfg_valid(cfg_valid), .cfg_ready(cfg_ready),
    .cfg_group_c(cfg_group_c), .cfg_kernel_w(cfg_kernel_w), .observed(current_observed));
  assign equivalent = reference_observed == current_observed;
endmodule
""")
    import pyosys
    library = Path(pyosys.__file__).parent / "share/xilinx/cells_sim.v"
    library_text = library.read_text()
    models = []
    for name in ("LUT6", "LUT6_2"):
        match = re.search(r"^module " + name + r"\b.*?^endmodule", library_text, re.M | re.S)
        if match is None:
            raise RuntimeError("Missing official primitive model: " + name)
        models.append(re.sub(r"\bspecify\b.*?\bendspecify\b", "", match[0], flags=re.S))
    primitive_file = out / "xilinx_primitives.sv"
    primitive_file.write_text("\n\n".join(models) + "\n")
    cases = []
    for fpga in (False, True):
        name = "fpga" if fpga else "generic"
        script, log_path = out / (name + ".ys"), out / (name + ".log")
        sources = [ROOT / CHECK, proof] + ([primitive_file] if fpga else [])
        defines = "-D XILINX_FPGA -D SYNTHESIS -D YOSYS -D VERIFIC " if fpga else ""
        script.write_text("read_slang --top shape_register_proof " + defines +
            " ".join(shlex.quote(str(path)) for path in sources) +
            "\nprep -top shape_register_proof -flatten\nasync2sync\n" +
            "sat -verify -seq 2 -tempinduct -set-at 1 rst_n 0 -prove equivalent 1 -maxsteps 8\n")
        with log_path.open("w") as log:
            subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                            "--worker", str(script)], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        if "Induction step proven: SUCCESS!" not in log_path.read_text():
            raise RuntimeError("Sequential comparison incomplete: " + name)
        cases.append(dict(mode=name, passed=True, observed_bits=34, shape_result_bits=2,
                          log_sha256=digest(log_path.read_bytes()), script_sha256=digest(script.read_bytes())))
    report = dict(passed=True, reference_ref=args.reference,
        reference_commit=subprocess.check_output(["git", "rev-parse", args.reference], cwd=ROOT, text=True).strip(),
        source_sha256=digest(current.encode()), reference_sha256=digest(reference.encode()),
        unchanged_outside_shape_checks=True, source_blocks_used_directly=True,
        configuration_updates_from_source=True, initial_reset=True, later_inputs_constrained=False,
        configuration_input_bits=32, observed_bits_per_case=34, added_register_bits=2,
        check_sha256=digest((ROOT / CHECK).read_bytes()), proof_sha256=digest(proof.read_bytes()),
        official_primitive_library_sha256=digest(library.read_bytes()),
        primitive_model_sha256=digest(primitive_file.read_bytes()), cases=cases)
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
