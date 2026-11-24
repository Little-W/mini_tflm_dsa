#!/usr/bin/env python3
"""验证持续卷积描述符、完整请求保存和预取上下文。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
TEST = ROOT / "test/conv_frontend"


def run(command, log):
    with log.open("w") as output:
        subprocess.run(list(map(str, command)), stdout=output,
                       stderr=subprocess.STDOUT, check=True)


def fingerprints(paths):
    return {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def context_monitor():
    """在真实前端实例上检查请求接收、停顿、预取接收和完成交接。"""
    return r'''
  logic audit_capture=0, audit_stall=0, audit_prefetch_capture=0;
  logic audit_saved_word_hit=0;
  logic [146:0] audit_expected, audit_saved;
  logic [406:0] audit_prefetch_expected;
  wire [146:0] audit_fields = {
      DUT.request_addr_q, DUT.request_geometry_q, DUT.request_event_first_q,
      DUT.request_index_valid_q, DUT.request_index_q, DUT.request_epoch_q,
      DUT.request_y_q, DUT.request_progress_q};
  wire [406:0] audit_prefetch_fields = {
      DUT.u_prefetch.accepted_coordinate_q[0], DUT.u_prefetch.accepted_coordinate_q[1],
      DUT.u_prefetch.channel_q[0], DUT.u_prefetch.pfa_origin_channel,
      DUT.u_prefetch.output_coordinate_q[0], DUT.u_prefetch.output_coordinate_q[1],
      DUT.u_prefetch.pfa_kernel_x, DUT.u_prefetch.pfa_kernel_y,
      DUT.u_prefetch.tile_extent_q[0], DUT.u_prefetch.tile_extent_q[1],
      DUT.u_prefetch.reference_q.address, DUT.u_prefetch.reference_q.index,
      DUT.u_prefetch.reference_q.epoch, DUT.u_prefetch.reference_q.index_valid};
  integer audit_request_captures=0, audit_incoming_captures=0;
  integer audit_live_count=0, audit_prefetch_count=0, audit_forward_count=0;
  integer audit_forward_hits=0, audit_stall_count=0, audit_saved_word_hits=0;
  integer audit_first_cycle_accepts=0, audit_idle_input_changes=0;
  integer audit_preview_fallback_checks=0;
  logic audit_previous_offer=0;
  logic [63:0] audit_previous_descriptor=0;

  initial begin
    assert(DUT.REGISTER_CACHE_REQUEST && !DUT.REGISTER_DESCRIPTOR &&
           !DUT.REGISTER_ROW_ADDRESS && DUT.CACHE_RESPONSE_DEPTH==1)
      else $fatal(1,"Unexpected production frontend configuration");
  end

  // 所有请求字段在同一接收边沿取样；停顿检查使用前一边沿保存的完整请求。
  always @(posedge clk) begin
    audit_previous_offer<=tile_valid;
    audit_previous_descriptor<={tile_p0,tile_q0};
    if(rst_n && tile_valid && !audit_previous_offer && tile_ready) audit_first_cycle_accepts++;
    if(rst_n && !tile_valid && {tile_p0,tile_q0}!=audit_previous_descriptor) audit_idle_input_changes++;
    audit_capture<=rst_n && DUT.cache_req_valid && DUT.cache_req_ready;
    audit_stall<=rst_n && DUT.request_pending && !DUT.cache_port_ready;
    audit_prefetch_capture<=rst_n && DUT.cache_port_valid && DUT.cache_port_ready &&
        DUT.prefetch_phase==0 && DUT.c.prefetch_enable;
    audit_saved_word_hit<=rst_n && DUT.tile_commit && !DUT.committing_tile.invalid &&
        DUT.committing_tile.fast && !DUT.committing_tile.padding && DUT.committing_tile.word_hit;
    audit_expected<={DUT.cache_req_addr,
        (DUT.incoming_context ? DUT.committing_tile.geometry : DUT.geometry_tile),
        ((DUT.incoming_context ? DUT.committing_tile.geometry : DUT.geometry_tile) &&
         DUT.cache_req_addr[3:0]==0),
        DUT.req_index_valid, DUT.req_index, DUT.req_epoch,
        DUT.request_y[15:0], DUT.request_output_y};
    audit_saved<=audit_fields;
    audit_prefetch_expected<={
        DUT.ix, DUT.iy, DUT.ch, DUT.ch0, DUT.ox, DUT.oy, DUT.kx, DUT.ky_q,
        32'(DUT.rows_q), 32'(DUT.cols_q), DUT.request_addr_q,
        DUT.request_index_q, DUT.request_epoch_q, DUT.request_index_valid_q};
    if (rst_n) begin
      // 当前快照尚不可消费时，生产前端等待响应，保持下一请求无效。
      if (DUT.u_cache.g_window.u_window.preview_active &&
          DUT.u_cache.g_window.u_window.accepted_request &&
          !DUT.u_cache.g_window.u_window.req_fire) begin
        audit_preview_fallback_checks++;
        assert(!DUT.cache_req_valid)
          else $fatal(1,"Next request offered while the prepared request enters the cache queue");
      end
      if (DUT.cache_req_valid && DUT.cache_req_ready) begin
        audit_request_captures++;
        if (DUT.incoming_context) audit_incoming_captures++;
      end
      if (DUT.request_pending) begin
        audit_live_count++;
        assert(DUT.request_addr_q==DUT.addr)
          else $fatal(1,"Request address differs from active stream at cycle %0d",cycles);
        assert(DUT.request_geometry_q==DUT.geometry_tile)
          else $fatal(1,"Request geometry differs from active stream");
        assert(DUT.request_y_q==DUT.iy[15:0])
          else $fatal(1,"Request input row differs from active stream");
        assert(DUT.request_progress_q==DUT.oy)
          else $fatal(1,"Request output row differs from active stream at cycle %0d",cycles);
        assert(DUT.request_index_q==DUT.current_req_index)
          else $fatal(1,"Request window index differs from active stream at cycle %0d",cycles);
        assert(DUT.request_epoch_q==DUT.current_req_epoch)
          else $fatal(1,"Request window epoch differs from active stream at cycle %0d",cycles);
        if (!DUT.cache_port_ready) audit_stall_count++;
      end
      if (DUT.cache_port_valid && DUT.cache_port_ready &&
          DUT.prefetch_phase==0 && DUT.c.prefetch_enable) audit_prefetch_count++;
      if (DUT.tile_commit && DUT.descriptor_response_forward) begin
        audit_forward_count++;
        if (DUT.committing_tile.word_hit) audit_forward_hits++;
      end
      if (DUT.tile_commit && !DUT.committing_tile.invalid && DUT.committing_tile.fast &&
          !DUT.committing_tile.padding && DUT.committing_tile.word_hit) audit_saved_word_hits++;
    end
  end

  // 在非阻塞赋值完成后检查保存结果，覆盖旧响应与新描述符同时接收的情况。
  always @(negedge clk) begin
    if (rst_n && audit_capture)
      assert(DUT.request_pending && audit_fields===audit_expected)
        else $fatal(1,"Request field capture mismatch");
    if (rst_n && audit_stall)
      assert(DUT.request_pending && audit_fields===audit_saved)
        else $fatal(1,"Request fields changed while stalled");
    if (rst_n && audit_prefetch_capture)
      assert(audit_prefetch_fields===audit_prefetch_expected)
        else $fatal(1,"Prefetch context differs from the accepted request");
    if (rst_n && audit_saved_word_hit)
      assert(DUT.state[$clog2(conv_im2col_frontend_pkg::STREAM)])
        else $fatal(1,"Saved-word descriptor did not enter STREAM");
  end
  final $display("CONTINUOUS_REQUEST_CONTEXT captures=%0d incoming=%0d live=%0d prefetch=%0d forward=%0d forward_hits=%0d stalls=%0d saved_word_hits=%0d",
      audit_request_captures, audit_incoming_captures, audit_live_count,
      audit_prefetch_count, audit_forward_count, audit_forward_hits,
      audit_stall_count, audit_saved_word_hits);
  final $display("CONTINUOUS_ADMISSION first_cycle=%0d idle_changes=%0d",
      audit_first_cycle_accepts,audit_idle_input_changes);
  final $display("CONTINUOUS_PREVIEW fallback_checks=%0d",audit_preview_fallback_checks);
'''.replace("DUT.", "g_direct.dut.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--verilator", default=shutil.which("verilator") or "verilator")
    parser.add_argument("--lanes", type=int, choices=(8, 16), nargs="+", default=[8, 16])
    parser.add_argument("--cache-sets", type=int, choices=tuple(1 << n for n in range(1, 9)),
                        help="Override cache sets; defaults are 16 for 8 lanes and 64 for 16 lanes")
    parser.add_argument("--windows", type=int, choices=(0, 1), nargs="+", default=[1])
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--changing-idle-inputs", action="store_true",
                        help="Change descriptor data every idle offer cycle before asserting tile_valid")
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    source_root = args.source_root.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    helper = runpy.run_path(str(TEST / "tools/compare_frontend.py"))
    continuous = runpy.run_path(str(TEST / "tools/continuous_frontend.py"))["continuous_bench"]
    files = runpy.run_path(str(TEST / "tools/run_rtl.py"))["FILES"]
    dependency_files = runpy.run_path(str(ROOT / "scripts/rtl/source_files.py"))["input_files"]

    # 仿真观察器与综合条件同时启用，生产 RTL 始终取自指定源码目录。
    monitors = out / "monitors"
    monitors.mkdir(exist_ok=True)
    sources = []
    for path in map(Path, files):
        relative = path.relative_to(ROOT)
        if relative.parts[0] == "rtl":
            sources.append(source_root / relative)
        elif relative.parts[:2] == ("test", "monitors"):
            target = monitors / path.name
            target.write_text("`undef SYNTHESIS\n" + path.read_text() + "\n`define SYNTHESIS 1\n")
            sources.append(target)
        elif path.name != "tb_conv_im2col_frontend.sv":
            sources.append(path)

    text = helper["widen_memory"]((TEST / "tests/tb_conv_im2col_frontend.sv").read_text())
    text = continuous(text, admission="finish", descriptor_capacity=1)
    if args.changing_idle_inputs:
        old = "              repeat(2) @(negedge clk);"
        new = """              repeat(2) begin
                tile_p0=$urandom;tile_q0=$urandom;tile_rows=RW'($urandom);tile_slot=3'($urandom);
                @(negedge clk);
              end"""
        if text.count(old) != 1:
            raise RuntimeError("Cannot locate descriptor idle input interval")
        text = text.replace(old, new)
        first_offer = "            tile_p0=32'(queued_descriptor[offer][0]);"
        prepare_first_offer = """            if(offer==0) begin
              tile_valid=0;
              while(!tile_ready && !error) begin
                tile_p0=$urandom;tile_q0=$urandom;tile_rows=RW'($urandom);tile_slot=3'($urandom);
                @(negedge clk);
              end
            end
