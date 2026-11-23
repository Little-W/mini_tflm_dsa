#!/usr/bin/env python3
"""逐周期比较参数装载与完整量化结果，并检查参数有效范围。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import shlex
import signal
import subprocess
import sys
import time

from support import ROOT, RTL

HERE = Path(__file__).resolve().parent
SOURCES = (
    "rtl/npu/writeback/requant_pkg.sv", "rtl/npu/writeback/requant_shift_pipeline.sv",
    "rtl/npu/writeback/requant_compute_lane.sv", "rtl/npu/writeback/requant_group_buffer.sv",
    "rtl/npu/conv/registered_multiplier_s32.sv", "rtl/common/parallel_prefix_add.sv",
    "rtl/common/regfile.v", "test/monitors/requant_group_buffer_observer.sv",
    "asic/rtl/smic40_sram_1r1w.sv", "test/asic_regfile/sram_model.sv",
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def process_tree_rss(pid):
    pending, visited, total = [pid], set(), 0
    while pending:
        current = pending.pop()
        if current in visited:
            continue
        visited.add(current)
        try:
            status = Path(f"/proc/{current}/status").read_text()
            matched = re.search(r"^VmRSS:\s+(\d+)\s+kB$", status, re.M)
            if matched:
                total += int(matched[1])*1024
            for task in Path(f"/proc/{current}/task").iterdir():
                try:
                    pending.extend(map(int, (task / "children").read_text().split()))
                except (FileNotFoundError, ProcessLookupError, PermissionError):
                    pass
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            pass
    return total


def build(command, log_path):
    start = time.monotonic()
    peak = 0
    with log_path.open("w") as stream:
        process = subprocess.Popen(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        try:
            while process.poll() is None:
                peak = max(peak, process_tree_rss(process.pid))
                if peak > 2 * 1024**3:
                    raise RuntimeError("量化测试编译进程组内存超过 2 GiB")
                if time.monotonic() - start > 1800:
                    raise TimeoutError("量化测试编译超过 1800 秒")
                time.sleep(0.2)
            if process.returncode:
                raise subprocess.CalledProcessError(process.returncode, command)
        except BaseException:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=30)
            raise
    return {"elapsed_seconds": round(time.monotonic()-start, 2),
            "peak_process_tree_rss_bytes": peak, "sample_interval_seconds": 0.2,
            "cumulative_peak_child_rss_bytes": int(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss)*1024}


def comparison_top():
    source = (ROOT / "test/requant_time_share/tb.sv").read_text()
    instance = re.search(r"        vec_requant #\(.*?        \);", source, re.S).group()
    instance = instance.replace(".quant_multiplier_lane(),.quant_shift_lane()",
                                ".quant_multiplier_lane(current_multiplier),.quant_shift_lane(current_shift)")
    reference = instance.replace("vec_requant #(", "vec_requant_unpacked #(").replace("u_quant (", "u_reference (")
    replacements = {
        "o_group_ready": "reference_group_ready", "load_quant_req": "reference_dma_request",
        "quant_params_valid": "reference_params_ready", "dma_start": "reference_dma_start",
        "dma_base_addr": "reference_dma_addr", "dma_burst_len_m1": "reference_dma_burst",
        "out_valid": "reference_output_valid", "out_tile_done": "reference_tile_done",
        "out_vec_s8": "reference_s8", "out_vec_s16": "reference_s16",
        "quant_multiplier_lane": "reference_multiplier", "quant_shift_lane": "reference_shift",
    }
    for port, name in replacements.items():
        reference = re.sub(r"\." + port + r"\([^)]*\)", "." + port + "(" + name + ")", reference)
    declarations = """        logic reference_group_ready,reference_dma_request,reference_params_ready;
        logic reference_dma_start,reference_output_valid,reference_tile_done;
        logic [31:0] reference_dma_addr;
        logic [7:0] reference_dma_burst;
        logic signed [7:0] reference_s8[p_vlen];
        logic signed [15:0] reference_s16[p_vlen];
        logic signed [31:0] current_multiplier[p_vlen],current_shift[p_vlen];
        logic signed [31:0] reference_multiplier[p_vlen],reference_shift[p_vlen];
