#!/usr/bin/env python3
"""证明配置容量上限与请求接收时保存的容量条件等价。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "rtl/npu/ps_compact/ps_frame_store.sv"
PROFILES = [(1, 1, 4096, 2048, 0), (7, 3, 16384, 4096, 1),
            (64, 16, 16384, 2048, 0), (512, 16, 49152, 8192, 1),
            (512, 16, 32768, 4096, 1)]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def model(source: str) -> str:
    start = source.index("    localparam int p_pool_words_width")
    end = source.index("    wire complete_now;", start)
    arithmetic = source[start:end]
    capture_start = source.index("    always_ff @(posedge clk or negedge rst_n) begin", end)
    capture_end = source.index("    logic [31:0] initial_row, initial_bank;", capture_start)
    capture = source[capture_start:capture_end]
    return """module capacity_capture_formal #(
 parameter integer MAX_FRAME_ROWS=512, FRAME_COUNT=16,
 POOL_BYTES=49152, BANK_BYTES=8192, EXTERNAL_RAM=1, p_frame_index=0
)(input logic clk, rst_n, configuration_pending, configure_start,
 input logic frame_request, frame_accept, command_accepted,
 input logic request_capture, cancel_prepared, cancel_request, prepare_start,
 input logic request_valid, capacity_fault,
 input logic [31:0] frame_rows, frame_reserve_rows,
 input logic frame_init, frame_final,
 input logic [31:0] cfg_pool_bank_words, cfg_pool_bank_count, cfg_directory_stride,
 output logic equivalent);
 localparam integer BANKS=EXTERNAL_RAM!=0 ? POOL_BYTES/BANK_BYTES : 4;
 localparam integer BANK_DEPTH=EXTERNAL_RAM!=0 ? BANK_BYTES/16 : POOL_BYTES/64;
 localparam integer BANK_ADDR_BITS=$clog2(BANK_DEPTH)>0 ? $clog2(BANK_DEPTH) : 1;
 localparam integer ROTATION_BITS=$clog2(BANKS)>0 ? $clog2(BANKS) : 1;
 localparam integer FRAME_ID_BITS=FRAME_COUNT>1 ? $clog2(FRAME_COUNT) : 1;
 localparam integer LENGTH_BITS=$clog2(MAX_FRAME_ROWS+1);
 wire [FRAME_ID_BITS-1:0] frame_id=FRAME_ID_BITS'(p_frame_index);
 localparam integer RAW_LINEAR_BITS=$clog2(FRAME_COUNT*MAX_FRAME_ROWS*4+1);
 logic [BANK_ADDR_BITS:0] pool_bank_words_q;
 logic [ROTATION_BITS:0] pool_bank_count_q;
 logic [LENGTH_BITS-1:0] directory_stride_q;
 always_ff @(posedge clk or negedge rst_n) begin
  if (!rst_n) begin
   pool_bank_words_q <= (BANK_ADDR_BITS+1)'(EXTERNAL_RAM==0 ? BANK_DEPTH : 0);
   pool_bank_count_q <= (ROTATION_BITS+1)'(EXTERNAL_RAM==0 ? BANKS : 0);
   directory_stride_q <= LENGTH_BITS'(MAX_FRAME_ROWS);
  end else if (configuration_pending && !configure_start) begin
   pool_bank_words_q <= (BANK_ADDR_BITS+1)'(cfg_pool_bank_words);
   pool_bank_count_q <= (ROTATION_BITS+1)'(cfg_pool_bank_count);
   directory_stride_q <= LENGTH_BITS'(cfg_directory_stride);
  end
 end
 typedef struct packed {
  logic [FRAME_ID_BITS-1:0] id;
  logic [31:0] rows;
  logic init, final_row, legal;
  logic [RAW_LINEAR_BITS-1:0] initial_linear;
 } request_context_t;
 request_context_t request_q;
 logic request_pending_q, pressure_q, request_fits_q, request_released_q;
 wire clear_metadata=configure_start || configuration_pending;
