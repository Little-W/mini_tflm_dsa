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
    parser.add_argument("--reference-root", type=Path,
                        help="从独立源码目录读取参考缓存 RTL")
    parser.add_argument("--out", type=Path, default=ROOT / "build/cache_storage/compare")
    parser.add_argument("--verilator", default=shutil.which("verilator") or "verilator")
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--lint-only", action="store_true", help="只检查相同数值比较模型的语法与接口")
    parser.add_argument("--fpga", action="store_true", help="使用官方LUT模型检查FPGA配置逻辑")
    parser.add_argument("--asic", action="store_true", help="启用 ASIC 综合配置及功能 SRAM 模型")
    parser.add_argument("--extra-source", type=Path, action="append", default=[])
    parser.add_argument("--compare-prefetch-keys", action="store_true",
                        help="逐周期比较全部固定槽位读取及活动预取选择结果")
    parser.add_argument("--cache-sets", type=int, default=8)
    parser.add_argument("--line-bytes", type=int, choices=(8, 16, 32, 64, 128, 256), default=16)
    parser.add_argument("--defer-retire-shift", action="store_true")
    parser.add_argument("--read-width", type=int, choices=(32, 64, 128), default=32)
    parser.add_argument("--source-root", type=Path, default=ROOT,
                        help="从独立源码目录读取候选 RTL")
    parser.add_argument("--bus-widths", nargs="+", type=int, choices=(32, 64), default=[32, 64])
    parser.add_argument("--profiles", nargs="+", choices=("4x2", "4x1", "2x2", "1x2"), default=["4x2", "4x1", "1x2"])
    args = parser.parse_args()
    if args.asic and args.fpga:
        parser.error("单次验证需要选择一种实现模式")
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    dependency_reader = runpy.run_path(str(ROOT / "scripts/rtl/source_files.py"))["with_dependencies"]
    reference_inputs = {}
    if args.reference_root:
        reference_root = args.reference_root.resolve()
        reference_sources = dependency_reader(
            [reference_root / "rtl/npu/dma/cache/conv_read_cache.sv"], reference_root)
        reference_inputs = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                            for path in reference_sources}
        old_text = "\n".join(path.read_text() for path in reference_sources)
    else:
        old_text = read_rtl_source(args.reference_commit +
                                  ":rtl/npu/dma/cache/conv_read_cache.sv", cwd=ROOT, text=True)
    # 每个参考模块使用其同一源码目录中的依赖，公共参数接口可独立演化。
    for name in sorted(set(re.findall(r"^\s*module\s+(\w+)", old_text, re.M)), key=len, reverse=True):
        old_text = re.sub(r"\b" + name + r"\b", "reference_" + name, old_text)
    old_file = out / "reference_cache.sv"
    old_file.write_text(old_text)
    template = (ROOT / "test/cache_pipeline/tb_cache_pipeline.sv").read_text()
    template = template.replace("parameter int LINE_BYTES=16,",
                                "parameter int LINE_BYTES=16,\n    parameter bit DEFER_RETIRE_SHIFT=0,")
    template = template.replace(".CACHE_POLICY(3),.DEMAND_DEPTH(DEMAND_DEPTH)",
                                ".p_defer_retire_shift(DEFER_RETIRE_SHIFT),.CACHE_POLICY(3),.DEMAND_DEPTH(DEMAND_DEPTH)")
    # 计数存储同时覆盖测试台的组地址范围和六十四个缓存行的预取访问。
    template = template.replace(".TRACK_BYTES(TRACK_BYTES)",
        ".TRACK_BYTES(TRACK_BYTES > 2048+64*LINE_BYTES ? TRACK_BYTES : 2048+64*LINE_BYTES)")
    template = template.replace("logic [31:0] prefetch_addr=0;",
        "logic [31:0] prefetch_addr=0,prefetch_epoch=0;\n" +
        "    int prefetch_peak=0,prefetch_swaps=0,prefetch_overlap=0;")
    template = template.replace(".prefetch_window_epoch(0)", ".prefetch_window_epoch(prefetch_epoch)")
    stress = '''
        if(LINE_BYTES>16) begin
            @(negedge clk);cfg_bytes=32'(2042+64*LINE_BYTES);
        end
        configure(12,1,1);
        @(negedge clk);block_ar=1;rsp_ready=0;req_window_epoch=3;
        for(int i=0;i<10;i++) begin
            prefetch_epoch=32'(i%4);
            offer_prefetch(32'h1500+32'(LINE_BYTES*i));
        end
        stream(1,0);
        @(negedge clk);block_ar=0;rsp_ready=1;
        fork
            begin
                for(int i=0;i<64;i++) begin
                    @(negedge clk);prefetch_epoch=32'(i%4);
                    offer_prefetch(32'h1200+32'(LINE_BYTES*((i*7)%48)));
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
            offer_prefetch(32'h1200+32'(2*LINE_BYTES*phase));
            repeat(phase) @(negedge clk);
            prefetch_epoch=3;
            offer_prefetch(32'h1200+32'(LINE_BYTES*(2*phase+1)));
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
    if args.compare_prefetch_keys:
        declarations += "\n    longint unsigned prefetch_key_checks=0;\n"
        checks += '''
        if (dut.g_window.u_window.prefetch_keys_o_rd_data !==
            reference_dut.g_window.u_window.prefetch_keys_o_rd_data)
            $fatal(1,"prefetch fixed-slot data mismatch cycle=%0d",cycle);
        if (dut.g_window.u_window.pf_selected_keys !==
            reference_dut.g_window.u_window.pf_selected_keys)
            $fatal(1,"prefetch selected data mismatch cycle=%0d",cycle);
        prefetch_key_checks++;
