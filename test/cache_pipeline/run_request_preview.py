#!/usr/bin/env python3
"""验证同步预读快照、正式请求、异常响应和取消时的缓存行为。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError("缓存测试结构与预读检查要求不一致")
    return text.replace(old, new)


def preview_bench(source):
    text = source.read_text()
    text = replace_once(text, ".CACHE_POLICY(3),.DEMAND_DEPTH(DEMAND_DEPTH)",
                        ".CACHE_POLICY(3),.p_preview_request(1'b1),.DEMAND_DEPTH(DEMAND_DEPTH)")
    text = replace_once(text, "@(negedge clk);rst_n=0;req_valid=0;prefetch_valid=0;cfg_valid=0;rsp_ready=0;",
        "@(negedge clk);rst_n=0;req_valid=0;preview_valid=0;prefetch_valid=0;cfg_valid=0;rsp_ready=0;")
    start = text.index("    task automatic stream(")
    end = text.index("    task automatic drain;", start)
    text = text[:start] + r'''
    task automatic stream(input int count,input int mode,input bit random_backpressure=0,
                          input bit expect_error=0);
        logic [31:0] random_state;
        bit taken;
        random_state=32'h84a3db21;
        for(int sent=0;sent<count;sent++) begin
            @(negedge clk);
            req_valid=0;req_addr=stream_address(sent,mode);req_expect_error=expect_error;
            preview_valid=1;preview_addr=req_addr;
            preview_index_valid=req_window_index_valid;preview_index=req_window_index;
            @(posedge clk);
            @(negedge clk);preview_valid=0;req_valid=1;
            taken=0;
            while(!taken) begin
                @(posedge clk);taken=req_ready;
                @(negedge clk);
                if(random_backpressure) begin
                    random_state={random_state[30:0],random_state[31]^random_state[21]^random_state[1]^random_state[0]};
                    rsp_ready=random_state[0] || random_state[3];
                end
            end
            req_valid=0;
        end
        req_expect_error=0;
    endtask

''' + text[end:]
    text = replace_once(text, "accepted_cycle[i]-accepted_cycle[i-1]!=1 ||\n                   completed_cycle[i]-completed_cycle[i-1]!=1",
                        "accepted_cycle[i]-accepted_cycle[i-1]!=3 ||\n                   completed_cycle[i]-completed_cycle[i-1]!=3")
    text = replace_once(text, "warm_accept_interval=1;warm_return_interval=1;",
                        "warm_accept_interval=3;warm_return_interval=3;")
    text = replace_once(text, "    int warm_accept_interval=0,warm_return_interval=0;", r'''
    int warm_accept_interval=0,warm_return_interval=0;
    int preview_direct=0,preview_conflicts=0,preview_fallbacks=0,preview_overlaps=0;
    always @(posedge clk) if(rst_n) begin
        if(dut.g_window.u_window.preview_active && dut.g_window.u_window.req_fire)
            preview_direct++;
        if(preview_valid && dut.g_window.u_window.spec_read_conflict)
            preview_conflicts++;
        if(dut.g_window.u_window.preview_active && dut.g_window.u_window.request_push)
            preview_fallbacks++;
        if(dut.g_window.u_window.preview_active && dut.g_window.u_window.request_push && preview_valid)
            preview_overlaps++;
    end
''')
    text = replace_once(text, "        reset_cache();configure(1);", r'''
        reset_cache();configure(1);
        old_bytes=read_bytes;
        for(int hint=0;hint<24;hint++) begin
            @(negedge clk);
            preview_valid=hint[0];preview_addr=$urandom;
            preview_index_valid=hint[1];preview_index=$urandom;
            req_addr=$urandom;req_window_epoch=$urandom;req_window_progress=$urandom;
        end
        @(negedge clk);preview_valid=0;
        repeat(3) @(negedge clk);
        if(accepted!=0 || completed!=0 || pending!=0 || read_bytes!=old_bytes ||
           arvalid || rsp_valid || hint_pending || dut.g_window.u_window.pf_count!=0)
            $fatal(1,"preview changed externally visible cache state");
        report("preview_without_request");
        @(negedge clk);preview_valid=1;preview_addr=32'h1234;
        @(posedge clk);
        @(negedge clk);preview_valid=0;
        configure(1);
        if(accepted!=0 || completed!=0 || pending!=0 || read_bytes!=old_bytes)
            $fatal(1,"configuration retained a cancelled preview");
        report("preview_configuration_cancel");
        req_window_epoch=0;req_window_progress=0;
''')
    text = replace_once(text, "        if(pending!=0 || accepted!=completed || peak!=DEMAND_DEPTH)", r'''
        configure(12,1,1);
        offer_prefetch(32'h1300);
        while(!dut.g_window.u_window.ram_wen) @(negedge clk);
        req_addr=dut.g_window.u_window.span_addr;
        preview_addr=req_addr;preview_index_valid=0;preview_index=0;preview_valid=1;
        @(posedge clk);
        @(negedge clk);preview_valid=0;req_valid=1;
        do @(posedge clk);while(!req_ready);
        @(negedge clk);req_valid=0;
        drain();
        if(preview_conflicts==0 || preview_fallbacks==0)
            $fatal(1,"synchronous read and fill conflict was not exercised");
        report("preview_fill_collision");
        configure(13,1,1);
        offer_prefetch(32'h1300);
        while(!dut.g_window.u_window.ram_wen) @(negedge clk);
        req_addr=dut.g_window.u_window.span_addr;
        preview_addr=req_addr;preview_index_valid=0;preview_index=0;preview_valid=1;
        @(posedge clk);
        // 正式请求保存到队列时继续准备另一地址，检查两个请求的响应顺序。
        @(negedge clk);preview_addr=32'h1404;req_valid=1;
        do @(posedge clk);while(!req_ready);
        @(negedge clk);preview_valid=0;req_addr=32'h1404;
        do @(posedge clk);while(!req_ready);
        @(negedge clk);req_valid=0;
        drain();
        if(preview_overlaps==0) $fatal(1,"preview and queued request overlap was not exercised");
        report("preview_during_queue_admission");
        @(negedge clk);preview_valid=1;preview_addr=32'h1300;
        @(posedge clk);
        reset_cache();configure(14);rsp_ready=1;
        stream(2,0);drain();
        report("preview_reset_cancel");
        if(preview_direct<64) $fatal(1,"prepared hit responses were not exercised");
        $display("CACHE_PREVIEW_CONTEXT direct=%0d conflicts=%0d fallbacks=%0d overlaps=%0d",
            preview_direct,preview_conflicts,preview_fallbacks,preview_overlaps);
        if(pending!=0 || accepted!=completed || peak!=DEMAND_DEPTH)''')
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--verilator", default=shutil.which("verilator") or "verilator")
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--cache-sets", type=int, choices=tuple(1 << n for n in range(1, 9)),
                        default=64, help="Number of sets in the two-way, 128-byte-line cache")
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    bench_source = ROOT / "test/cache_pipeline/tb_cache_pipeline.sv"
    bench = out / "tb_cache_request_preview.sv"
    bench.write_text(preview_bench(bench_source))
    files = [ROOT / "rtl/npu/dma/cache/conv_read_cache.sv",
             ROOT / "rtl/npu/dma/cache/conv_sdp_ram.sv",
             ROOT / "rtl/npu/conv/conv_axi_span_reader.sv",
             ROOT / "test/conv_reuse/axi_counted_memory.sv", bench]
    files = runpy.run_path(str(ROOT / "test/monitors/sources.py"))["with_observers"](files)
    files = [root / path.relative_to(ROOT) if path.is_relative_to(ROOT / "rtl") else path
             for path in files]
    dependencies = runpy.run_path(str(ROOT / "scripts/rtl/source_files.py"))["input_files"](
        files, root, [root / "include"])
    dependencies += [Path(__file__).resolve(), bench_source]
    hashes = {str(path): digest(path) for path in dependencies}
    objects = out / "obj"
    command = [args.verilator, "--binary", "--timing", "--assert", "-DCONV_ASSERT",
               "-DNPU_SIM_ASSERT", "-DXILINX_FPGA=1", "-Wno-fatal", "--top-module", "tb_cache_pipeline",
               "-GDEMAND_DEPTH=1", "-GCACHE_WAYS=2", f"-GCACHE_SETS={args.cache_sets}",
               "-GLINE_BYTES=128", "-GCHECK_EXTENDED_SETS=1",
               "-GBUS_WIDTH=64", "-GREAD_WIDTH=128", "-GHIT_LATENCY=0",
               "--Mdir", str(objects), "-j", str(args.jobs), "--output-groups", "0",
               "--output-split", "12000", "-CFLAGS", "-std=c++20 -O1", "-MAKEFLAGS",
               "OPT_FAST=-O1 OPT_SLOW=-O0 VK_PCH_I_FAST= VK_PCH_I_SLOW= CFG_CXXFLAGS_PCH=-E",
               "-I" + str(root / "include"), *map(str, files)]
    try:
        with (out / "build.log").open("w") as log:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
        warnings = [line for line in (out / "build.log").read_text().splitlines()
                    if line.startswith("%Warning")]
        if any(re.match(r"%Warning-(UNOPTFLAT|LATCH|MULTIDRIVEN|PINMISSING)", row) for row in warnings):
            raise RuntimeError("缓存预读测试包含未允许的结构诊断")
        binary = objects / "Vtb_cache_pipeline"
        with (out / "run.log").open("w") as log:
            subprocess.run([str(binary)], stdout=log, stderr=subprocess.STDOUT, check=True, timeout=120)
        log = (out / "run.log").read_text()
        cases = [dict(re.findall(r"(\w+)=([^ ]+)", line)) for line in log.splitlines()
                 if line.startswith("CACHE_PIPELINE_CASE ")]
        if len(cases) != 20 or "CACHE_PIPELINE_PASS " not in log:
            raise RuntimeError("缓存预读检查未完成全部二十项场景")
        context = re.search(r"CACHE_PREVIEW_CONTEXT direct=(\d+) conflicts=(\d+) fallbacks=(\d+) overlaps=(\d+)", log)
        if context is None or not all(int(value) > 0 for value in context.groups()):
            raise RuntimeError("缓存预读未覆盖命中、同步读写冲突和队列处理")
        sets = re.search(r"CACHE_SET_COVERAGE highest=(\d+) indexed=(\d+) physical=(\d+) "
                         r"fills=(\d+) clears=(\d+) clear_cycles=(\d+) stride=(\d+)", log)
        if sets is None or int(sets[1]) != args.cache_sets - 1 or \
                not all(int(value) > 0 for value in sets.groups()[1:]) or \
                int(sets[6]) != args.cache_sets or int(sets[7]) != args.cache_sets * 128:
            raise RuntimeError("缓存集合上界、冲突地址或逐集合清除未完成检查")
        unchanged = all(digest(path) == value for path, value in hashes.items())
        if not unchanged:
            raise RuntimeError("缓存预读检查过程中源码发生变化")
        summary = {"passed": True, "source_sha256": hashes, "source_unchanged": unchanged,
                   "binary_sha256": digest(binary), "cases": cases,
                   "preview_state_bits": 1, "bus_width": 64, "read_width": 128,
                   "cache_sets": args.cache_sets, "cache_ways": 2,
                   "cache_bytes": args.cache_sets * 2 * 128, "line_bytes": 128, "request_depth": 1,
                   "coverage": dict(zip(("direct", "conflicts", "fallbacks", "overlaps"), map(int, context.groups()))),
                   "set_coverage": dict(zip(("highest", "indexed", "physical", "fills", "clears",
                                              "clear_cycles", "stride"), map(int, sets.groups()))),
                   "command": command}
        (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print("CACHE_REQUEST_PREVIEW_PASS cases=20", f"sets={args.cache_sets}", flush=True)
    finally:
        if objects.is_dir():
            for path in objects.iterdir():
                if path.is_file() and path.suffix in (".o", ".a", ".gch", ".cpp", ".h", ".d", ".mk"):
                    path.unlink()


if __name__ == "__main__":
    main()
