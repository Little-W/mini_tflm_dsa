#!/usr/bin/env python3
"""从实际 RTL 提取输出选择逻辑，并证明全部输入编码下等价。"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("rtl/npu/writeback/vec_s8_to_fifo.sv")
PARAMETERS = """parameter int VLEN=16, BUS_WIDTH=64,
    localparam int BYTE_PER_BEAT=BUS_WIDTH/8,
    localparam int BYTE_SHIFT=$clog2(BYTE_PER_BEAT),
    localparam int PTR_WIDTH=(VLEN<=1)?1:$clog2(VLEN),
    localparam int COUNT_WIDTH=$clog2(VLEN+1),
    localparam int ROW_BEATS=(VLEN+BYTE_PER_BEAT-1)/BYTE_PER_BEAT,
    localparam int BEAT_WIDTH=(ROW_BEATS<=1)?1:$clog2(ROW_BEATS)"""
INPUTS = """input logic clk,
    input logic [VLEN*8-1:0] ram_rd_data[BYTE_PER_BEAT],
    input logic coalesce_enable, co_active, transpose_mode_eff,
    input logic stream_active, transpose_mode_tmp,
    input logic [8:0] co_row,
    input logic [BEAT_WIDTH-1:0] co_beat, beat_idx,
    input logic [PTR_WIDTH-1:0] read_ptr,
    input logic [COUNT_WIDTH-1:0] output_col_count, active_read_count"""
PORT_NAMES = ("clk", "ram_rd_data", "coalesce_enable", "co_active", "transpose_mode_eff",
              "stream_active", "transpose_mode_tmp", "co_row", "co_beat", "beat_idx",
              "read_ptr", "output_col_count", "active_read_count")


def selector(source, name):
    start = source.index("  integer valid_cols_i;")
    end = source.index("\nendmodule", start)
    return f"module {name} #({PARAMETERS}) ({INPUTS},\n" + \
        "output logic [BUS_WIDTH-1:0] output_data,\n" + \
        "output logic [BYTE_PER_BEAT-1:0] output_mask);\n" + source[start:end] + "\nendmodule\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "build/fifo_selection_formal")
    parser.add_argument("--reference", default="aa2ef9a3")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    original = read_rtl_source(f"{args.reference}:{SOURCE}", cwd=ROOT, text=True)
    current = (ROOT / SOURCE).read_text()
    source_hash = hashlib.sha256(current.encode()).hexdigest()
    generated = out / "selection.sv"
    body = selector(original, "selection_reference") + selector(current, "selection_current")
    body += f"module fifo_output_selection_formal #({PARAMETERS}) ({INPUTS}, output logic equivalent);\n"
    body += "logic [BUS_WIDTH-1:0] reference_data, current_data;\n"
    body += "logic [BYTE_PER_BEAT-1:0] reference_mask, current_mask;\n"
    for name in ("reference", "current"):
        body += f"selection_{name} #(.VLEN(VLEN), .BUS_WIDTH(BUS_WIDTH)) u_{name} (\n"
        body += ",\n".join(f".{port}({port})" for port in PORT_NAMES)
        body += f",\n.output_data({name}_data), .output_mask({name}_mask));\n"
    body += "assign equivalent = (reference_data === current_data) && (reference_mask === current_mask);\nendmodule\n"
    generated.write_text(body)
    profiles = []
    for size, bus in ((4, 32), (8, 32), (8, 64), (16, 32), (16, 64), (16, 128), (32, 64), (32, 256)):
        script = out / f"n{size}_b{bus}.ys"
        script.write_text(f"read_slang --top fifo_output_selection_formal -GVLEN={size} -GBUS_WIDTH={bus} " +
            shlex.quote(str(generated)) + "\nprep -top fifo_output_selection_formal -flatten\n" +
            "sat -verify -enable_undef -set-def-inputs -prove equivalent 1 -show-inputs\n")
        with script.with_suffix(".log").open("w") as log:
            subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                            "--worker", str(script)], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        profiles.append(dict(vlen=size, bus_width=bus, passed=True))
        print(json.dumps(profiles[-1]), flush=True)
    if source_hash != hashlib.sha256((ROOT / SOURCE).read_bytes()).hexdigest():
        raise RuntimeError("Source changed during verification")
    (out / "summary.json").write_text(json.dumps(dict(passed=True, profiles=profiles,
        source_sha256=source_hash, reference=args.reference,
        reference_sha256=hashlib.sha256(original.encode()).hexdigest(),
        extracted_logic_sha256=hashlib.sha256(body.encode()).hexdigest()), indent=2) + "\n")


if __name__ == "__main__":
    main()