'''
        template = template.replace('        $display("PREFETCH_QUEUE_PASS',
            '        $display("PREFETCH_STORAGE_PASS fixed_ports=8 selected_ports=1 cycles=%0d",prefetch_key_checks);\n'
            '        $display("PREFETCH_QUEUE_PASS')
    template = template[:end] + declarations + "\n" + reference + "\n    always @(posedge clk) if (rst_n) begin\n" + checks + "    end\n" + template[end:]
    tb_file = out / "tb_cache_pipeline.sv"
    tb_file.write_text(template)
    memory = (ROOT / "test/conv_reuse/axi_counted_memory.sv").read_text()
    memory_file = out / "axi_counted_memory.sv"
    memory_file.write_text(memory)
    candidate_root = args.source_root.resolve()
    sources = [candidate_root / "rtl/npu/dma/cache/conv_read_cache.sv",
               candidate_root / "rtl/npu/dma/cache/conv_sdp_ram.sv",
               candidate_root / "rtl/npu/conv/conv_axi_span_reader.sv", old_file, tb_file, memory_file]
    sources += [candidate_root / "rtl/common" / name for name in
                ("regfile.v", "onehot_check.sv", "add_equal.sv", "parallel_prefix_add.sv", "unsigned_compare.sv")]
    sources = dependency_reader(sources, candidate_root)
    modules = set().union(*(set(re.findall(r"\bmodule\s+(\w+)", path.read_text())) for path in sources))
    for name in sorted(modules):
        observer = ROOT / "test/monitors" / (name + "_observer.sv")
        if observer.exists() and observer not in sources:
            sources.append(observer)
    observer_inputs = {}
    if args.asic:
        prepared_sources = []
        for source in sources:
            if source.parent == ROOT / "test/monitors":
                observer_inputs[str(source)] = hashlib.sha256(source.read_bytes()).hexdigest()
                target = out / ("asic_" + source.name)
                target.write_text(source.read_text().replace("`ifndef SYNTHESIS", "`ifdef NPU_SIM_ASSERT"))
                prepared_sources.append(target)
            else:
                prepared_sources.append(source)
        sources = prepared_sources
        sources += [path.resolve() for path in args.extra_source]
    elif args.extra_source:
        sources += [path.resolve() for path in args.extra_source]
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
            command = [args.verilator, "--lint-only" if args.lint_only else "--binary",
                       "--timing", "--assert", "-DNPU_SIM_ASSERT", "-Wno-fatal",
                       "--top-module", "tb_cache_pipeline", f"-GBUS_WIDTH={bus}", f"-GDEMAND_DEPTH={depth}",
                       f"-GREAD_WIDTH={args.read_width}", f"-GLINE_BYTES={args.line_bytes}",
                       f"-GDEFER_RETIRE_SHIFT={int(args.defer_retire_shift)}",
                       f"-GCACHE_WAYS={ways}", f"-GCACHE_SETS={args.cache_sets}", "--Mdir", str(folder / "obj"), "-j", str(args.jobs),
                       "--output-groups", "0", "--output-split", "12000", "-CFLAGS", "-std=c++20 -O1",
                       "-MAKEFLAGS", "OPT_FAST=-O1 OPT_SLOW=-O0 VK_PCH_I_FAST= VK_PCH_I_SLOW= CFG_CXXFLAGS_PCH=-E",
                       *(["-DXILINX_FPGA=1"] if args.fpga else []), *map(str, sources)]
            if args.asic:
                command[1:1] = ["-DSYNTHESIS=1", "-DASIC_SYNTHESIS=1", "-DASIC_SRAM=1"]
            with (folder / "compile.log").open("w") as log:
                subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
            if args.lint_only:
                results.append({"bus_width": bus, "read_width": args.read_width, "depth": depth,
                                "ways": ways, "cache_sets": args.cache_sets, "line_bytes": args.line_bytes,
                                "defer_retire_shift": args.defer_retire_shift, "lint_passed": True})
                print(f"CACHE_COMPARISON_LINT_PASS bus={bus} depth={depth} ways={ways}", flush=True)
                continue
            run = subprocess.run([str(folder / "obj/Vtb_cache_pipeline")], cwd=ROOT, capture_output=True, text=True)
            (folder / "run.log").write_text(run.stdout + run.stderr)
            if run.returncode:
                raise RuntimeError(run.stdout[-4000:] + run.stderr)
            passed = next(line for line in run.stdout.splitlines() if line.startswith("CACHE_PIPELINE_PASS"))
            prefetch = next(line for line in run.stdout.splitlines() if line.startswith("PREFETCH_QUEUE_PASS"))
            results.append({"bus_width": bus, "read_width": args.read_width, "depth": depth, "ways": ways,
                            "cache_sets": args.cache_sets, "line_bytes": args.line_bytes,
                            "defer_retire_shift": args.defer_retire_shift, "result": passed,
                            "prefetch_queue": prefetch})
            if args.compare_prefetch_keys:
                results[-1]["prefetch_storage"] = next(
                    line for line in run.stdout.splitlines() if line.startswith("PREFETCH_STORAGE_PASS"))
            print(f"COMPARE_PASS bus={bus} depth={depth} ways={ways}", flush=True)
            for temporary in (folder / "obj").iterdir():
                if temporary.suffix in (".o", ".gch"):
                    temporary.unlink()
    assert hashes == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    assert observer_inputs == {path: hashlib.sha256(Path(path).read_bytes()).hexdigest()
                               for path in observer_inputs}
    assert reference_inputs == {path: hashlib.sha256(Path(path).read_bytes()).hexdigest()
                                for path in reference_inputs}
    (out / "summary.json").write_text(json.dumps({"passed": True,
        "reference_commit": None if args.reference_root else args.reference_commit,
        "reference_root": str(args.reference_root.resolve()) if args.reference_root else None,
        "output_ports": list(OUTPUTS), "source_sha256": hashes, "fpga": args.fpga,
        "asic": args.asic, "observer_input_sha256": observer_inputs,
        "reference_input_sha256": reference_inputs,
        "compare_prefetch_keys": args.compare_prefetch_keys,
        "verification_scope": "syntax_and_interfaces" if args.lint_only else "cycle_and_numeric_comparison",
        "profiles": results}, indent=2) + "\n")


if __name__ == "__main__":
    main()
