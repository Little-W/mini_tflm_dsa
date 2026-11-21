#!/usr/bin/env python3
"""在相同输入和 AXI 返回下逐周期比较缓存的全部外部输出。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]
OUTPUTS = {"cfg_ready": 1, "req_ready": 1, "hint_pending": 1, "rsp_valid": 1,
           "rsp_data": 32, "rsp_error": 1, "arvalid": 1, "araddr": 32,
           "arlen": 8, "arsize": 3, "arburst": 2, "rready": 1, "prefetch_ready": 1}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-commit", default="aa2ef9a3")
    parser.add_argument("--out", type=Path, default=ROOT / "build/cache_storage/compare")
    parser.add_argument("--verilator", default=shutil.which("verilator") or "verilator")
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--fpga", action="store_true", help="使用官方LUT模型检查FPGA配置逻辑")
    parser.add_argument("--cache-sets", type=int, default=8)
    parser.add_argument("--read-width", type=int, choices=(32, 64, 128), default=32)
    parser.add_argument("--source-root", type=Path, default=ROOT,
                        help="从独立源码目录读取候选 RTL")
    parser.add_argument("--bus-widths", nargs="+", type=int, choices=(32, 64), default=[32, 64])
    parser.add_argument("--profiles", nargs="+", choices=("4x2", "4x1", "1x2"), default=["4x2", "4x1", "1x2"])
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    old_text = read_rtl_source(args.reference_commit +
        ":rtl/npu/dma/cache/conv_read_cache.sv", cwd=ROOT, text=True)
    for name in ("conv_cache_rank_table", "conv_read_cache_reference", "conv_windowed_cache", "conv_read_cache"):
        old_text = re.sub(r"\b" + name + r"\b", "reference_" + name, old_text)
    old_file = out / "reference_cache.sv"
    old_file.write_text(old_text)
    template = (ROOT / "test/cache_pipeline/tb_cache_pipeline.sv").read_text()
    template = template.replace("logic [31:0] prefetch_addr=0;",
        "logic [31:0] prefetch_addr=0,prefetch_epoch=0;\n" +
        "    int prefetch_peak=0,prefetch_swaps=0,prefetch_overlap=0;")
    template = template.replace(".prefetch_window_epoch(0)", ".prefetch_window_epoch(prefetch_epoch)")
    stress = '''
        configure(12,1,1);
        @(negedge clk);block_ar=1;rsp_ready=0;req_window_epoch=3;
        for(int i=0;i<10;i++) begin
            prefetch_epoch=32'(i%4);
            offer_prefetch(32'h1500+32'(16*i));
        end
        stream(1,0);
        @(negedge clk);block_ar=0;rsp_ready=1;
        fork
            begin
                for(int i=0;i<64;i++) begin
                    @(negedge clk);prefetch_epoch=32'(i%4);
                    offer_prefetch(32'h1200+32'(16*((i*7)%48)));
                end
            end
            begin
                stream(64,2,1);
            end
        join
        drain();
        configure(13,1,1);
        for(int phase=0;phase<16;phase++) begin
            prefetch_epoch=0;
            offer_prefetch(32'h1200+32'(32*phase));
            repeat(phase) @(negedge clk);
            prefetch_epoch=3;
            offer_prefetch(32'h1210+32'(32*phase));
            drain();
        end
        if(prefetch_peak!=8 || prefetch_swaps<4 || prefetch_overlap==0)
            $fatal(1,"prefetch queue coverage peak=%0d swaps=%0d overlap=%0d",
                   prefetch_peak,prefetch_swaps,prefetch_overlap);
        report("prefetch_priority_and_reuse");
        $display("PREFETCH_QUEUE_PASS peak=%0d swaps=%0d simultaneous_push_pop=%0d",
                 prefetch_peak,prefetch_swaps,prefetch_overlap);
'''
    template = template.replace("        if(pending!=0 || accepted!=completed || peak!=DEMAND_DEPTH)",
                                stress + "\n        if(pending!=0 || accepted!=completed || peak!=DEMAND_DEPTH)")
    start = template.index("    conv_read_cache #(")
    end = template.index("    assign stat_hits", start)
    original = template[start:end]
    reference = original.replace("conv_read_cache #(", "reference_conv_read_cache #(").replace(") dut(", ") reference_dut(")
    reference = reference.replace(".*);", ",".join(f".{port}(reference_{port})" for port in OUTPUTS) + ",.*);")
    declarations = "\n".join(f"    logic [$bits({port})-1:0] reference_{port};" for port in OUTPUTS)
    always_ports = tuple(OUTPUTS)
    checks = "\n".join(f'        if ({port} !== reference_{port}) $fatal(1, "cache cycle mismatch {port} cycle=%0d", cycle);'
                       for port in always_ports)
    checks += '''
        if (rsp_valid && {rsp_data,rsp_error} !== {reference_rsp_data,reference_rsp_error})
            $fatal(1, "cache response mismatch cycle=%0d", cycle);
        if (arvalid && {araddr,arlen,arsize,arburst} !== {reference_araddr,reference_arlen,reference_arsize,reference_arburst})
            $fatal(1, "cache address mismatch cycle=%0d", cycle);
        if ({dut.g_window.u_window.pf_count,dut.g_window.u_window.pf_head,dut.g_window.u_window.pf_tail,
             dut.g_window.u_window.pf_active_valid} !==
            {reference_dut.g_window.u_window.pf_count,reference_dut.g_window.u_window.pf_head,
             reference_dut.g_window.u_window.pf_tail,reference_dut.g_window.u_window.pf_active_valid})
            $fatal(1,"prefetch queue timing mismatch cycle=%0d",cycle);
        if (dut.g_window.u_window.pf_active_valid &&
            {dut.g_window.u_window.pf_addr,dut.g_window.u_window.pf_index,dut.g_window.u_window.pf_epoch,
             dut.g_window.u_window.pf_retire,dut.g_window.u_window.pf_index_valid} !==
            {reference_dut.g_window.u_window.pf_addr,reference_dut.g_window.u_window.pf_index,
             reference_dut.g_window.u_window.pf_epoch,reference_dut.g_window.u_window.pf_retire,
             reference_dut.g_window.u_window.pf_index_valid})
            $fatal(1,"prefetch priority or payload mismatch cycle=%0d",cycle);
        if (int'(dut.g_window.u_window.pf_count)>prefetch_peak)
            prefetch_peak=int'(dut.g_window.u_window.pf_count);
        if (dut.g_window.u_window.pf_pop && dut.g_window.u_window.pf_pick!=dut.g_window.u_window.pf_head)
            prefetch_swaps++;
        if (dut.g_window.u_window.pf_push && dut.g_window.u_window.pf_pop)
            prefetch_overlap++;
'''
    template = template[:end] + declarations + "\n" + reference + "\n    always @(posedge clk) if (rst_n) begin\n" + checks + "    end\n" + template[end:]
    tb_file = out / "tb_cache_pipeline.sv"
    tb_file.write_text(template)
    memory = (ROOT / "test/conv_reuse/axi_counted_memory.sv").read_text()
    memory_file = out / "axi_counted_memory.sv"
    memory_file.write_text(memory)
    sources = [ROOT / "rtl/npu/dma/cache/conv_read_cache.sv", ROOT / "rtl/npu/dma/cache/conv_sdp_ram.sv",
               ROOT / "rtl/npu/conv/conv_axi_span_reader.sv", old_file, tb_file, memory_file]
    sources = runpy.run_path(str(ROOT / "test/monitors/sources.py"))["with_observers"](sources)
    candidate_root = args.source_root.resolve()
    sources = [candidate_root / path.relative_to(ROOT)
               if path.is_relative_to(ROOT) and path.relative_to(ROOT).parts[0] == "rtl" else path
               for path in sources]
    if args.fpga:
        import pyosys
        library = Path(pyosys.__file__).parent / "share/xilinx/cells_sim.v"
        model = out / "lut6_2.sv"
        model.write_text(re.search(r"^module LUT6_2\b.*?^endmodule", library.read_text(), re.M | re.S).group(0) + "\n")
        sources.append(model)
    hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    results = []
    for bus in args.bus_widths:
        for profile in args.profiles:
            depth, ways = map(int, profile.split("x"))
            folder = out / f"b{bus}_d{depth}_w{ways}"
            folder.mkdir(exist_ok=True)
            command = [args.verilator, "--binary", "--timing", "--assert", "-DNPU_SIM_ASSERT", "-Wno-fatal",
                       "--top-module", "tb_cache_pipeline", f"-GBUS_WIDTH={bus}", f"-GDEMAND_DEPTH={depth}",
                       f"-GREAD_WIDTH={args.read_width}",
                       f"-GCACHE_WAYS={ways}", f"-GCACHE_SETS={args.cache_sets}", "--Mdir", str(folder / "obj"), "-j", str(args.jobs),
                       "--output-groups", "0", "--output-split", "12000", "-CFLAGS", "-std=c++20 -O1",
                       "-MAKEFLAGS", "OPT_FAST=-O1 OPT_SLOW=-O0 VK_PCH_I_FAST= VK_PCH_I_SLOW= CFG_CXXFLAGS_PCH=-E",
                       *(["-DXILINX_FPGA=1"] if args.fpga else []), *map(str, sources)]
            with (folder / "compile.log").open("w") as log:
                subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
            run = subprocess.run([str(folder / "obj/Vtb_cache_pipeline")], cwd=ROOT, capture_output=True, text=True)
            (folder / "run.log").write_text(run.stdout + run.stderr)
            if run.returncode:
                raise RuntimeError(run.stdout[-4000:] + run.stderr)
            passed = next(line for line in run.stdout.splitlines() if line.startswith("CACHE_PIPELINE_PASS"))
            prefetch = next(line for line in run.stdout.splitlines() if line.startswith("PREFETCH_QUEUE_PASS"))
            results.append({"bus_width": bus, "read_width": args.read_width, "depth": depth, "ways": ways,
                            "cache_sets": args.cache_sets, "result": passed,
                            "prefetch_queue": prefetch})
            print(f"COMPARE_PASS bus={bus} depth={depth} ways={ways}", flush=True)
            for temporary in (folder / "obj").iterdir():
                if temporary.suffix in (".o", ".gch"):
                    temporary.unlink()
    assert hashes == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    (out / "summary.json").write_text(json.dumps({"passed": True, "reference_commit": args.reference_commit,
        "output_ports": list(OUTPUTS), "source_sha256": hashes, "fpga": args.fpga,
        "profiles": results}, indent=2) + "\n")


if __name__ == "__main__":
    main()
