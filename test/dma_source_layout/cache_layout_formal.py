#!/usr/bin/env python3
"""证明八通道紧凑字节及宽数据对任意列起点的排列。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "rtl/npu/loaders/ia_loader_cache_mgr.sv"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    text = SOURCE.read_text()
    wide = re.search(r"begin : g_dma_write_layout\s*(.*?)\s*end else begin : g_general_write_layout", text, re.S)[1]
    compact = re.search(r"begin : g_dma_compact_layout\s*(.*?)\s*end else begin : g_general_compact_layout", text, re.S)[1]
    proof = out / "layout.sv"
    proof.write_text("""module cache_layout_proof (
    input logic [127:0] input_words,
    input logic [63:0] input_bytes,
    input logic [3:0] wr_col_base,
    output logic equivalent
);
    logic [255:0] write_source_data, write_shifted_data;
    logic [127:0] compact_source_bytes, compact_shifted_bytes;
    assign write_source_data = {128'd0, input_words};
    assign compact_source_bytes = {64'd0, input_bytes};
""" + wide + "\n" + compact + """
    assign equivalent =
        write_shifted_data == (write_source_data << (int'(wr_col_base) * 16)) &&
        compact_shifted_bytes == (compact_source_bytes << (int'(wr_col_base) * 8));
endmodule
""")
    script, log = out / "run.ys", out / "formal.log"
    script.write_text("read_slang --top cache_layout_proof " + shlex.quote(str(proof)) + "\n" +
                      "prep -top cache_layout_proof -flatten\ncheck -assert\n" +
                      "sat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
    with log.open("w") as stream:
        subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"), "--worker", str(script)],
                       stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=120)
    if "SAT proof finished - no model found: SUCCESS!" not in log.read_text():
        raise RuntimeError("Cache layout proof did not complete")
    summary = {"passed": True, "input_bits": 196, "input_constraints": [],
               "column_positions": 16, "input_lanes": 8,
               "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
               "proof_sha256": hashlib.sha256(proof.read_bytes()).hexdigest(),
               "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest()}
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print("CACHE_LAYOUT_FORMAL_PASS input_bits=196 column_positions=16 input_lanes=8", flush=True)


if __name__ == "__main__":
    main()
