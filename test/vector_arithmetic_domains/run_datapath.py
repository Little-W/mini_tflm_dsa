#!/usr/bin/env python3
"""读取实际 RTL，比较偏移限幅、Add 限幅和累加器全部状态。"""
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


def normalized(text):
    return re.sub(r"\s+", "", re.sub(r"//[^\n]*", "", text))


def extract(text):
    offset_decl = re.search(r"  logic \[(?:8|32):0\] q_offset_low;.*?logic signed \[31:0\] q_clamped_data;", text, re.S)[0]
    offset_math = re.search(r"  assign q_offset_low\s*=.*?(?=  assign ready)", text, re.S)[0]
    offset_result = re.search(r"  assign q_clamped_data\s*=.*?;", text, re.S)[0]
    add = re.search(r"  wire signed \[9:0\] add_adjusted=.*?(?=\n\n)", text, re.S)[0]
    first = text.find("  logic signed [31:0] acc_common_write_data")
    if first < 0:
        first = text.index("  for (genvar entry=0;entry<TILE;entry++) begin : g_accumulator_write")
    last = text.index("  wire signed [63:0] rounding_input", first)
    return offset_decl, offset_math, offset_result, add, text[first:last]


def offset_unit(name, parts):
    return (f"module {name}(input logic signed[63:0] q_rounded, "
            "input vector_engine_pkg::vector_engine_cfg_t c, output logic[33:0] observed);\n" +
            "\n".join(parts[:3]) + "\nassign observed={q_above_max,q_below_min,q_clamped_data};\nendmodule\n")


def add_unit(name, block):
    return (f"module {name}(input logic signed[63:0] add_rounded, "
            "input vector_engine_pkg::vector_engine_cfg_t c, output logic[31:0] observed);\n" +
            block + "\nassign observed=add_clamped;\nendmodule\n")


def accumulator_unit(name, body, enums, proof=False):
    outputs = ("output logic state_equal,valid_mode" if proof else
               "output logic signed[31:0] acc_buf[TILE],output logic signed[15:0] rhs_buf[TILE]")
    header = f"""module {name} #(
parameter int BUS_WIDTH=64,TILE=16,PE_COUNT=8,DMA_SIZE=4*TILE,
BUS_BYTES=BUS_WIDTH/8,ACTIVE_COUNT_W=$clog2(TILE+1),
TILE_INDEX_W=$clog2(TILE+PE_COUNT+1),INPUT_INDEX_W=$clog2(DMA_SIZE)
)(input logic clk,rst_n,input logic [5:0] state,input logic [2:0] load_kind,
input vector_engine_pkg::vector_engine_cfg_t c,
input logic [ACTIVE_COUNT_W-1:0] active,
input logic [TILE_INDEX_W-1:0] compute_index,
input logic signed[31:0] pe_result[PE_COUNT],bias_buf[TILE],
input logic soft_exp_we,input logic [$clog2(TILE)-1:0] soft_exp_index,
input logic signed[31:0] soft_exp_data,
input logic rd_valid[BUS_BYTES],input logic signed[15:0] rd_data[BUS_BYTES],
input logic [INPUT_INDEX_W-1:0] rd_col_base,{outputs});
import vector_engine_pkg::*;
logic depthwise,softmax_s8;
assign depthwise=c.op==DW_S8;
assign softmax_s8=c.op==SOFTMAX_S8;
"""
    return header + enums + "\n" + body + "\nendmodule\n"


