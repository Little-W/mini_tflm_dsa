#!/usr/bin/env python3
"""证明实际数据字命中表达式在全部输入位模式下等价。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[3]
SOURCE = "rtl/npu/conv/conv_im2col_frontend.sv"
MARKER = "  // 数据字匹配只需要高三十位的加法等式，低两位单独提供进位。\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-ref", default="8c669a70")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = (ROOT / SOURCE).read_text()
    reference = read_rtl_source(args.reference_ref + ":" + SOURCE, cwd=ROOT, text=True)
    start = current.index(MARKER)
    end = current.index("  if (CHUNK_COUNT_W + 1 < 32)", start)
    body = current[start:end]
    declaration = re.search(r"  logic \[31:0\] next_tap_delta, incoming_delta;.*?"
                            r"  logic incoming_live_word_o_equal;\n", current, re.S).group(0)
    current_hit = re.search(r"  assign incoming_word_hit\s*=.*?;", current, re.S).group(0)
    reference_hit = re.search(r"  assign incoming_word_hit\s*=.*?;", reference, re.S).group(0)
    model = out / "word_match.sv"
    model.write_text("""module word_match_proof (
input logic [31:0] tap_group_base,row_base_addr,addr,word_addr,
input logic [31:0] tap_wrap_bytes,tap_step_bytes,tile_q0,q0,
input logic tap_wrap,incoming_tap_wrap,finishing_tile,state,word_valid,
output logic equivalent
);
localparam logic WAIT_WORD=1'b1;
logic [31:0] next_tap_addr,incoming_addr;
logic incoming_word_hit,reference_incoming_word_hit;
""" + declaration + body + current_hit + "\n" +
        "assign next_tap_addr=tap_group_base+(tap_wrap ? tap_wrap_bytes : tap_step_bytes);\n"
        "assign incoming_addr=tile_q0==q0 ? row_base_addr :\n"
        " row_base_addr+(incoming_tap_wrap ? tap_wrap_bytes : tap_step_bytes);\n" +
        reference_hit.replace("incoming_word_hit", "reference_incoming_word_hit") + "\n"
        "assign equivalent=next_word_o_equal==(next_tap_addr[31:2]==addr[31:2]) &&\n"
        " incoming_word_hit==reference_incoming_word_hit;\nendmodule\n")
    script = out / "prove.ys"
    script.write_text("read_slang --top word_match_proof " + shlex.quote(str(model)) + " " +
                     shlex.quote(str(ROOT / "rtl/common/add_equal.sv")) + "\n"
                     "prep -top word_match_proof -flatten\nsat -verify -prove equivalent 1\n")
    log = out / "formal.log"
    with log.open("w") as stream:
        subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"), "--worker", str(script)],
                       cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
    if "SAT proof finished - no model found: SUCCESS!" not in log.read_text():
        raise RuntimeError("Word match proof incomplete")
    report = dict(passed=True, reference_ref=args.reference_ref, input_bits=261, compared_bits=2,
        inputs_constrained=False,
        source_sha256=hashlib.sha256(current.encode()).hexdigest(),
        reference_sha256=hashlib.sha256(reference.encode()).hexdigest(),
        model_sha256=hashlib.sha256(model.read_bytes()).hexdigest(),
        log_sha256=hashlib.sha256(log.read_bytes()).hexdigest())
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
