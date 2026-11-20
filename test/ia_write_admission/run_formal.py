#!/usr/bin/env python3
"""证明 IA 描述符列状态与 DMA 写入数据、有效位的全部输入行为。"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = "rtl/npu/loaders/ia_loader.sv"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def extract(text):
    start = text.index("    logic [REG_WIDTH-1:0] active_valid_cols;")
    end = text.index("    // Every read, including im2col", start)
    state = text[start:end]
    start = text.index("    generate\n        for (genvar dma_i", end)
    end = text.index("    endgenerate\n", start) + len("    endgenerate\n")
    return state, text[start:end]


def unit(name, state, writes):
    return "module " + name + """ #(
  parameter int unsigned SIZE=16, BUS_WIDTH=64, REG_WIDTH=32, DATA_WIDTH=16,
  localparam int BYTE_PER_BEAT=BUS_WIDTH/8, LOG2_SIZE=$clog2(SIZE)
)(
  input logic clk, rst_n, ext_dma_start,
  input logic [REG_WIDTH-1:0] descriptor_cols,
  input logic [LOG2_SIZE-1:0] ext_dma_wr_col_base,
  input logic signed [DATA_WIDTH-1:0] ext_dma_wr_data [BYTE_PER_BEAT],
  input logic ext_dma_wr_valid [BYTE_PER_BEAT],
  output logic [BYTE_PER_BEAT*(DATA_WIDTH+1)-1:0] observed
);
  typedef struct packed {logic [REG_WIDTH-1:0] cols;} descriptor_t;
  descriptor_t dma_descriptor;
  logic signed [DATA_WIDTH-1:0] tl_wr_data [BYTE_PER_BEAT];
  logic tl_wr_valid [BYTE_PER_BEAT];
  assign dma_descriptor.cols=descriptor_cols;
""" + state + writes + """
  for (genvar lane=0;lane<BYTE_PER_BEAT;lane++) begin:g_observe
    assign observed[lane*(DATA_WIDTH+1)+:(DATA_WIDTH+1)]={tl_wr_valid[lane],tl_wr_data[lane]};
  end
endmodule
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", default="362870b1")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = (ROOT / SOURCE).read_text()
    reference = subprocess.check_output(["git", "show", f"{args.reference}:{SOURCE}"], cwd=ROOT, text=True)
    current_state, current_writes = extract(current)
    reference_state, reference_writes = extract(reference)
    if current.replace(current_state, reference_state, 1).replace(current_writes, reference_writes, 1) != reference:
        raise RuntimeError("Changes outside DMA column state and writes require verification")
    proof = out / "columns.sv"
    proof.write_text(unit("current_columns", current_state, current_writes) +
        unit("reference_columns", reference_state, reference_writes) + """
module column_proof #(
  parameter int unsigned SIZE=16, BUS_WIDTH=64, REG_WIDTH=32, DATA_WIDTH=16,
  localparam int BYTE_PER_BEAT=BUS_WIDTH/8, LOG2_SIZE=$clog2(SIZE)
)(
  input logic clk, rst_n, ext_dma_start,
  input logic [REG_WIDTH-1:0] descriptor_cols,
  input logic [LOG2_SIZE-1:0] ext_dma_wr_col_base,
  input logic signed [DATA_WIDTH-1:0] ext_dma_wr_data [BYTE_PER_BEAT],
  input logic ext_dma_wr_valid [BYTE_PER_BEAT],
  output logic equivalent
);
  logic [BYTE_PER_BEAT*(DATA_WIDTH+1)-1:0] current_observed, reference_observed;
  current_columns #(.SIZE(SIZE),.BUS_WIDTH(BUS_WIDTH),.REG_WIDTH(REG_WIDTH),.DATA_WIDTH(DATA_WIDTH))
    u_current(.*,.observed(current_observed));
  reference_columns #(.SIZE(SIZE),.BUS_WIDTH(BUS_WIDTH),.REG_WIDTH(REG_WIDTH),.DATA_WIDTH(DATA_WIDTH))
    u_reference(.*,.observed(reference_observed));
  assign equivalent=current_observed==reference_observed;
endmodule
""")
    cases = []
    for size, bus, reg, data in ((4,32,32,8), (8,64,16,16), (16,32,32,16),
            (16,64,32,16), (16,128,32,16), (16,64,4,16), (16,8,4,16),
            (5,64,8,16), (2,128,16,16), (32,64,32,16), (64,128,32,32)):
        label = f"size{size}_bus{bus}_reg{reg}_data{data}"
        script, log_path = out / (label + ".ys"), out / (label + ".log")
        script.write_text(f"read_slang --top column_proof -GSIZE={size} -GBUS_WIDTH={bus} " +
            f"-GREG_WIDTH={reg} -GDATA_WIDTH={data} " + shlex.quote(str(proof)) +
            "\nprep -top column_proof -flatten\nasync2sync\nopt_clean\n" +
            "sat -verify -seq 2 -tempinduct -set-at 1 rst_n 0 -prove equivalent 1 -maxsteps 8\n")
        with log_path.open("w") as log:
            subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"), "--worker", str(script)],
                           cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        if "Induction step proven: SUCCESS!" not in log_path.read_text():
            raise RuntimeError("Column-state induction incomplete")
        result = dict(size=size, bus_width=bus, register_width=reg, data_width=data, passed=True,
            observed_bits=(bus//8)*(data+1), log_sha256=digest(log_path.read_bytes()),
            script_sha256=digest(script.read_bytes()))
        cases.append(result)
        print(json.dumps(result), flush=True)
    report = dict(passed=True, reference_ref=args.reference,
        reference_commit=subprocess.check_output(["git", "rev-parse", args.reference], cwd=ROOT, text=True).strip(),
        source_sha256=digest(current.encode()), reference_sha256=digest(reference.encode()),
        unchanged_outside_column_state_and_writes=True, inputs_constrained=False,
        reset_initialization=True, proof_sha256=digest(proof.read_bytes()), cases=cases)
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
