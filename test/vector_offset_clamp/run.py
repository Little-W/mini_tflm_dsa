#!/usr/bin/env python3
"""从生产源码证明六十四位偏移限幅的全部输入及全部三十二位输出。"""
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
SOURCE = Path("rtl/npu/conv/vector_engine.sv")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def tokens(text):
    return re.sub(r"\s+", "", re.sub(r"//[^\n]*", "", text))


def extract(text):
    declarations = re.search(r"  logic \[32:0\] q_offset_low;.*?logic signed \[31:0\] q_clamped_data;", text, re.S)[0]
    arithmetic = re.search(r"  assign q_offset_low\s*=.*?(?=  assign ready)", text, re.S)[0]
    result = re.search(r"  assign q_clamped_data\s*=.*?;", text, re.S)[0]
    return declarations, arithmetic, result


def unit(name, expressions):
    declarations, arithmetic, result = expressions
    header = f"module {name}(input logic signed [63:0] q_rounded, input vector_engine_pkg::vector_engine_cfg_t c, output logic [33:0] observed);\n"
    return header + declarations + "\n" + arithmetic + result + \
        "\nassign observed={q_above_max,q_below_min,q_clamped_data};\nendmodule\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", default="414099fa")
    parser.add_argument("--oracle-ref", default="1c081bc")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = (ROOT / SOURCE).read_text()
    reference = read_rtl_source(f"{args.reference}:{SOURCE}", cwd=ROOT, text=True)
    oracle = read_rtl_source(f"{args.oracle_ref}:{SOURCE}", cwd=ROOT, text=True)
    current_parts, reference_parts = extract(current), extract(reference)
    normalized = current
    for new, old in zip(current_parts, reference_parts):
        normalized = normalized.replace(new, old, 1)
    if tokens(normalized) != tokens(reference):
        raise RuntimeError("Changes outside the output offset and clamp expressions require verification")
    proof = out / "offset_clamp.sv"
    oracle_body = "logic signed [63:0] q_with_offset;\n"
    oracle_body += re.search(r"assign q_with_offset\s*=.*?;", oracle, re.S)[0] + "\n"
    oracle_body += re.search(r"wire signed \[31:0\] q_clamped_data=.*?;", oracle, re.S)[0] + "\n"
    oracle_unit = ("module oracle_offset(input logic signed [63:0] q_rounded, "
        "input vector_engine_pkg::vector_engine_cfg_t c, output logic [31:0] observed);\n" +
        oracle_body + "assign observed=q_clamped_data;\nendmodule\n")
    proof.write_text(unit("current_offset", current_parts) + unit("reference_offset", reference_parts) + oracle_unit + """
module offset_clamp_proof(
  input logic signed [63:0] q_rounded,
  input vector_engine_pkg::vector_engine_cfg_t c,
  output logic equivalent
);
  logic [33:0] current_observed, reference_observed;
  logic [31:0] oracle_observed;
  current_offset u_current(.*,.observed(current_observed));
  reference_offset u_reference(.*,.observed(reference_observed));
  oracle_offset u_oracle(.*,.observed(oracle_observed));
  assign equivalent=(current_observed==reference_observed) && (current_observed[31:0]==oracle_observed);
endmodule
""")
    packages = [ROOT / "rtl/npu/conv/conv_im2col_pkg.sv", ROOT / "rtl/npu/conv/vector_engine_pkg.sv"]
    import pyosys
    library = Path(pyosys.__file__).parent / "share/xilinx/cells_sim.v"
    model = re.search(r"^module LUT6_2\b.*?^endmodule", library.read_text(), re.M | re.S)[0]
    primitive_file = out / "xilinx_primitives.sv"
    primitive_file.write_text(re.sub(r"\bspecify\b.*?\bendspecify\b", "", model, flags=re.S) + "\n")
    cases = []
    for fpga in (False, True):
        name = "fpga" if fpga else "generic"
        script, log_path = out / (name + ".ys"), out / (name + ".log")
        sources = [*packages, proof] + ([primitive_file] if fpga else [])
        defines = "-D XILINX_FPGA -D SYNTHESIS -D YOSYS -D VERIFIC " if fpga else "-D ASIC_SYNTHESIS "
        script.write_text("read_slang --top offset_clamp_proof " + defines +
            " ".join(shlex.quote(str(p)) for p in sources) +
            "\nprep -top offset_clamp_proof -flatten\nsat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
        with log_path.open("w") as log:
            subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"), "--worker", str(script)],
                           cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        if "SAT proof finished - no model found: SUCCESS!" not in log_path.read_text():
            raise RuntimeError("Offset clamp comparison incomplete: " + name)
        cases.append(dict(mode=name, passed=True, script_sha256=digest(script.read_bytes()),
                          log_sha256=digest(log_path.read_bytes())))
    report = dict(passed=True, reference_ref=args.reference,
        reference_commit=subprocess.check_output(["git", "rev-parse", args.reference], cwd=ROOT, text=True).strip(),
        oracle_commit=subprocess.check_output(["git", "rev-parse", args.oracle_ref], cwd=ROOT, text=True).strip(),
        oracle_source_sha256=digest(oracle.encode()), oracle_result_bits=32,
        source_sha256=digest(current.encode()), reference_sha256=digest(reference.encode()),
        unchanged_outside_offset_clamp=True, actual_source_expressions=True,
        relevant_input_bits=160, observed_bits=34, inputs_constrained=False,
        proof_sha256=digest(proof.read_bytes()), cases=cases,
        primitive_library_sha256=digest(library.read_bytes()),
        primitive_model_sha256=digest(primitive_file.read_bytes()),
        package_sha256={str(p.relative_to(ROOT)):digest(p.read_bytes()) for p in packages})
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
