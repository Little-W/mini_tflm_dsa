#!/usr/bin/env python3
"""证明实际坐标分段加法和图像范围判断的全部输入位模式。"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "rtl/npu/conv/conv_im2col_frontend.sv"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = SOURCE.read_text()
    start = current.index("  for (genvar axis = 0; axis < 7; axis++) begin : g_coordinate_bound")
    section = current[start:current.index("  // 数据字匹配", start)]
    model = out / "coordinate_bound.sv"
    model.write_text("""module coordinate_bound_proof (
input logic [6:0][34:0] i_a,i_b,
input logic [6:0][15:0] i_limit,
output logic equivalent
);
localparam integer COORD_W=35;
logic [COORD_W-1:0] bound_a[7],bound_b[7],bound_sum[7];
logic [15:0] bound_limit[7];
logic [6:0] bound_valid,axis_equal;
for(genvar axis_input=0;axis_input<7;axis_input++) begin:g_input
  wire [34:0] direct_sum=bound_a[axis_input]+bound_b[axis_input];
  wire direct_valid=!(|direct_sum[34:16]) && direct_sum[15:0]<bound_limit[axis_input];
  assign bound_a[axis_input]=i_a[axis_input];
  if(axis_input==1 || axis_input==3 || axis_input==4 || axis_input==6) begin:g_positive
    assign bound_b[axis_input]={19'd0,i_b[axis_input][15:0]};
  end else begin:g_signed
    assign bound_b[axis_input]=i_b[axis_input];
  end
  assign bound_limit[axis_input]=i_limit[axis_input];
  assign axis_equal[axis_input]=bound_sum[axis_input]==direct_sum && bound_valid[axis_input]==direct_valid;
end
""" + section + "\nassign equivalent=&axis_equal;\nendmodule\n")
    script = out / "prove.ys"
    script.write_text("read_slang --top coordinate_bound_proof " + shlex.quote(str(model)) + " " +
                     shlex.quote(str(ROOT / "rtl/common/add_equal.sv")) + "\n"
                     "prep -top coordinate_bound_proof -flatten\nsat -verify -prove equivalent 1\n")
    log = out / "formal.log"
    with log.open("w") as stream:
        subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"), "--worker", str(script)],
                       cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
    if "SAT proof finished - no model found: SUCCESS!" not in log.read_text():
        raise RuntimeError("Coordinate proof incomplete")
    report = dict(passed=True, compared_bits=252, coordinate_width=35, limit_width=16,
        positive_step_axes=[1, 3, 4, 6], signed_step_axes=[0, 2, 5],
        source_sha256=hashlib.sha256(current.encode()).hexdigest(),
        model_sha256=hashlib.sha256(model.read_bytes()).hexdigest(),
        log_sha256=hashlib.sha256(log.read_bytes()).hexdigest())
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