""" + arithmetic + capture + """
 logic [31:0] reference_reserve_q;
 always_ff @(posedge clk) begin
  if (!clear_metadata && !cancel_prepared && request_capture)
   reference_reserve_q <= frame_reserve_rows;
 end
 logic [63:0] requested_rows, pool_words;
 logic expected_fits;
 assign requested_rows = request_q.rows > reference_reserve_q ?
  64'(request_q.rows) : 64'(reference_reserve_q);
 assign pool_words=64'(pool_bank_words_q)*64'(pool_bank_count_q);
 assign expected_fits=(request_q.init && request_q.final_row) ||
  (64'(request_q.initial_linear)+(requested_rows<<2) <= pool_words);
 logic [FRAME_COUNT-1:0] limit_state_matches;
 for (genvar frame=0;frame<FRAME_COUNT;frame++) begin:g_invariant
  logic [RAW_LINEAR_BITS-1:0] initial_linear;
  logic [p_capacity_rows_width:0] expected_available;
  assign initial_linear=(RAW_LINEAR_BITS'(frame)*RAW_LINEAR_BITS'(directory_stride_q))<<2;
  assign expected_available=(p_capacity_rows_width+1)'(pool_words>>2)-
   (p_capacity_rows_width+1)'(initial_linear>>2);
  assign limit_state_matches[frame]=frame_available_rows_q[frame]==expected_available;
 end
 assign equivalent=limit_state_matches[p_frame_index] &&
  (!request_pending_q || 32'(request_q.id)>=FRAME_COUNT || request_fits_q==expected_fits);
endmodule
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = SOURCE.read_text()
    actual = out / "capacity_capture.sv"
    actual.write_text(model(source))
    prefix = ROOT / "rtl/common/parallel_prefix_add.sv"
    report = {"passed": False, "source_sha256": sha(SOURCE),
              "model_sha256": sha(actual), "test_sha256": sha(Path(__file__)),
              "scope": "直接提取配置容量上限与请求接收的 RTL",
              "assumptions": "第一个采样边沿复位；逐个检查有效 frame_id；后续配置与请求控制输入不受限制",
              "profiles": []}
    for rows, frames, pool, bank, external in PROFILES:
        for frame_index in range(frames):
            label = f"rows{rows}_frames{frames}_pool{pool}_bank{bank}_ext{external}_id{frame_index}"
            script = out / (label + ".ys")
            log = out / (label + ".log")
            script.write_text(shlex.join(["read_slang", "--top", "capacity_capture_formal",
                f"-GMAX_FRAME_ROWS={rows}", f"-GFRAME_COUNT={frames}",
                f"-GPOOL_BYTES={pool}", f"-GBANK_BYTES={bank}", f"-GEXTERNAL_RAM={external}", f"-Gp_frame_index={frame_index}",
                str(prefix), str(actual)]) + "\n"
                "prep -top capacity_capture_formal -flatten\nasync2sync\nopt_clean\n"
                "sat -verify -tempinduct -seq 2 -set-at 1 rst_n 0 -prove equivalent 1\n")
            with log.open("w") as stream:
                result = subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                    "--worker", str(script)], stdout=stream, stderr=subprocess.STDOUT, timeout=300)
            passed = result.returncode == 0 and "Induction step proven: SUCCESS!" in log.read_text()
            report["profiles"].append(dict(max_frame_rows=rows, frame_count=frames,
                pool_bytes=pool, bank_bytes=bank, external_ram=external, frame_id=frame_index, passed=passed,
                log_sha256=sha(log)))
            print("PS_REQUEST_CAPACITY", label, passed, flush=True)
            if not passed:
                raise RuntimeError(log.read_text()[-6000:])
    assert SOURCE.read_text() == source
    report["passed"] = True
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
