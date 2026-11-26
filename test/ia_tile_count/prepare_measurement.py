#!/usr/bin/env python3
"""提取 IA 分块数算术并添加相同的输入、输出寄存边界。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from run import ROOT, SOURCE, extract

WRAPPER = """module tile_count_pipeline (
    input logic clk, rst_n, i_enable,
    input logic [31:0] i_global, i_n, i_saved_n,
    input logic [1:0] i_state,
    output logic [32:0] o_tiles
);
    logic [31:0] cfg_global_reduction, n, cfg_n;
    logic [1:0] state;
    wire [32:0] value;
    arithmetic u_count (.cfg_global_reduction,.n,.cfg_n,.state,.o_value(value));
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            cfg_global_reduction<='0; n<='0; cfg_n<='0; state<='0; o_tiles<='0;
        end else if (i_enable) begin
            cfg_global_reduction<=i_global; n<=i_n; cfg_n<=i_saved_n; state<=i_state;
            o_tiles<=value;
        end
    end
endmodule
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-ref", default="1470a963")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    original = subprocess.check_output(["git", "show", args.reference_ref + ":" + SOURCE],
                                       cwd=ROOT, text=True)
    current = (ROOT / SOURCE).read_text()
    cases, hashes = {}, {}
    for name, source in (("reference", original), ("current", current)):
        path = out / f"{name}.sv"
        path.write_text(extract(source, "arithmetic") + WRAPPER)
        hashes[name] = hashlib.sha256(source.encode()).hexdigest()
        cases[name] = dict(top="tile_count_pipeline", options=["-DSYNTHESIS=1"],
                           sources=[str(path)], parameters=dict(REG_WIDTH=32, SIZE=16),
                           configuration="Complete source selection and ceiling with registered input and output")
    (out / "cases.json").write_text(json.dumps(cases, indent=2) + "\n")
    (out / "source_sha256.json").write_text(json.dumps(hashes, indent=2) + "\n")


if __name__ == "__main__":
    main()