""" + first_offer
        if text.count(first_offer) != 1:
            raise RuntimeError("Cannot locate the first descriptor offer")
        text = text.replace(first_offer, prepare_first_offer)
    point = text.rindex("endmodule")
    bench = out / "tb_continuous_request.sv"
    bench.write_text(text[:point] + context_monitor() + text[point:])
    sources.append(bench)
    vectors = out / "vectors.txt"
    run([sys.executable, TEST / "tests/gen_rtl_vectors.py", "--size", "16", "--out", vectors],
        out / "vectors.log")
    expected_jobs = int(vectors.read_text().split(None, 1)[0])
    if expected_jobs != 42:
        raise RuntimeError(f"Expected 42 numerical jobs, found {expected_jobs}")

    inputs = dependency_files(sources, source_root, [source_root / "include"])
    inputs += [vectors, Path(__file__).resolve(), TEST / "tools/continuous_frontend.py",
               TEST / "tools/compare_frontend.py", TEST / "tools/run_rtl.py",
               TEST / "tests/gen_rtl_vectors.py", TEST / "tests/run_model_tests.py",
               TEST / "model/conv_model.py", ROOT / "scripts/rtl/source_files.py"]
    source_hashes = fingerprints(inputs)
    rows = []
    for lanes in dict.fromkeys(args.lanes):
        sets = args.cache_sets if args.cache_sets is not None else (16 if lanes == 8 else 64)
        for window in dict.fromkeys(args.windows):
            case = out / f"lanes{lanes}_window{window}"
            case.mkdir(exist_ok=True)
            objects = case / "obj"
            command = [args.verilator, "--binary", "--timing", "--assert",
                       "-DNPU_SIM_ASSERT", "-DCONV_ASSERT", "-DXILINX_FPGA=1", "-DSYNTHESIS=1",
                       "-Wno-fatal", "--top-module", "tb_conv_im2col_frontend", "-GSIZE=16",
                       "-GBUS_WIDTH=64", f"-GLANES={lanes}", f"-GCACHE_SETS={sets}",
                       "-GLINE_BYTES=128", "-GNARROW_MODE=2", f"-GWINDOWED=1'b{window}",
                       f"-GPREFETCH=1'b{window}", "--Mdir", objects, "-j", str(args.jobs),
                       "--output-groups", "0", "--output-split", "12000",
                       "-CFLAGS", "-std=c++20 -O1", "-MAKEFLAGS",
                       "OPT_FAST=-O1 OPT_SLOW=-O0 VK_PCH_I_FAST= VK_PCH_I_SLOW= CFG_CXXFLAGS_PCH=-E",
                       "-I" + str(source_root / "include"), *sources]
            try:
                run(command, case / "build.log")
                warnings = helper["reviewed_warnings"](case / "build.log", 0)
                run([objects / "Vtb_conv_im2col_frontend", "+VECTORS=" + str(vectors)],
                    case / "run.log")
            finally:
                if objects.exists():
                    for path in objects.iterdir():
                        if path.suffix in (".o", ".a", ".gch", ".cpp", ".h", ".d", ".mk"):
                            path.unlink()
            if fingerprints(inputs) != source_hashes:
                raise RuntimeError("Source files changed during verification")
            result = (case / "run.log").read_text()
            numerical = re.search(r"RTL_FRONTEND_PASS jobs=(\d+) cycles=(\d+)", result)
            continuous_result = re.search(
                r"FRONTEND_CONTINUOUS_PASS blocked=(\d+) concurrent=(\d+) finish_captures=(\d+) "
                r"commit_captures=(\d+) capacity=(\d+)", result)
            context = re.search(
                r"CONTINUOUS_REQUEST_CONTEXT captures=(\d+) incoming=(\d+) live=(\d+) "
                r"prefetch=(\d+) forward=(\d+) forward_hits=(\d+) stalls=(\d+) saved_word_hits=(\d+)",
                result)
            admission = re.search(r"CONTINUOUS_ADMISSION first_cycle=(\d+) idle_changes=(\d+)", result)
            preview = re.search(r"CONTINUOUS_PREVIEW fallback_checks=(\d+)", result)
            if any(value is None for value in (numerical, continuous_result, context, admission, preview)):
                raise RuntimeError(f"Incomplete numerical or context checks: {case / 'run.log'}")
            if int(numerical[1]) != expected_jobs:
                raise RuntimeError("The simulator did not complete every numerical job")
            if args.changing_idle_inputs and (not int(admission[1]) or not int(admission[2])):
                raise RuntimeError("First-cycle acceptance or changing idle inputs were not exercised")
            counts = dict(zip(("request_captures", "incoming_captures", "pending_context_checks",
                               "prefetch_context_checks", "response_forward_commits", "response_forward_hits",
                               "request_stall_cycles", "saved_word_hits"), map(int, context.groups())))
            if not counts["request_captures"] or not counts["pending_context_checks"]:
                raise RuntimeError("Request context checks were not exercised")
            if window and not all(counts[name] for name in (
                    "incoming_captures", "prefetch_context_checks", "response_forward_commits",
                    "response_forward_hits")):
                raise RuntimeError("Window request and response forwarding checks were not exercised")
            rows.append({"passed": True, "lanes": lanes, "cache_sets": sets, "line_bytes": 128,
                         "cache_ways": 2, "cache_bytes": sets * 2 * 128,
                         "windowed_prefetch": bool(window), "jobs": int(numerical[1]),
                         "cycles": int(numerical[2]), "request_metadata_bits": 147,
                         "prefetch_context_bits": 407, **counts,
                         "first_cycle_accepts": int(admission[1]), "idle_input_changes": int(admission[2]),
                         "preview_fallback_checks": int(preview[1]),
                         **dict(zip(("blocked_offers", "concurrent_offers", "finish_captures",
                                     "commit_captures", "descriptor_capacity"),
                                    map(int, continuous_result.groups()))),
                         "command": list(map(str, command)), "warnings": warnings})
            print("CONTINUOUS_REQUEST_PASS", f"lanes={lanes}", f"window={window}",
                  f"jobs={numerical[1]}", f"cycles={numerical[2]}",
                  f"finish_captures={continuous_result[3]}",
                  f"forward_hits={counts['response_forward_hits']}",
                  f"stalls={counts['request_stall_cycles']}", flush=True)

    summary = {"passed": True, "source_root": str(source_root),
               "changing_idle_inputs": args.changing_idle_inputs,
               "source_sha256": source_hashes, "sources_unchanged": True, "cases": rows}
    (out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
