#!/usr/bin/env python3
"""对全部字数据、状态和字节偏移证明前端固定字节选择。"""
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", default="2bd1d2b3")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = (ROOT / SOURCE).read_text()
    reference = read_rtl_source(f"{args.reference}:{SOURCE}", cwd=ROOT, text=True)
    start = current.index("    // 字内偏移只有四种取值，固定字节选择直接形成当前写入数据。")
    end = current.index("    endcase", start) + len("    endcase")
    selection = current[start:end]
    source = re.search(r"  assign stream_word =.*?;", current, re.S)[0]
    original = re.search(r"    selected_word = .*?;", reference, re.S)[0]
    normalized = current.replace("  logic [31:0] stream_word;\n", "", 1).replace(source, "", 1)
    normalized = normalized.replace(selection, original, 1)
    if tokens(normalized) != tokens(reference):
        raise RuntimeError("Changes outside byte selection require verification")
    enum = re.search(r"typedef enum logic \[4:0\] \{(.*?)\} st_t;", current, re.S)[1]
    wait_state = [name.strip() for name in enum.split(",")].index("WAIT_WORD")
    proof = out / "byte_selection.sv"
    proof.write_text(f"""module byte_selection_proof(
    input logic [31:0] cache_rsp_data, word_buf,
    input logic [4:0] state,
    input logic [1:0] addr,
    output logic equivalent
);
  localparam logic [4:0] WAIT_WORD=5'd{wait_state};
  logic [31:0] selected_word, reference_word, stream_word;
{source}
  always_comb begin
{selection}
{original.replace('selected_word', 'reference_word')}
  end
  assign equivalent=selected_word==reference_word;
endmodule
""")
    script, log_path = out / "run.ys", out / "formal.log"
    script.write_text("read_slang --top byte_selection_proof " + shlex.quote(str(proof)) +
        "\nprep -top byte_selection_proof -flatten\nsat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
    with log_path.open("w") as log:
        subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"), "--worker", str(script)],
                       cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    if "SAT proof finished - no model found: SUCCESS!" not in log_path.read_text():
        raise RuntimeError("Byte selection comparison incomplete")
    report = dict(passed=True, reference_ref=args.reference,
        reference_commit=subprocess.check_output(["git", "rev-parse", args.reference], cwd=ROOT, text=True).strip(),
        source_sha256=digest(current.encode()), reference_sha256=digest(reference.encode()),
        unchanged_outside_byte_selection=True, actual_source_expressions=True,
        input_bits=71, result_bits=32, inputs_constrained=False,
        proof_sha256=digest(proof.read_bytes()), script_sha256=digest(script.read_bytes()),
        log_sha256=digest(log_path.read_bytes()))
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
