#!/usr/bin/env python3
"""保存实际修改前后 RTL，生成独立运算单元与完整向量综合配置。"""
import argparse
import json
from pathlib import Path
import re
import sys

from run_datapath import ROOT, SOURCE, extract, offset_unit, add_unit, accumulator_unit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference", default="67a35b26")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    names = ("conv_im2col_pkg.sv", "vector_engine_pkg.sv", "vector_config_check.sv",
             "vector_writeback.sv", "vector_round_shift.sv", "vector_scalar_multiplier.sv",
             "vector_pe.sv", "vector_softmax.sv", "vector_quant_params.sv", "vector_engine.sv")
    cases = {}
    for label in ("reference", "current"):
        folder = out / label
        folder.mkdir(exist_ok=True)
        for name in names:
            path = Path("rtl/npu/conv") / name
            text = ((ROOT / path).read_text() if label == "current" else
                    read_rtl_source(f"{args.reference}:{path}", cwd=ROOT, text=True))
            (folder / name).write_text(text)
        source = (folder / SOURCE.name).read_text()
        parts = extract(source)
        packages = [str(folder / name) for name in names[:2]]
        cases[f"vector_{label}"] = {
            "top": "vector_engine", "options": ["-D", "SYNTHESIS=1", "-GTILE=16", "-GBUS_WIDTH=64", "-GPE_COUNT=8"],
            "sources": [str(folder / name) for name in names], "configuration": "TILE16 BUS64 PE8 完整向量引擎"}
        for kind, unit, width, value in (
            ("offset", offset_unit("clamp_comb", parts), 34, "q_rounded"),
            ("add", add_unit("clamp_comb", parts[3]), 32, "add_rounded")):
            wrapper = f"""module clamp_unit(input logic clk,input logic signed[63:0] i_value,
input vector_engine_pkg::vector_engine_cfg_t i_cfg,output logic[{width-1}:0] o_value);
logic signed[63:0] {value};vector_engine_pkg::vector_engine_cfg_t c;logic [{width-1}:0] comb;
always_ff @(posedge clk) begin {value}<=i_value;c<=i_cfg;o_value<=comb;end
clamp_comb u_comb(.*, .observed(comb));
endmodule
"""
            path = folder / (kind + ".sv")
            path.write_text(unit + wrapper)
            cases[f"{kind}_{label}"] = {"top": "clamp_unit", "options": ["-D", "SYNTHESIS=1"],
                "sources": packages + [str(path)], "configuration": "完整输入端口和寄存输出的限幅运算"}
        enums = "\n".join(re.search(r"  typedef enum logic \[" + width + r":0\].*?} " + name + ";", source, re.S)[0]
                           for width, name in (("5", "state_t"), ("2", "load_t")))
        path = folder / "accumulator.sv"
        path.write_text(accumulator_unit("accumulator_store", parts[4], enums))
        cases[f"accumulator_{label}"] = {"top": "accumulator_store", "options": ["-D", "SYNTHESIS=1"],
            "sources": packages + [str(path)], "configuration": "TILE16 PE8 BUS64 累加器与右操作数存储"}
    (out / "cases.json").write_text(json.dumps(cases, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
