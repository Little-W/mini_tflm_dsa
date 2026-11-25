#!/usr/bin/env python3
"""验证线性 DMA 通道加法及其映射后的完整算术功能。"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "rtl/npu/dma/axi_linear_block_dma.sv"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tokens(source, attributes=True):
    source = re.sub(r"/\*.*?\*/|//[^\n]*", "", source, flags=re.S)
    if not attributes:
        source = re.sub(r"\(\*.*?\*\)", "", source, flags=re.S)
    return re.sub(r"\s+", "", source)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-rtl", type=Path, required=True)
    parser.add_argument("--rtl", type=Path, default=SOURCE)
    parser.add_argument("--mapped-json", type=Path, required=True)
    parser.add_argument("--mapped-source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    paths = [args.reference_rtl, args.rtl, args.mapped_json, args.mapped_source]
    hashes = {str(path.resolve()): sha(path) for path in paths}
    current = args.rtl.read_text()
    if tokens(current, attributes=False) != tokens(args.reference_rtl.read_text(), attributes=False):
        raise RuntimeError("Executable RTL differs after removing comments and synthesis attributes")
    if tokens(current) != tokens(args.mapped_source.read_text()):
        raise RuntimeError("Mapped source differs from the verified RTL")
    module = json.loads(args.mapped_json.read_text())["modules"]["axi_linear_block_dma"]
    nets, cells = module["netnames"], module["cells"]
    drivers = {}
    for name, cell in cells.items():
        for port, bits in cell["connections"].items():
            if cell["port_directions"][port] == "output":
                for bit in bits:
                    if isinstance(bit, int):
                        if bit in drivers:
                            raise RuntimeError("Mapped net has multiple drivers")
                        drivers[bit] = name
    # 保存到 DSP 输入寄存器的零点副本与普通寄存器共用时钟、使能和复位。
    zero_bits = nets["rd_rsp_zp"]["bits"][:16]
    zero_cells = [cells[drivers[bit]] for bit in zero_bits]
    if any(cell["type"] != "FDRE" for cell in zero_cells):
        raise RuntimeError("Unexpected zero-point register structure")
    controls = {port: zero_cells[0]["connections"][port] for port in ("C", "CE", "R")}
    if any(cell["connections"][port] != bits for cell in zero_cells
           for port, bits in controls.items()):
        raise RuntimeError("Zero-point register controls differ")
    inputs = {
        "clk": controls["C"], "i_enable": controls["CE"], "i_reset": controls["R"],
        "i_zero_point": [cell["connections"]["D"][0] for cell in zero_cells],
        "i_data": nets["rd_rsp_data_r"]["bits"],
        "i_use_16bits": nets["rd_rsp_use_16bits"]["bits"],
    }
    if len(inputs["i_data"]) != 64:
        raise RuntimeError("This mapped arithmetic check uses the production 64-bit bus")
    outputs = [bit for lane in range(8)
               for bit in nets[f"g_unpack_lane[{lane}].adjusted_data"]["bits"]]
    if len(outputs) != 128:
        raise RuntimeError("This mapped arithmetic check uses sixteen-bit results")
    roots = {bit for bits in inputs.values() for bit in bits}
    selected = {}

    def visit(bit):
        if isinstance(bit, str) or bit in roots:
            return
        if bit not in drivers:
            raise RuntimeError(f"Arithmetic input lacks a driver: {bit}")
        name = drivers[bit]
        if name in selected:
            return
        cell = cells[name]
        selected[name] = copy.deepcopy(cell)
        for port, bits in cell["connections"].items():
            if cell["port_directions"][port] == "input":
                for source in bits:
                    visit(source)

    for bit in outputs:
        visit(bit)
    if any(cell["type"] not in ("FDRE", "DSP48E1", "INV")
           and not re.fullmatch(r"LUT[1-6]", cell["type"]) for cell in selected.values()):
        raise RuntimeError("Unexpected cell in the extracted arithmetic")
    dsp = [cell for cell in selected.values() if cell["type"] == "DSP48E1"]
    if len(dsp) != 4 or any(cell["parameters"]["USE_SIMD"] != "TWO24" for cell in dsp):
        raise RuntimeError("Expected four inferred paired-lane arithmetic units")
    ports = {name: dict(direction="input", bits=bits) for name, bits in inputs.items()}
    ports["o_data"] = dict(direction="output", bits=outputs)
    extracted = out / "mapped_arithmetic.json"
    extracted.write_text(json.dumps({"modules": {"current": {
        "attributes": {}, "ports": ports, "cells": selected, "netnames": {},
    }}}) + "\n")
    reference = out / "reference.sv"
    reference.write_text("""module reference (
    input logic clk, i_enable, i_reset, i_use_16bits,
    input logic [15:0] i_zero_point,
    input logic [63:0] i_data,
    output logic [127:0] o_data
);
    logic [15:0] zero_point;
    always_ff @(posedge clk) begin
        if (i_reset) zero_point <= '0;
        else if (i_enable) zero_point <= i_zero_point;
    end
    for (genvar lane=0; lane<8; lane++) begin : g_lane
        logic [15:0] data_value;
        if (lane<4) begin : g_both_formats
            assign data_value = i_use_16bits ? i_data[16*lane+:16] :
                {{8{i_data[8*lane+7]}}, i_data[8*lane+:8]};
        end else begin : g_byte_format
            assign data_value = {{8{i_data[8*lane+7]}}, i_data[8*lane+:8]};
        end
        assign o_data[16*lane+:16] = data_value + zero_point;
    end
endmodule
""")
    script = out / "mapped_equivalence.ys"
    script.write_text("\n".join([
        f"read_slang --top reference {reference}",
        "prep -top reference -flatten", "opt -full", "design -stash reference",
        "read_verilog +/xilinx/cells_sim.v", f"read_json {extracted}",
        "hierarchy -top current", "flatten -wb", "proc", "opt -full",
        "design -stash current",
        "design -copy-from reference -as reference reference",
        "design -copy-from current -as current current",
        "equiv_make reference current proof", "hierarchy -top proof",
        "equiv_simple -seq 3", "opt_clean", "equiv_induct -seq 4", "equiv_status -assert",
    ]) + "\n")
    log = out / "mapped_equivalence.log"
    with log.open("w") as stream:
        result = subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                                 "--worker", str(script)], cwd=ROOT,
                                stdout=stream, stderr=subprocess.STDOUT)
    content = log.read_text()
    if result.returncode or "Equivalence successfully proven" not in content:
        raise RuntimeError(content[-8000:])
    if hashes != {str(path.resolve()): sha(path) for path in paths}:
        raise RuntimeError("Source changed during verification")
    import pyosys
    library = Path(pyosys.__file__).parent / "share/xilinx/cells_sim.v"
    report = dict(passed=True, inputs_constrained=False,
                  executable_rtl_tokens_equal=True, four_state_rtl_behavior_unchanged=True,
                  mapped_source_tokens_equal=True, mapped_output_bits=128,
                  mapped_dsp_units=len(dsp), primitive_library_sha256=sha(library),
                  source_sha256=hashes, extracted_netlist_sha256=sha(extracted), log_sha256=sha(log))
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
