#!/usr/bin/env python3
"""使用官方 LUT 模型验证加法等式模块的通用及并行比较实现。"""
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
SOURCE = Path("rtl/common/add_equal.sv")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", default="fa66f107")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference = read_rtl_source(f"{args.reference}:{SOURCE}", cwd=ROOT)
    reference_file = out / "reference_add_equal.sv"
    reference_file.write_text(reference.decode().replace("module add_equal #(", "module reference_add_equal #(", 1))
    import pyosys
    library = Path(pyosys.__file__).parent / "share/xilinx/cells_sim.v"
    model = re.search(r"^module LUT6\b.*?^endmodule", library.read_text(), re.M | re.S)[0]
    primitive_file = out / "xilinx_primitives.sv"
    primitive_file.write_text(re.sub(r"\bspecify\b.*?\bendspecify\b", "", model, flags=re.S) + "\n")
    cases = []
    for width in (1, 6, 7, 16, 32, 33):
        proof = out / f"width_{width}.sv"
        proof.write_text(f"""module helper_proof(
  input logic [{width-1}:0] i_a, i_b, i_target,
  input logic i_carry_in,
  output logic equivalent
);
  logic reference_equal, generic_equal, lut_equal;
  reference_add_equal #(.p_width({width})) u_reference(.*,.o_equal(reference_equal));
  add_equal #(.p_width({width})) u_generic(.*,.o_equal(generic_equal));
  add_equal #(.p_width({width}),.p_use_lut(1'b1)) u_lut(.*,.o_equal(lut_equal));
  assign equivalent=(reference_equal==generic_equal)&&(reference_equal==lut_equal);
endmodule
""")
        script, log_path = out / f"width_{width}.ys", out / f"width_{width}.log"
        sources = [ROOT / SOURCE, reference_file, primitive_file, proof]
        script.write_text("read_slang --top helper_proof -D SYNTHESIS -D YOSYS -D VERIFIC " +
            " ".join(shlex.quote(str(p)) for p in sources) +
            "\nprep -top helper_proof -flatten\nsat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
        with log_path.open("w") as log:
            subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"), "--worker", str(script)],
                           cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        if "SAT proof finished - no model found: SUCCESS!" not in log_path.read_text():
            raise RuntimeError("Helper comparison incomplete")
        cases.append(dict(width=width, input_bits=3*width+1, inputs_constrained=False,
                          generic_equal=True, lut_equal=True, proof_sha256=digest(proof.read_bytes()),
                          log_sha256=digest(log_path.read_bytes()), script_sha256=digest(script.read_bytes())))
    report = dict(passed=True, source_sha256=digest((ROOT / SOURCE).read_bytes()),
        reference_sha256=digest(reference), reference_ref=args.reference,
        reference_commit=subprocess.check_output(["git", "rev-parse", args.reference], cwd=ROOT, text=True).strip(),
        primitive_library_sha256=digest(library.read_bytes()),
        primitive_model_sha256=digest(primitive_file.read_bytes()), cases=cases)
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
