#!/usr/bin/env python3
"""检查窗口发送资格在二态和四态输入下的完整 RTL 结果。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import subprocess


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "test"))
from reference_sources import read_reference_file
RTL = "rtl/npu/dma/conv_window_queue.sv"


def simulator_source(source: str) -> str:
    """将三个固定描述符字段的赋值展开为常量下标。"""
    loop = """for (int field_index = 0; field_index < 3; field_index++)
        descriptor_prepared_data[field_index] <= descriptor_o_rd_data[field_index][0];"""
    if source.count(loop) != 1:
        raise ValueError("三个描述符字段的赋值无法定位")
    return source.replace(loop, "\n      ".join(
        f"descriptor_prepared_data[{field}] <= descriptor_o_rd_data[{field}][0];"
        for field in range(3)))


def testbench(depth: int, outstanding: int, samples: int) -> str:
    return f"""
module tb;
  localparam integer C = $clog2({depth}+1);
  localparam integer A = $clog2({outstanding}+1);
  logic enable, configure, frontend_error, frontend_rsp_valid, rsp_ready, frontend_rsp_last;
  logic current_valid, reference_valid;
  logic [C-1:0] count_value;
  logic [A-1:0] active_value;
  logic failed_value, busy_value, prepared_value;
  integer seed = 32'h2179c8e1;
  integer checks = 0;
  function automatic logic value4(input integer value);
    case (value & 3)
      0: value4 = 1'b0;
      1: value4 = 1'b1;
      2: value4 = 1'bx;
      3: value4 = 1'bz;
    endcase
  endfunction
  conv_window_queue #(.DEPTH({depth}), .p_frontend_outstanding({outstanding})) dut (
    .clk(1'b0), .rst_n(1'b1), .configure, .enable,
    .frontend_error, .frontend_rsp_valid, .rsp_ready, .frontend_rsp_last,
    .frontend_valid(current_valid)
  );
  conv_window_queue_reference #(.DEPTH({depth}), .p_frontend_outstanding({outstanding})) reference (
    .clk(1'b0), .rst_n(1'b1), .configure, .enable,
    .frontend_error, .frontend_rsp_valid, .rsp_ready, .frontend_rsp_last,
    .frontend_valid(reference_valid)
  );
  initial begin
    for (integer trial = 0; trial < {samples}; trial = trial + 1) begin
      {{enable, configure, frontend_error, frontend_rsp_valid, rsp_ready,
        frontend_rsp_last, failed_value, busy_value, prepared_value}} = $random(seed);
      count_value = $random(seed);
      active_value = $random(seed);
      if (trial % 3 != 0) begin
        case (trial % 11)
          0: enable = value4($random(seed));
          1: configure = value4($random(seed));
          2: frontend_error = value4($random(seed));
          3: frontend_rsp_valid = value4($random(seed));
          4: rsp_ready = value4($random(seed));
          5: frontend_rsp_last = value4($random(seed));
          6: failed_value = value4($random(seed));
          7: busy_value = value4($random(seed));
          8: prepared_value = value4($random(seed));
          9: count_value[(trial/11) % C] = value4($random(seed));
          10: active_value[(trial/11) % A] = value4($random(seed));
        endcase
      end
      if (trial % 7 == 0) begin
        enable = 1; configure = 0; frontend_error = 0;
        failed_value = 0; busy_value = 1; prepared_value = 1;
      end
      dut.count = count_value; reference.count = count_value;
      dut.active_count = active_value; reference.active_count = active_value;
      dut.failed = failed_value; reference.failed = failed_value;
      dut.busy = busy_value; reference.busy = busy_value;
      dut.descriptor_prepared = prepared_value; reference.descriptor_prepared = prepared_value;
      #1;
      if (current_valid !== reference_valid)
        $fatal(1, "Window admission differs at trial %0d", trial);
      checks = checks + 1;
    end
    $display("WINDOW_ADMISSION_FOUR_STATE_PASS checks=%0d", checks);
    $finish;
  end
endmodule
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-ref", required=True)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=65536)
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = (root / RTL).read_bytes()
    reference = read_reference_file(root, args.reference_ref, RTL)
    current_path, reference_path = out / "current.sv", out / "reference.sv"
    current_path.write_text(simulator_source(current.decode()))
    reference_path.write_text(simulator_source(reference.decode()).replace(
        "module conv_window_queue #(", "module conv_window_queue_reference #(", 1))
    report = dict(passed=True, reference_ref=args.reference_ref,
                  source_sha256=hashlib.sha256(current).hexdigest(), cases=[])
    for depth, outstanding in ((2, 1), (3, 2), (4, 3), (7, 4)):
        folder = out / f"depth{depth}_outstanding{outstanding}"
        folder.mkdir(exist_ok=True)
        bench, binary, log = folder / "tb.sv", folder / "test.vvp", folder / "run.log"
        bench.write_text(testbench(depth, outstanding, args.samples))
        with (folder / "build.log").open("w") as stream:
            subprocess.run(["iverilog", "-g2012", "-s", "tb", "-o", str(binary),
                            str(root / "rtl/common/regfile.v"), str(current_path),
                            str(reference_path), str(bench)], check=True,
                           stdout=stream, stderr=subprocess.STDOUT)
        result = subprocess.run(["vvp", str(binary)], check=True, capture_output=True, text=True)
        log.write_text(result.stdout + result.stderr)
        expected = f"WINDOW_ADMISSION_FOUR_STATE_PASS checks={args.samples}"
        if expected not in result.stdout:
            raise RuntimeError("窗口发送资格四态检查没有完成")
        report["cases"].append(dict(depth=depth, outstanding=outstanding, checks=args.samples,
                                    passed=True, log_sha256=hashlib.sha256(log.read_bytes()).hexdigest()))
    report["sources_unchanged"] = current == (root / RTL).read_bytes()
    if not report["sources_unchanged"]:
        raise RuntimeError("检查期间窗口队列源码发生变化")
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"passed": True, "checks": args.samples * len(report["cases"])}))


if __name__ == "__main__":
    main()
