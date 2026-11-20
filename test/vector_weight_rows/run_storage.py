#!/usr/bin/env python3
"""比较完整权重存储的字节写入状态和同步读取周期。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    engine = ROOT / "rtl/npu/conv/vector_engine.sv"
    source = engine.read_text()
    modules = out / "storage.sv"
    modules.write_text("\n\n".join(re.search(r"^module " + name + r"\b.*?^endmodule", source, re.M | re.S)[0]
                                    for name in ("vector_weight_bank", "vector_weight_store")) + "\n")
    proof = out / "proof.sv"
    proof.write_text("""module weight_storage_proof #(
parameter int CHANNELS=16,DEPTH=49
)(input logic clk,i_wr_en,input logic [31:0] i_wr_tap,i_rd_tap,
input logic [CHANNELS-1:0] i_wr_mask,input logic [8*CHANNELS-1:0] i_wr_data,
output logic state_equal,output_equal);
logic [8*CHANNELS-1:0] reference_read,current_read,reference_async;
logic [8*CHANNELS*DEPTH-1:0] reference_state,current_state;
for (genvar channel=0;channel<CHANNELS;channel++) begin : g_reference
  vector_weight_bank #(.DEPTH(DEPTH)) u_bank (
    .clk(clk),.write_enable(i_wr_en && i_wr_mask[channel]),.write_address(i_wr_tap),
    .write_data(i_wr_data[8*channel+:8]),.read_address(i_rd_tap),
    .read_data(reference_async[8*channel+:8])
  );
  for (genvar row=0;row<DEPTH;row++) begin : g_row
    assign reference_state[8*(row*CHANNELS+channel)+:8] = u_bank.data[row];
  end
end
always_ff @(posedge clk) reference_read <= reference_async;
vector_weight_store #(.p_channels(CHANNELS),.p_depth(DEPTH)) u_current (
  .clk(clk),.i_wr_en(i_wr_en),.i_wr_tap(i_wr_tap),.i_rd_tap(i_rd_tap),
  .i_wr_mask(i_wr_mask),.i_wr_data(i_wr_data),.o_rd_data(current_read)
);
for (genvar row=0;row<DEPTH;row++) begin : g_current_row
  assign current_state[8*row*CHANNELS+:8*CHANNELS] = u_current.u_storage.mem[row];
end
assign state_equal = reference_state == current_state;
assign output_equal = reference_read == current_read;
endmodule
""")
    regfile = ROOT / "rtl/common/regfile.v"
    report = {"source_sha256": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                                 for path in (engine, regfile)}, "inputs_constrained": False,
              "initial_relation": "两份完整存储内容相同，内容值任意。", "checks": []}
    for channels, depth in ((1, 1), (3, 7), (16, 49)):
        folder = out / f"channels{channels}_depth{depth}"
        folder.mkdir(exist_ok=True)
        script = folder / "run.ys"
        sources = " ".join(shlex.quote(str(path)) for path in (modules, regfile, proof))
        script.write_text(f"""read_slang --top weight_storage_proof -GCHANNELS={channels} -GDEPTH={depth} {sources}
prep -top weight_storage_proof -flatten
memory_map
opt -full
sat -seq 2 -set-at 1 state_equal 1 -prove-skip 1 -prove state_equal 1 -prove output_equal 1 -verify
""")
        log = folder / "formal.log"
        with log.open("w") as stream:
            subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"), "--worker", str(script)],
                           cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
        if "SUCCESS!" not in log.read_text():
            raise RuntimeError("权重存储状态比较未通过")
        item = {"channels": channels, "depth": depth, "compared_memory_bits": 8*channels*depth,
                "passed": True, "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest()}
        report["checks"].append(item)
        print(json.dumps(item), flush=True)
    report["passed"] = True
    (out / "summary.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