def execute(folder, source, commands, options=""):
    folder.mkdir(parents=True, exist_ok=True)
    packages = [ROOT / "rtl/npu/conv/conv_im2col_pkg.sv", ROOT / "rtl/npu/conv/vector_engine_pkg.sv"]
    sources = " ".join(shlex.quote(str(path)) for path in packages + [source])
    script = folder / "proof.ys"
    script.write_text(f"read_slang --top proof {options} {sources}\nprep -top proof -flatten\n{commands}\n")
    log = folder / "formal.log"
    with log.open("w") as stream:
        subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                        "--worker", str(script)], cwd=ROOT, stdout=stream,
                       stderr=subprocess.STDOUT, check=True)
    if "SUCCESS!" not in log.read_text():
        raise RuntimeError("数据比较未完成")
    return {"passed": True, "proof_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference", default="67a35b26")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = (ROOT / SOURCE).read_text()
    reference = read_rtl_source(f"{args.reference}:{SOURCE}", cwd=ROOT, text=True)
    current_parts, reference_parts = extract(current), extract(reference)
    restored = current
    for old, new in zip(reference_parts, current_parts):
        restored = restored.replace(new, old, 1)
    if normalized(restored) != normalized(reference):
        raise RuntimeError("存在尚未包含在本比较中的 RTL 修改")
    report = {"reference_commit": subprocess.check_output(["git", "rev-parse", args.reference],
               cwd=ROOT, text=True).strip(), "source_sha256": hashlib.sha256(current.encode()).hexdigest(),
              "actual_source_expressions": True, "other_logic_unchanged": True, "checks": []}
    source = out / "offset.sv"
    source.write_text(offset_unit("reference", reference_parts) + offset_unit("current", current_parts) + """
module proof(input logic signed[63:0] q_rounded,
input logic signed[7:0] offset,lower,upper,output logic equivalent);
vector_engine_pkg::vector_engine_cfg_t c;
logic [33:0] a,b;
always_comb begin c='0;c.output_offset=32'(offset);c.activation_min=32'(lower);c.activation_max=32'(upper);end
reference r(.*, .observed(a));current n(.*, .observed(b));assign equivalent=a==b;
endmodule
""")
    item = execute(out / "offset", source, "sat -prove equivalent 1 -verify")
    item.update(name="offset", unrestricted_data_bits=64, configuration="S8 offset and bounds", observed_bits=34)
    report["checks"].append(item)
    source = out / "add.sv"
    source.write_text(add_unit("reference", reference_parts[3]) + add_unit("current", current_parts[3]) + """
module proof(input logic signed[63:0] add_rounded,
input vector_engine_pkg::vector_engine_cfg_t c,output logic equivalent);
logic [31:0] a,b;
reference r(.*, .observed(a));current n(.*, .observed(b));assign equivalent=a==b;
endmodule
""")
    item = execute(out / "add", source, "sat -prove equivalent 1 -verify")
    item.update(name="add", inputs_constrained=False, observed_bits=32)
    report["checks"].append(item)
    enums = "\n".join(re.search(r"  typedef enum logic \[" + width + r":0\].*?} " + name + ";", current, re.S)[0]
                       for width, name in (("5", "state_t"), ("2", "load_t")))
    source = out / "accumulator.sv"
    body = """logic signed[31:0] r_acc[TILE],n_acc[TILE];
logic signed[15:0] r_rhs[TILE],n_rhs[TILE];logic [48*TILE-1:0] r_state,n_state;
reference #(.BUS_WIDTH(BUS_WIDTH),.TILE(TILE),.PE_COUNT(PE_COUNT)) r(.*, .acc_buf(r_acc),.rhs_buf(r_rhs));
current #(.BUS_WIDTH(BUS_WIDTH),.TILE(TILE),.PE_COUNT(PE_COUNT)) n(.*, .acc_buf(n_acc),.rhs_buf(n_rhs));
assign r_state={>>{r_acc,r_rhs}};assign n_state={>>{n_acc,n_rhs}};
assign state_equal=r_state==n_state;
assign valid_mode=!(softmax_s8 && soft_exp_we &&
    (state==EXECUTE_COMMIT || state==OUTPUT_INIT || state==VECTOR_INIT));
"""
    source.write_text(accumulator_unit("reference", reference_parts[4], enums) +
                      accumulator_unit("current", current_parts[4], enums) +
                      accumulator_unit("proof", body, enums, proof=True))
    for tile, pes, bus in ((16, 8, 64), (16, 8, 32), (8, 4, 32), (3, 3, 64), (1, 1, 32)):
        item = execute(out / f"accumulator_t{tile}_p{pes}_b{bus}", source,
                       "sat -seq 2 -set-at 1 state_equal 1 -set valid_mode 1 -prove-skip 1 -prove state_equal 1 -verify",
                       f"-GTILE={tile} -GPE_COUNT={pes} -GBUS_WIDTH={bus}")
        item.update(name="accumulator", tile=tile, pes=pes, bus_width=bus,
                    compared_state_bits=48*tile, initial_state="equal arbitrary contents",
                    control_relation="Softmax exponent writes are separate from compute and initialization")
        report["checks"].append(item)
    report["passed"] = True
    (out / "summary.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"passed": True, "checks": len(report["checks"])}), flush=True)


if __name__ == "__main__":
    main()
