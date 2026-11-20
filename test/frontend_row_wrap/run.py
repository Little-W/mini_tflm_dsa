#!/usr/bin/env python3
"""直接读取前端源码，证明行尾等式及其进位条件对全部输入等价。"""
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
    start = text.index("  assign p_delta =")
    end = text.index("  always_comb begin", start)
    arithmetic = text[start:end]
    condition_start = text.index("end else if (last_p_valid && p_decode>=last_p")
    condition = re.search(r"      p_fast_wrap = .*?;", text[condition_start:], re.S)[0]
    declarations = text[text.index("  logic [15:0] p_delta;"):text.index("  logic incoming_fast,")]
    return arithmetic, condition, declarations


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", default="fa66f107")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = (ROOT / SOURCE).read_text()
    reference = read_rtl_source(f"{args.reference}:{SOURCE}", cwd=ROOT, text=True)
    current_arithmetic, current_condition, declarations = extract(current)
    reference_arithmetic, reference_condition, reference_declarations = extract(reference)
    normalized = current.replace(current_arithmetic, reference_arithmetic, 1).replace(current_condition, reference_condition, 1)
    normalized = normalized.replace(declarations, reference_declarations, 1)
    if tokens(normalized) != tokens(reference):
        raise RuntimeError("Changes outside the row-end expressions require verification")
    modules = []
    for name, arithmetic, condition, local_declarations in [
            ("current_row_end", current_arithmetic, current_condition, declarations),
            ("reference_row_end", reference_arithmetic, reference_condition, reference_declarations)]:
        modules.append(f"""module {name}(
  input logic [31:0] p_decode, last_p,
  input logic [15:0] last_x, output_w, last_output_col_q,
  output logic [2:0] result
);
{local_declarations}
{arithmetic.replace('c.output_w', 'output_w')}
  logic p_fast_wrap;
  always_comb begin
{condition.replace('c.output_w', 'output_w')}
  end
  assign result={{p_fast_wrap,p_sum_wrap_o_equal,p_sum_last_o_equal}};
endmodule
""")
    modules.append("""module row_end_proof(
  input logic [31:0] p_decode, last_p,
  input logic [15:0] last_x, output_w, last_output_col_q,
  output logic equivalent
);
  wire [2:0] current_result, reference_result;
  current_row_end u_current(.*,.result(current_result));
  reference_row_end u_reference(.*,.result(reference_result));
  assign equivalent=current_result==reference_result;
endmodule
""")
    proof = out / "row_end.sv"
    proof.write_text("\n".join(modules))
    helper = ROOT / "rtl/common/add_equal.sv"
    import pyosys
    library = Path(pyosys.__file__).parent / "share/xilinx/cells_sim.v"
    model = re.search(r"^module LUT6\b.*?^endmodule", library.read_text(), re.M | re.S)[0]
    primitive_file = out / "xilinx_primitives.sv"
    primitive_file.write_text(re.sub(r"\bspecify\b.*?\bendspecify\b", "", model, flags=re.S) + "\n")
    cases = []
    for fpga in (False, True):
        name = "fpga" if fpga else "generic"
        script, log_path = out / (name + ".ys"), out / (name + ".log")
        sources = [proof, helper] + ([primitive_file] if fpga else [])
        defines = "-D XILINX_FPGA -D SYNTHESIS -D YOSYS -D VERIFIC " if fpga else ""
        script.write_text("read_slang --top row_end_proof " + defines +
            " ".join(shlex.quote(str(p)) for p in sources) +
            "\nprep -top row_end_proof -flatten\nsat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
        with log_path.open("w") as log:
            subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"), "--worker", str(script)],
                           cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        if "SAT proof finished - no model found: SUCCESS!" not in log_path.read_text():
            raise RuntimeError("Row-end comparison incomplete: " + name)
        cases.append(dict(mode=name, passed=True, script_sha256=digest(script.read_bytes()), log_sha256=digest(log_path.read_bytes())))
    report = dict(passed=True, reference_ref=args.reference,
        reference_commit=subprocess.check_output(["git", "rev-parse", args.reference], cwd=ROOT, text=True).strip(),
        source_sha256=digest(current.encode()), reference_sha256=digest(reference.encode()),
        unchanged_outside_row_end_expressions=True, actual_source_expressions=True,
        input_bits=112, result_bits=3, inputs_constrained=False,
        helper_sha256=digest(helper.read_bytes()),
        reference_helper_sha256=digest(read_rtl_source(f"{args.reference}:rtl/common/add_equal.sv", cwd=ROOT)),
        primitive_library_sha256=digest(library.read_bytes()), primitive_model_sha256=digest(primitive_file.read_bytes()),
        proof_sha256=digest(proof.read_bytes()), cases=cases)
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
