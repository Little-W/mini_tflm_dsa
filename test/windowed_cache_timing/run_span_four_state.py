#!/usr/bin/env python3
"""检查页内突发编码在所有地址及未知输入下的完整结果。"""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from run_four_state import run_test

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "build/windowed_cache_timing"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, default=BASE/"span_four_state")
    args = parser.parse_args()
    rtl = args.source_root.resolve() / "rtl/npu/conv/conv_axi_span_reader.sv"
    source = rtl.read_text()
    first = source.index("  localparam int BUS_BYTES=")
    last = source.index("  `ifdef NPU_SIM_ASSERT", first)
    parameters = source[first:last]
    first = source.index("  for (genvar candidate = 0;")
    last = source.index("  assign finishing_span", first)
    body = source[first:last]
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    records = []
    for bus, request, dma in ((32, 16, 1024), (64, 128, 2048), (128, 256, 4096),
                              (1024, 65535, 32768), (32, 1, 4), (64, 3, 8), (64, 65535, 64)):
        test = f"""module tb;
  localparam integer BUS_WIDTH={bus}, MAX_REQUEST_BYTES={request}, DMA_MAX_BYTES={dma};
{parameters}
  localparam integer INPUT_WIDTH=24+2*COUNT_W;
  logic [1:0][11:0] candidate_addr;
  logic [1:0][COUNT_W-1:0] candidate_bytes;
  logic [1:0][BEAT_W-1:0] candidate_beats;
  logic [1:0][7:0] candidate_arlen;
  logic [INPUT_WIDTH-1:0] stimulus,saved;
  logic [31:0] random_state=32'h76af_04e1;
  integer checks=0;
  assign {{candidate_addr,candidate_bytes}}=stimulus;
{body}
  task automatic check;
    begin
      #1;
      for(integer index=0;index<2;index=index+1) begin
        if(candidate_arlen[index] !== 8'(candidate_beats[index]-1'b1))
          $fatal(1,"span stimulus=%b port=%0d actual=%b expected=%b",stimulus,index,
              candidate_arlen[index],8'(candidate_beats[index]-1'b1));
        checks=checks+1;
      end
    end
  endtask
  task automatic randomize;
    begin
      for(integer bit_index=0;bit_index<INPUT_WIDTH;bit_index=bit_index+1) begin
        random_state={{random_state[30:0],random_state[31]^random_state[21]^random_state[1]^random_state[0]}};
        stimulus[bit_index]=random_state[0];
      end
    end
  endtask
  initial begin
    for(integer address=0;address<4096;address=address+1)
      for(integer length_index=0;length_index<16;length_index=length_index+1) begin
        stimulus={{12'(address),12'(~address),COUNT_W'(length_index*BUS_BYTES),COUNT_W'((1<<length_index)-1)}};
        check();
      end
    for(integer trial=0;trial<512;trial=trial+1) begin
      randomize();check();saved=stimulus;
      for(integer bit_index=0;bit_index<INPUT_WIDTH;bit_index=bit_index+1) begin
        stimulus=saved;stimulus[bit_index]=1'bx;check();
        stimulus=saved;stimulus[bit_index]=1'bz;check();
      end
    end
    $display("FOUR_STATE_PASS checks=%0d",checks);$finish;
  end
endmodule
"""
        record = run_test(out, f"bus{bus}_request{request}_dma{dma}", test)
        record["parameters"] = {"BUS_WIDTH": bus, "MAX_REQUEST_BYTES": request, "DMA_MAX_BYTES": dma}
        records.append(record)
        print(json.dumps(record), flush=True)
    assert source == rtl.read_text()
    (out / "summary.json").write_text(json.dumps({"passed": True,
        "source_sha256": {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in (rtl, Path(__file__), Path(__file__).with_name("run_four_state.py"))},
        "profiles": records, "total_checks": sum(row["checks"] for row in records)}, indent=2) + "\n")


if __name__ == "__main__":
    main()
