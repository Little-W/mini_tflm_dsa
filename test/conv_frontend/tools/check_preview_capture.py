#!/usr/bin/env python3
"""检查请求寄存器更新与缓存预读资格的状态关系及四态行为。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[3]
FRONTEND = Path("rtl/npu/conv/conv_im2col_frontend.sv")
CACHE = Path("rtl/npu/dma/cache/conv_windowed_cache.sv")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(command, log, cwd):
    with log.open("w") as output:
        subprocess.run(list(map(str, command)), cwd=cwd, stdout=output,
                       stderr=subprocess.STDOUT, check=True)


def capture_parts(frontend, cache):
    start = frontend.index("  always_comb begin\n    preview_capture_valid =")
    stop = frontend.index("\n  end", start) + len("\n  end")
    capture = frontend[start:stop]
    assert ".preview_valid(preview_capture_valid)," in frontend
    pending = re.search(
        r"  always_ff @\(posedge clk or negedge rst_n\) begin\n"
        r"    if \(!rst_n\) request_pending <=.*?\n  end", frontend, re.S)
    if pending is None:
        raise RuntimeError("未找到请求有效状态的保存条件")
    pending_body = pending.group().split("\n", 1)[1].rsplit("\n  end", 1)[0]
    pending_body = pending_body.replace("request_pending <=", "next_pending =")
    comments_removed = re.sub(r"//[^\n]*|/\*.*?\*/", "", cache, flags=re.S)
    if len(re.findall(r"\bpreview_selected_q\b", comments_removed)) != 4:
        raise RuntimeError("缓存预读状态的使用位置需要重新检查")
    active = re.search(r"assign preview_active\s*=\s*(.*?);", cache, re.S).group(1)
    if "req_valid && preview_selected_q" not in active:
        raise RuntimeError("正式请求有效位未限定缓存预读状态")
    update = re.search(r"else preview_selected_q <=\s*(.*?);", cache, re.S).group(1)
    if not update.startswith("preview_valid &&"):
        raise RuntimeError("缓存预读状态未使用统一的预读资格")
    return capture, pending_body, active, update


def model(capture, pending_body, registered):
    return f"""module capture_relation (
  input logic rst_n, request_pending, original_selected, candidate_selected,
  input logic cache_req_ready, cache_req_valid, eligibility,
  output logic equivalent, capture_direct,
  output logic next_pending, original_next_selected, candidate_next_selected
);
  localparam bit REGISTER_CACHE_REQUEST = 1'b{registered};
  logic preview_capture_valid;
{capture}
  always_comb begin
    next_pending = request_pending;
{pending_body}
    if (!rst_n) begin
      original_next_selected = 1'b0;
      candidate_next_selected = 1'b0;
    end else begin
      original_next_selected =
          REGISTER_CACHE_REQUEST && cache_req_valid && cache_req_ready && eligibility;
      candidate_next_selected = preview_capture_valid && eligibility;
    end
  end
  assign equivalent =
      ((request_pending && original_selected) != (request_pending && candidate_selected)) ||
      ((next_pending && original_next_selected) == (next_pending && candidate_next_selected));
  assign capture_direct = preview_capture_valid ==
      (REGISTER_CACHE_REQUEST && cache_req_ready);
endmodule
"""


FOUR_STATE = r"""
module tb;
  logic rst_n, request_pending, original_selected, candidate_selected;
  logic cache_req_ready, cache_req_valid, eligibility;
  wire equivalent, capture_direct, next_pending, original_next_selected, candidate_next_selected;
  integer checked=0;
  capture_relation dut (.*);
  function automatic logic value(input integer index);
    case(index)
      0: value=1'b0;
      1: value=1'b1;
      2: value=1'bx;
      3: value=1'bz;
    endcase
  endfunction
  initial begin
    for(integer code=0;code<16384;code=code+1) begin
      request_pending=value((code>>0)&3);
      original_selected=value((code>>2)&3);
      candidate_selected=value((code>>4)&3);
      cache_req_ready=value((code>>6)&3);
      cache_req_valid=value((code>>8)&3);
      eligibility=value((code>>10)&3);
      rst_n=value((code>>12)&3);
      #1;
      if ((request_pending && original_selected) ===
          (request_pending && candidate_selected)) begin
        if ((next_pending && original_next_selected) !==
            (next_pending && candidate_next_selected))
          $fatal(1,"PREVIEW_CAPTURE_RELATION_MISMATCH code=%0d",code);
        checked=checked+1;
      end
    end
    if (checked!=10752) $fatal(1,"Unexpected relation coverage %0d",checked);
    $display("PREVIEW_CAPTURE_RELATION_PASS cases=%0d",checked);
    $finish;
  end
endmodule
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources = {str(path): digest(root / path) for path in (FRONTEND, CACHE)}
    capture, pending_body, active, update = capture_parts(
        (root / FRONTEND).read_text(), (root / CACHE).read_text())
    results = []
    for registered in (0, 1):
        case = out / f"registered{registered}"
        case.mkdir(exist_ok=True)
        proof = case / "relation.sv"
        proof.write_text(model(capture, pending_body, registered))
        script = case / "relation.ys"
        script.write_text(
            f"read_verilog -sv {shlex.quote(str(proof))}\n"
            "prep -top capture_relation -flatten\n"
            "sat -verify -prove equivalent 1\n"
            "sat -verify -prove capture_direct 1\n")
        log = case / "formal.log"
        run([sys.executable, root / "scripts/fpga/open_fpga_synth.py",
             "--worker", script], log, root)
        if log.read_text().count("SAT proof finished - no model found: SUCCESS!") != 2:
            raise RuntimeError("预读资格形式证明未完成")
        bench = case / "four_state.sv"
        bench.write_text(proof.read_text() + FOUR_STATE)
        executable = case / "four_state.vvp"
        run(["iverilog", "-g2012", "-s", "tb", "-o", executable, bench],
            case / "four_state_compile.log", root)
        run(["vvp", executable], case / "four_state.log", root)
        if "PREVIEW_CAPTURE_RELATION_PASS cases=10752" not in (case / "four_state.log").read_text():
            raise RuntimeError("四态关系检查未完成")
        results.append(dict(registered=bool(registered), sat_properties=2,
                            four_state_cases=10752, proof_sha256=digest(proof),
                            formal_log_sha256=digest(log),
                            four_state_log_sha256=digest(case / "four_state.log")))
    if sources != {str(path): digest(root / path) for path in (FRONTEND, CACHE)}:
        raise RuntimeError("测试期间生产源码发生变化")
    result = dict(passed=True, source_sha256=sources, actual_capture_block=True,
        actual_pending_update=True, preview_state_uses_checked=True,
        invariant="request_pending && preview_selected_q",
        eligibility="All shared cache eligibility inputs are unconstrained, including X and Z in simulation",
        preview_active_expression=active, preview_update_expression=update,
        sat_properties=sum(row["sat_properties"] for row in results),
        four_state_cases=sum(row["four_state_cases"] for row in results), cases=results)
    (out / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
