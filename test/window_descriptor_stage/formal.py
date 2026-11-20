#!/usr/bin/env python3
"""证明描述符准备阶段保持队列容量、事务顺序和所有有效响应。"""
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
SOURCE = Path("rtl/npu/dma/conv_window_queue.sv")

PROOF = r"""
module window_stage_proof #(
  parameter int DEPTH=4, TAG_W=2, COL_W=4, MAX_COLS=16,
  PTR_W=(DEPTH<=1 ? 1 : $clog2(DEPTH)), COUNT_W=$clog2(DEPTH+1)
)(
  input logic clk,rst_n,configure,enable,req_valid,rsp_ready,frontend_ready,
  input logic [31:0] req_p0,req_q0,req_cols,
  input logic [TAG_W-1:0] req_tag,
  input logic frontend_rsp_valid,frontend_rsp_last,frontend_error,
  input logic [COL_W-1:0] frontend_rsp_col,
  input logic signed [15:0] frontend_rsp_data[4],
  input logic [3:0] frontend_rsp_mask,
  output logic equivalent
);
  logic req_ready,rsp_valid,rsp_last,rsp_error,busy;
  logic [TAG_W-1:0] rsp_tag;
  logic [COL_W-1:0] rsp_col;
  logic signed [15:0] rsp_data[4];
  logic [3:0] rsp_mask;
  logic frontend_valid,frontend_active,frontend_rsp_ready;
  logic [31:0] frontend_p0,frontend_q0,frontend_cols;
  logic frontend_cols_valid;
  logic ref_req_ready,ref_rsp_valid,ref_rsp_last,ref_rsp_error,ref_busy;
  logic [TAG_W-1:0] ref_rsp_tag;
  logic [COL_W-1:0] ref_rsp_col;
  logic signed [15:0] ref_rsp_data[4];
  logic [3:0] ref_rsp_mask;
  logic ref_frontend_valid,ref_frontend_active,ref_frontend_rsp_ready;
  logic [31:0] ref_frontend_p0,ref_frontend_q0,ref_frontend_cols;
  logic ref_frontend_ready;
  logic initialized=1'b0;
  logic [DEPTH-1:0] written;
  logic control_equal,response_equal,descriptor_equal,storage_equal,state_valid;
  // 参考队列在准备完成时接收相同启动事件，比较顺序与有效数据。
  assign ref_frontend_ready=frontend_ready && current.descriptor_prepared;
  conv_window_queue #(.DEPTH(DEPTH),.TAG_W(TAG_W),.COL_W(COL_W),.p_max_cols(MAX_COLS)) current (.*);
  reference_window_queue #(.DEPTH(DEPTH),.TAG_W(TAG_W),.COL_W(COL_W)) reference (
    .clk,.rst_n,.configure,.enable,.req_valid,.req_p0,.req_q0,.req_cols,.req_tag,
    .rsp_ready,.frontend_rsp_valid,.frontend_rsp_last,.frontend_error,
    .frontend_rsp_col,.frontend_rsp_data,.frontend_rsp_mask,
    .req_ready(ref_req_ready),.rsp_valid(ref_rsp_valid),.rsp_tag(ref_rsp_tag),
    .rsp_col(ref_rsp_col),.rsp_data(ref_rsp_data),.rsp_mask(ref_rsp_mask),
    .rsp_last(ref_rsp_last),.rsp_error(ref_rsp_error),.busy(ref_busy),
    .frontend_ready(ref_frontend_ready),.frontend_valid(ref_frontend_valid),
    .frontend_active(ref_frontend_active),.frontend_rsp_ready(ref_frontend_rsp_ready),
    .frontend_p0(ref_frontend_p0),.frontend_q0(ref_frontend_q0),.frontend_cols(ref_frontend_cols)
  );
  always_ff @(posedge clk) begin
    if (!rst_n) begin initialized<=1'b1;written<='0;end
    else if (configure) written<='0;
    else if (req_valid && req_ready) written[current.tail]<=1'b1;
  end
  always_comb begin
    control_equal={req_ready,rsp_valid,rsp_error,busy,frontend_active,frontend_rsp_ready,
                   current.head,current.tail,current.count,current.active,current.failed} ==
                  {ref_req_ready,ref_rsp_valid,ref_rsp_error,ref_busy,ref_frontend_active,
                   ref_frontend_rsp_ready,reference.head,reference.tail,reference.count,
                   reference.active,reference.failed};
    control_equal &= frontend_valid==(ref_frontend_valid && current.descriptor_prepared);
    response_equal=!rsp_valid || {rsp_tag,rsp_col,rsp_mask,rsp_last,rsp_error,rsp_data[0],
                     rsp_data[1],rsp_data[2],rsp_data[3]} ==
                    {ref_rsp_tag,ref_rsp_col,ref_rsp_mask,ref_rsp_last,ref_rsp_error,
                     ref_rsp_data[0],ref_rsp_data[1],ref_rsp_data[2],ref_rsp_data[3]};
    descriptor_equal=!frontend_valid || {frontend_p0,frontend_q0,frontend_cols} ==
                                         {ref_frontend_p0,ref_frontend_q0,ref_frontend_cols};
    descriptor_equal &= !frontend_valid || frontend_cols_valid==(ref_frontend_cols>0 && ref_frontend_cols<=32'(MAX_COLS));
    storage_equal=1'b1;
    state_valid=current.count<=COUNT_W'(DEPTH) && int'(current.head)<DEPTH &&
                int'(current.tail)<DEPTH &&
                int'(current.tail)==(int'(current.head)+int'(current.count))%DEPTH;
    for (int slot=0;slot<DEPTH;slot++) begin
      if (written[slot])
        storage_equal &= {current.p0[slot],current.q0[slot],current.cols[slot],current.tags[slot]} ==
                         {reference.p0[slot],reference.q0[slot],reference.cols[slot],reference.tags[slot]};
      if (written[slot])
        storage_equal &= current.cols_valid[slot]==(current.cols[slot]>0 && current.cols[slot]<=32'(MAX_COLS));
      if (slot<int'(current.count)) state_valid &= written[(int'(current.head)+slot)%DEPTH];
    end
    if (current.descriptor_prepared && !current.failed) begin
      state_valid &= current.descriptor_available;
      state_valid &= {frontend_p0,frontend_q0,frontend_cols} ==
                     {current.p0[current.present],current.q0[current.present],current.cols[current.present]};
      state_valid &= frontend_cols_valid==current.cols_valid[current.present];
    end
    equivalent=!initialized || (control_equal && response_equal && descriptor_equal && storage_equal && state_valid);
  end
endmodule
"""


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", default="16913ce0")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--depths", nargs="+", type=int, default=[2, 3, 4, 7, 8])
    parser.add_argument("--max-cols", type=int, default=16)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference = out / "reference.sv"
    original = read_rtl_source(f"{args.reference}:{SOURCE}", cwd=ROOT)
    reference.write_text(original.decode().replace("module conv_window_queue", "module reference_window_queue", 1))
    current = out / "current.sv"
    current.write_bytes((ROOT / SOURCE).read_bytes())
    proof = out / "proof.sv"
    proof.write_text(PROOF)
    report = dict(reference_ref=args.reference, source_sha256=digest(current),
                  reference_sha256=hashlib.sha256(original).hexdigest(), proof_sha256=digest(proof),
                  initial_reset=True, inputs_constrained_after_reset=False,
                  reference_ready="frontend_ready && current.descriptor_prepared", max_cols=args.max_cols, cases=[])
    for depth in args.depths:
        folder = out / f"depth{depth}"
        folder.mkdir(exist_ok=True)
        script, log_path = folder / "run.ys", folder / "formal.log"
        script.write_text(f"read_slang --top window_stage_proof -GDEPTH={depth} -GMAX_COLS={args.max_cols} -D SYNTHESIS " +
            " ".join(shlex.quote(str(p)) for p in (reference, current, proof)) + "\n" +
            "prep -top window_stage_proof -flatten\nasync2sync\nmemory_map\nopt_clean\n" +
            "sat -verify -seq 2 -tempinduct -set-at 1 rst_n 0 -prove equivalent 1 " +
            "-show-inputs -show-outputs -maxsteps 12\n")
        with log_path.open("w") as log:
            subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                            "--worker", str(script)], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        text = log_path.read_text()
        if "Induction step proven: SUCCESS!" not in text:
            raise RuntimeError("Queue induction incomplete")
        length = int(re.findall(r"\[induction step (\d+)\]", text)[-1])
        item = dict(depth=depth, max_cols=args.max_cols, passed=True, induction_steps=length, log_sha256=digest(log_path))
        report["cases"].append(item)
        print(json.dumps(item), flush=True)
    if digest(ROOT / SOURCE) != report["source_sha256"]:
        raise RuntimeError("Queue source changed during verification")
    report["passed"] = True
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
