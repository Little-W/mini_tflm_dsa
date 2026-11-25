#!/usr/bin/env python3
"""固定参考及候选 PE，为八通道独立映射生成相同的公开输入。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("rtl/npu/conv/vector_pe.sv")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", default="f821b566")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    revision = subprocess.check_output(["git", "rev-parse", args.reference + "^{commit}"],
                                       cwd=ROOT, text=True).strip()
    reference = subprocess.check_output(["git", "show", f"{revision}:{SOURCE}"], cwd=ROOT)
    wrapper = '''`default_nettype none
module pe_array (
  input wire logic clk, i_en,
  input wire logic [2:0] i_op,
  input wire logic signed [15:0] i_a[8], i_b[8],
  input wire logic signed [31:0] i_acc[8],
  output logic signed [31:0] o_result[8]
);
  for (genvar lane=0; lane<8; lane++) begin : g_pe
    vector_pe #(.ENABLE_EXTENDED_MULTIPLY(1'b0)) u_pe (
      .clk(clk), .i_en(i_en), .i_op(i_op), .i_a(i_a[lane]), .i_b(i_b[lane]),
      .i_acc(i_acc[lane]), .o_result(o_result[lane])
    );
  end
endmodule
`default_nettype wire
'''
    cases, hashes = {}, {}
    for label, content in (("reference", reference), ("candidate", (ROOT / SOURCE).read_bytes())):
        folder = out / label
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "vector_pe.sv").write_bytes(content)
        (folder / "pe_array.sv").write_text(wrapper)
        hashes[label] = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                         for path in (folder / "vector_pe.sv", folder / "pe_array.sv")}
        cases[label] = dict(top="pe_array", sources=["vector_pe.sv", "pe_array.sv"],
                            parameters={}, options=["-DSYNTHESIS=1", "-DXILINX_FPGA=1"],
                            configuration="Eight parallel signed vector PEs, all ports active")
    (out / "cases.json").write_text(json.dumps(cases, indent=2) + "\n")
    (out / "source_sha256.json").write_text(json.dumps(
        dict(reference_commit=revision, sources=hashes), indent=2) + "\n")


if __name__ == "__main__":
    main()