"""
    checks = """
        always @(posedge clk) begin
            if(rst_n) begin
                assert ({group_ready[variant],dma_request[variant],params_ready[variant],dma_start[variant]} ===
                        {reference_group_ready,reference_dma_request,reference_params_ready,reference_dma_start})
                    else $fatal(1,"Parameter or group control cycle differs");
                assert ({dma_addr[variant],dma_burst[variant]} === {reference_dma_addr,reference_dma_burst})
                    else $fatal(1,"Parameter DMA command differs");
                assert(output_valid[variant] === reference_output_valid)
                    else $fatal(1,"Quantized output cycle differs");
                for(integer lane=0;lane<p_vlen;lane=lane+1) begin
                    assert ({current_multiplier[lane],current_shift[lane]} ===
                            {reference_multiplier[lane],reference_shift[lane]})
                        else $fatal(1,"Raw parameter output differs");
                    if(output_valid[variant]) begin
                        assert ({output_s8[variant][lane],output_s16[variant][lane],output_tile_done[variant]} ===
                                {reference_s8[lane],reference_s16[lane],reference_tile_done})
                            else $fatal(1,"Quantized output differs");
                    end
                end
            end
        end
        for(genvar bank=0;bank<p_bus_width/32;bank++)begin:g_amount_monitor
            logic pair_pending;
            always @(posedge clk) begin
                if(!rst_n || init_cfg) pair_pending <= 1'b0;
                else if(u_quant.gen_is_parameter_bank[bank].shift_i_wr_en) begin
                    pair_pending <= !u_quant.gen_is_parameter_bank[bank].product_amount_i_wr_en;
                end
                if(rst_n && !init_cfg && params_ready[variant] && cfg_per_channel && cfg_is)
                    assert(!pair_pending) else $fatal(1,"Parameters published before final pair");
            end
        end
        if(variant==0)begin:g_parallel_range
            always @(posedge clk) begin
                if(rst_n && !init_cfg && cfg_per_channel && cfg_is && u_quant.accept_valid)
                    assert(32'(u_quant.input_group_idx_cur)<u_quant.quant_need_load_r)
                        else $fatal(1,"Parallel computation consumed padded parameter");
            end
        end else begin:g_serial_range
            always @(posedge clk) begin
                if(rst_n && !init_cfg && cfg_per_channel && cfg_is && u_quant.g_serial_arithmetic.issue_valid)
                    assert(32'(u_quant.input_group_idx_cur)<u_quant.quant_need_load_r)
                        else $fatal(1,"Serial computation consumed padded parameter");
            end
        end
"""
    original = re.search(r"        vec_requant #\(.*?        \);", source, re.S).group()
    return source.replace(original, declarations + instance + "\n" + reference + checks)


def driver():
    source = (ROOT / "test/requant_time_share/main.cpp").read_text()
    source = source.replace("BUS=TEST_BUS;", "BUS=TEST_BUS;\nconstexpr unsigned RUNTIME_REUSE=1U<<(31-__builtin_clz(REUSE));")
    source = source.replace("return shifts[(index+scenario)%shifts.size()];",
                            "return (index+scenario)%3==0 ? shifts[(index+scenario)%shifts.size()] : uint32_t(int((index+scenario)&127U)-64);")
    start = source.index("                uint64_t word=memory(r.address);")
    end = source.index("\n", source.index("dut.dma_raw_data[variant]=word;", start))
    source = source[:start] + """#if TEST_BUS > 64
                for(unsigned word_index=0;word_index<BUS/32;++word_index)
                    dut.dma_raw_data[variant][word_index]=memory(r.address+4*word_index);
#else
                uint64_t word=memory(r.address);
                if(BUS==64)word|=uint64_t(memory(r.address+4))<<32;
                dut.dma_raw_data[variant]=word;
#endif""" + source[end:]
    source = source.replace("scenario<96", "scenario<192")
    source = source.replace("if(reuse>REUSE)reuse=REUSE;", "if(reuse>RUNTIME_REUSE)reuse=RUNTIME_REUSE;")
    source = source.replace("if(maximum)reuse=REUSE;", "if(maximum)reuse=RUNTIME_REUSE;")
    source = source.replace("rows==REUSE*N", "rows==RUNTIME_REUSE*N")
    source = source.replace("commands_count=0;", "commands_count=0,load_clears=0,load_resets=0;")
    anchor = "            bool canceled=false;"
    cancel = """            if(dut.cfg_per_channel && scenario%5==1){
                wait([&]{return response[1].address>=0x20000U;});
                idle(scenario%4);
                if((scenario>>1)&1){dut.init_cfg=1;tick();dut.init_cfg=0;++load_clears;}
                else{dut.rst_n=0;tick();dut.rst_n=1;dut.init_cfg=1;tick();dut.init_cfg=0;++load_resets;}
                commands[0].clear();commands[1].clear();received={};
            }
"""
    source = source.replace(anchor, cancel + anchor)
    source = source.replace('require(groups && outputs && clears && resets && full_groups,"Coverage incomplete");',
                            'require(groups && outputs && clears && resets && full_groups && load_clears && load_resets,"Coverage incomplete");')
    source = source.replace('<<",\\\"dma_commands\\\":"<<commands_count',
                            '<<",\\\"load_clears\\\":"<<load_clears<<",\\\"load_resets\\\":"<<load_resets<<",\\\"dma_commands\\\":"<<commands_count')
    return source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference", default="820c2b18")
    parser.add_argument("--verilator", default="verilator")
    parser.add_argument("--profiles", nargs="+", default=["2:1:1:64:rtl", "4:1:3:128:rtl", "16:2:32:64:rtl", "16:2:32:64:asic"],
                        help="VLEN:compute_lanes:reuse_capacity:BUS_WIDTH:rtl_or_asic")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    inputs = {}
    for name in [str(RTL), *SOURCES]:
        destination = out / "inputs" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((ROOT / name).read_bytes())
        inputs[name] = destination
    original = subprocess.check_output(["git", "show", args.reference+":"+str(RTL)], cwd=ROOT, text=True)
    reference = out / "reference_vec_requant.sv"
    reference.write_text(original.replace("module vec_requant #(", "module vec_requant_unpacked #("))
    wrapper, cpp = out / "tb.sv", out / "main.cpp"
    wrapper.write_text(comparison_top())
    cpp.write_text(driver())
    report = {"passed": False, "reference": args.reference,
              "reference_rtl_sha256": hashlib.sha256(original.encode()).hexdigest(),
              "source_sha256": {name: sha(path) for name, path in inputs.items()},
              "test_sha256": {"wrapper": sha(wrapper), "driver": sha(cpp)}, "profiles": []}
    for profile in args.profiles:
        vlen, lanes, reuse, bus, model = profile.split(":")
        vlen, lanes, reuse, bus = map(int, [vlen, lanes, reuse, bus])
        folder = out / profile.replace(":", "_")
        folder.mkdir(exist_ok=True)
        sources = [path for name, path in inputs.items() if not name.startswith("asic/") and not name.endswith("sram_model.sv")]
        options = []
        if model == "asic":
            sources += [inputs["asic/rtl/smic40_sram_1r1w.sv"], inputs["test/asic_regfile/sram_model.sv"]]
            options = ["-DASIC_SRAM"]
        flags = f"-std=c++20 -O1 -fsanitize=undefined -fno-sanitize-recover=all -DTEST_VLEN={vlen} -DTEST_LANES={lanes} -DTEST_REUSE={reuse} -DTEST_BUS={bus} --param=ggc-min-expand=10 --param=ggc-min-heapsize=32768"
        command = [args.verilator, "--cc", "--exe", "--build", "-j", "1", "--assert", "-Wno-fatal",
                   "--top-module", "requant_time_share_tb", "--output-split", "20000", "--output-split-cfuncs", "100",
                   "--Mdir", str(folder / "obj"), f"-Gp_vlen={vlen}", f"-Gp_lanes={lanes}",
                   f"-Gp_reuse={reuse}", f"-Gp_bus_width={bus}", "-CFLAGS", flags, "-LDFLAGS", "-fsanitize=undefined",
                   "-MAKEFLAGS", "CFG_CXXFLAGS_PCH_I=-include OPT_FAST=-O1 OPT_SLOW=-O0 OPT_GLOBAL=-O0",
                   *map(str, sources), str(reference), str(wrapper), str(cpp), *options]
        (folder / "command.txt").write_text(shlex.join(command)+"\n")
        build_record = build(command, folder / "build.log")
        binary = folder / "obj/Vrequant_time_share_tb"
        result = subprocess.run([str(binary)], cwd=ROOT, capture_output=True, text=True, timeout=600)
        (folder / "run.log").write_text(result.stdout + result.stderr)
        result.check_returncode()
        record = json.loads(result.stdout.strip().splitlines()[-1])
        record.update(model=model, reference_cycles_equal=True, reference_data_equal=True,
                      raw_parameters_equal=True, consumed_parameters_in_range=True,
                      binary_sha256=sha(binary), build=build_record)
        report["profiles"].append(record)
        print(json.dumps(record), flush=True)
        (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n")
    report["passed"] = True
    (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n")


if __name__ == "__main__":
    main()
