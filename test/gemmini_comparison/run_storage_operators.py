#!/usr/bin/env python3
"""在共同存储和访存配置下运行 GEMM、卷积与 DW，并检查全部内存内容。"""
from __future__ import annotations

import argparse
import ctypes as ct
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from storage_vector_profile import resolve_vector_configuration, resolve_cache_configuration
SCHEDULE_FIELDS = (
    "ia_reuse", "w_reuse", "row_groups", "row_tail_tiles", "col_groups",
    "col_tail_tiles", "dataflow_mode", "candidates", "estimated_cycles",
    "read_words", "read_requests", "write_words", "write_requests",
    "compute_cycles", "ps_payload_bytes", "ps_control", "ia_bank_count",
    "ia_cache_bytes", "ps_pool_bytes", "frame_rows", "predicted_resident_frames",
    "read_beats", "write_beats", "memory_policy_valid", "literal_record_bytes",
)
TILING_FIELDS = SCHEDULE_FIELDS[:6]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n")


def clean_build_products(output):
    """只移除本次仿真对象目录中的 Verilator 生成文件。"""
    root = Path(output).resolve()
    directory = root / "sim" / "obj"
    report = {"object_directory": str(directory), "files_removed": 0, "bytes_removed": 0}
    if not directory.is_dir():
        return report
    resolved = directory.resolve()
    if resolved in (root, (root / "sim").resolve()) or resolved in root.parents:
        raise ValueError("仿真对象目录不能指向输出目录或其上级目录")
    suffixes = {".o", ".a", ".gch", ".cpp", ".h", ".d", ".mk"}
    for path in directory.iterdir():
        if path.is_symlink() or not path.is_file():
            continue
        if not path.name.startswith(("Vtb_latest_operators", "verilated")):
            continue
        if path.suffix not in suffixes:
            continue
        if path.resolve().parent != resolved:
            raise ValueError("生成文件位于本次仿真对象目录之外")
        size = path.stat().st_size
        path.unlink()
        report["files_removed"] += 1
        report["bytes_removed"] += size
    return report


def vector_configuration(args):
    """读取生产模块支持的并行参数，明确记录每个实验的实际资源。"""
    return resolve_vector_configuration(args.repo, pe_count=args.pe_count,
                                        bank_count=args.bank_count, bus_width=64)


def hardware_profile(args, normalize):
    profile = normalize(dict(size=16, bus_width=64, ps_compress=True,
        ia_cache_blocks=4, ps_frame_count=16, ps_storage_rows=0,
        shared_bank_bytes=args.bank_bytes, shared_bank_count=args.bank_count,
        shared_total_bytes=args.bank_bytes*args.bank_count,
        im2col_cache_bytes=args.cache_bytes, output_banks_s16_max=4,
        ram_continuous_read_beat_cycles=1, ram_read_first_latency=8,
        dma_max_bytes=2048, force_raw=True, ps_force_raw=True),
        root=args.repo, literal_bound=False, ram_fixed_lat=0)
    vector = vector_configuration(args)
    profile.update({key: vector[key] for key in (
        "vector_pe_count", "quantization_lanes", "window_lanes", "shared_quant_enable")})
    profile.update(resolve_cache_configuration(args.repo, args.cache_bytes))
    profile['conv_cache_demand_outstanding'] = 1
    profile['conv_register_descriptor'] = 0
    profile['conv_register_cache_request'] = 1
    profile['rtl_simulation_defines'] = [name for name, enabled in (
        ('SYNTHESIS', args.synthesis), ('XILINX_FPGA', args.fpga)) if enabled]
    return profile


def planner(args, out, profile, header_text):
    out.mkdir(parents=True, exist_ok=True)
    header = out / "hardware_profile.h"
    header.write_text(header_text)
    source = HERE / "storage_planner_bridge.c"
    library = out / "planner.so"
    command = ["gcc", "-std=c11", "-O2", "-shared", "-fPIC", "-Wall", "-Wextra",
               "-DDSA_MMIO_CUSTOM=1", "-DDSA_PS_COMPRESS=1", "-DDSA_PS_FORCE_RAW=1",
               "-include", str(header),
               "-I", str(args.repo / "drivers"), str(source), "-o", str(library)]
    tracked = [source, header, args.repo / "drivers/dsa_accel.c",
               *sorted((args.repo / "drivers").glob("*.h"))]
    source_hashes = {str(p): digest(p) for p in tracked}
    completed = subprocess.run(command, capture_output=True, text=True)
    (out / "compile.log").write_text(completed.stdout + completed.stderr)
    completed.check_returncode()
    if source_hashes != {str(p): digest(p) for p in tracked}:
        raise ValueError("Planner compilation inputs changed")
    write_json(out / "build.json", dict(command=command,
        returncode=completed.returncode, sources_unchanged_during_build=True,
        source_sha256=source_hashes, binary_sha256=digest(library), profile=profile))
    lib = ct.CDLL(str(library))
    lib.operator_schedule.argtypes = [ct.POINTER(ct.c_uint32), ct.c_void_p,
                                     ct.c_uint32, ct.POINTER(ct.c_uint64)]
    lib.operator_schedule.restype = ct.c_int
    return lib


def schedule(lib, cfg, weights):
    inputs = (ct.c_uint32 * 64)(*cfg)
    payload = ct.create_string_buffer(weights)
    outputs = (ct.c_uint64 * len(SCHEDULE_FIELDS))()
    if not lib.operator_schedule(inputs, payload, len(weights), outputs):
        raise ValueError("Production planner rejected a common operator")
    return dict(zip(SCHEDULE_FIELDS, outputs))


def schedule_key(value):
    return tuple(value[name] for name in (
        "estimated_cycles", "read_words", "read_requests", "compute_cycles",
        "write_requests", "ps_payload_bytes", "dataflow_mode"))


def prepare_group(args, kind, lib, runner, gemm, conv):
    workloads = args.workloads / kind
    catalogue = json.loads((workloads / "workloads.json").read_text())
    cases = []
    for item in catalogue["cases"]:
        if args.cases and item["name"] not in args.cases:
            continue
        manifest = workloads / item["manifest"]
        if digest(manifest) != item["manifest_sha256"]:
            raise ValueError("Common workload manifest changed")
        source = manifest.parent
        description = json.loads(manifest.read_text())
        depthwise = description.get("operator") == "depthwise"
        layouts = (["depthwise-native"] if depthwise else
                   ["raw", "packed"] if kind == "conv" else
                   ["row-major", "lhs-packed", "rhs-packed", "both-packed"])
        case_out = args.out / kind / "cases" / item["name"]
        choices = []
        for layout in layouts:
            target = case_out / "candidates" / layout
            if kind == "gemm":
                record = gemm.prepare_case(runner, source, target, 4, 16, 0,
                    schedule_mode="legacy", dataflow="ws", layout=layout,
                    requested_r=1, requested_w=1, s16_output_banks=4,
                    dma_max_bytes=2048, bus_width=64, read_beat_cycles=1)
            else:
                record = conv.prepare_case(runner, source, target,
                    ia_cache_blocks=4, ps_frames=16, ps_storage_rows=0,
                    s16_output_banks=4, schedule_mode="legacy", dataflow="ws",
                    rhs_layout="raw" if depthwise else layout,
                    requested_r=1, requested_w=1,
                    dma_max_bytes=2048, bus_width=64, read_beat_cycles=1)
            cfg = [int(value, 16) for value in (target / "config.mem").read_text().split()]
            selected = None
            if not depthwise:
                weight_name = "b_transposed" if kind == "gemm" else "weights_npu"
                weight = gemm.payload(source, description["tensors"][weight_name])
                if cfg[29] & 2:
                    weight = gemm.pack_matrix(weight, cfg[5], cfg[4])
                selected = schedule(lib, cfg, weight)
                cfg[6], cfg[7], cfg[8] = (selected[k] for k in ("ia_reuse", "w_reuse", "dataflow_mode"))
                cfg[30] = selected["row_groups"] | selected["col_groups"] << 16
                cfg[31] = selected["row_tail_tiles"] | selected["col_tail_tiles"] << 16
                cfg[61], cfg[62] = selected["ps_control"], selected["ia_bank_count"]
                record.update(schedule_mode="production_shared_auto", schedule=selected,
                    dataflow="is" if selected["dataflow_mode"] else "ws",
                    tiling={k: selected[k] for k in TILING_FIELDS})
            else:
                cfg[61], cfg[62] = 0, 1
            (target / "config.mem").write_text("".join(f"{v & 0xffffffff:08x}\n" for v in cfg))
            record["files"]["config.mem"] = digest(target / "config.mem")
            record["operator_kind"] = "depthwise" if depthwise else kind
            record["physical_layout"] = layout
            record["configuration_words"] = cfg
            record["schedule_configuration"] = None if depthwise else dict(
                production_entry="drivers/dsa_schedule_impl.h:dsa_schedule_cached_plan",
                hardware_profile=str(args.out / "hardware_profile.json"),
                requested_dataflow="auto", requested_r=0, requested_w=0,
                rows=cfg[3], depth=cfg[4], cols=cfg[5],
                lhs_address=cfg[14], rhs_address=cfg[15], output_address=cfg[17],
                lhs_stride=cfg[18], rhs_stride=cfg[19], output_stride=cfg[20],
                lhs_tile_packed=cfg[29] & 1, rhs_tile_packed=(cfg[29] >> 1) & 1,
                spatial=bool(cfg[32]), source_s8=True, compact_mode_mask=3,
                per_channel=bool(cfg[13]), has_bias=bool(cfg[16]),
                literal_record_bytes=selected["literal_record_bytes"],
                shared_total_bytes=args.bank_bytes*args.bank_count,
                shared_bank_bytes=args.bank_bytes, im2col_cache_bytes=args.cache_bytes)
            write_json(target / "case.json", record)
            choices.append((target, record, selected))
        chosen = choices[0] if depthwise else min(choices, key=lambda x: schedule_key(x[2]))
        target, record, _ = chosen
        for name in ("init.mem", "golden.mem", "config.mem"):
            shutil.copy2(target / name, case_out / name)
        record["layout_candidates"] = [dict(layout=row[1]["physical_layout"], schedule=row[2]) for row in choices]
        if not depthwise:
            record["requested_layout" if kind == "gemm" else "requested_rhs_layout"] = "auto"
        record["case_directory"] = str(case_out)
        write_json(case_out / "case.json", record)
        cases.append(record)
    return cases


def ar_interval_monitor():
    """在测试台中限制读地址接受间隔，并记录实际最短间隔。"""
    return r'''
    integer read_address_interval = 1;
    logic memory_arvalid, memory_arready;
    integer unsigned address_cooldown;
    longint unsigned address_cycle, last_address_cycle, minimum_address_interval;
    longint unsigned accepted_addresses;
    initial begin
        if ($value$plusargs("AR_MIN_INTERVAL=%d", read_address_interval)) begin end
        assert (read_address_interval >= 1)
            else $fatal(1, "Read address interval must be positive");
    end
    assign memory_arvalid = arvalid && (address_cooldown == 0);
    assign arready = memory_arready && (address_cooldown == 0);
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            address_cooldown <= 0;
            address_cycle <= 0;
            last_address_cycle <= 0;
            minimum_address_interval <= '1;
            accepted_addresses <= 0;
        end else begin
            address_cycle <= address_cycle + 1;
            if (address_cooldown != 0) address_cooldown <= address_cooldown - 1;
            assert ((arvalid && arready) == (memory_arvalid && memory_arready))
                else $fatal(1, "Read address handshake differs across memory service");
            if (arvalid && arready) begin
                address_cooldown <= unsigned'(read_address_interval - 1);
                if (accepted_addresses != 0) begin
                    assert (address_cycle - last_address_cycle >= 64'(read_address_interval))
                        else $fatal(1, "Read address interval is below the requested minimum");
                    if (address_cycle - last_address_cycle < minimum_address_interval)
                        minimum_address_interval <= address_cycle - last_address_cycle;
                end
                last_address_cycle <= address_cycle;
                accepted_addresses <= accepted_addresses + 1;
            end
        end
    end
    final $display("COMMON_AR_INTERVAL minimum=%0d required=%0d accepted=%0d",
        accepted_addresses > 1 ? minimum_address_interval : 0,
        read_address_interval, accepted_addresses);
'''


def output_tensor_dump():
    """在完成计时和完整内存比较后导出实际输出字节。"""
    return r'''
    task automatic write_output_tensor;
        string output_path;
        integer output_file;
        integer unsigned output_base, output_bytes;
        if ($value$plusargs("OUTPUT_DUMP=%s", output_path)) begin
            assert ($value$plusargs("OUTPUT_BASE=%h", output_base) &&
                    $value$plusargs("OUTPUT_BYTES=%d", output_bytes))
                else $fatal(1, "Output address and byte count are required");
            assert ({1'b0, output_base} + {1'b0, output_bytes} <= 33'(WORDS*4))
                else $fatal(1, "Output tensor exceeds system memory");
            output_file = $fopen(output_path, "wb");
            assert (output_file != 0) else $fatal(1, "Cannot open output tensor file");
            for (integer unsigned index=0; index<output_bytes; index++)
                $fwrite(output_file, "%c", 8'(u_mem.mem[(output_base+index)>>2] >>
                    (8*((output_base+index)&3))));
            $fclose(output_file);
            $display("COMMON_OUTPUT_TENSOR address=%0d bytes=%0d", output_base, output_bytes);
        end
    endtask
'''


def testbench(args):
    vector = vector_configuration(args)
    text = (args.repo / "test/gemmini_comparison/tb_common_conv.sv").read_text()
    # 测试台沿用生产端口，并显式固定容量、访存计时和共享存储参数。
    text = text.replace("module tb_common_conv;", "module tb_latest_operators;")
    text = text.replace("localparam int WORDS = 131072;", "localparam int WORDS = 524288;")
    text = text.replace(".DMA_MAX_BYTES(`TB_DMA_MAX_BYTES),", ".DMA_MAX_BYTES(`TB_DMA_MAX_BYTES),\n"
        "              .VECTOR_PE_COUNT(`TB_VECTOR_PE_COUNT),\n"
        + ("              .WINDOW_LANES(`TB_WINDOW_LANES),\n" if vector["top_window_parameter"] else "") +
        "              .SHARED_BANK_BYTES(`TB_SHARED_BANK_BYTES), .SHARED_BANK_COUNT(`TB_SHARED_BANK_COUNT),\n"
        "              .IM2COL_CACHE_BYTES(`TB_IM2COL_CACHE_BYTES),")
    text = text.replace(".cfg_lhs_tile_packed(1'b0)", ".cfg_lhs_tile_packed(cfg[29][0])")
    text = text.replace(".CONV_CACHE_WAYS(2)", ".CONV_CACHE_WAYS(`TB_CONV_CACHE_WAYS)")
    text = text.replace(".CONV_LINE_BYTES(16)", ".CONV_LINE_BYTES(`TB_CONV_LINE_BYTES)")
    text = text.replace(".protect_input(1'b1)", ".protect_input(cfg[32][0] || cfg[59][0])")
    text = text.replace(".cfg_vector_enable(cfg[59][0]), .cfg_vector(vector_cfg),", 
        ".cfg_vector_enable(cfg[59][0]), .cfg_vector(vector_cfg),\n"
        "        .cfg_ps_control(cfg[61]), .cfg_shared_ia_banks(cfg[62]),")
    text = text.replace("COMMON_CONV_PASS", "COMMON_OPERATOR_PASS")
    memory_instance = "    conv_test_axi_memory #("
    memory_ports = "        .arvalid, .arready, .araddr, .arlen, .arsize, .arburst,"
    if text.count(memory_instance) != 1 or text.count(memory_ports) != 1:
        raise ValueError("共同测试台需要一个明确的外部存储读地址接口")
    text = text.replace(memory_instance, ar_interval_monitor() + "\n" + memory_instance)
    text = text.replace(memory_ports,
        "        .arvalid(memory_arvalid), .arready(memory_arready), .araddr, .arlen, .arsize, .arburst,")
    text = text.replace("Conv comparison failed or timed out", "Operator failed or timed out")
    text = text.replace("Conv output or memory preservation mismatch", "Operator output or memory preservation mismatch")
    output_check = '        assert (errors == 0) else $fatal(1, "Operator output or memory preservation mismatch");'
    if text.count(output_check) != 1:
        raise ValueError("共同测试台需要一个完整内存比较完成点")
    text = text.replace("    initial begin : run_case", output_tensor_dump() + "\n    initial begin : run_case")
    text = text.replace(output_check, output_check + "\n        write_output_tensor();")
    check = '''        assert (u_dut.SHARED_RAM_ENABLED &&
                u_dut.SHARED_TOTAL_BYTES == `TB_SHARED_BANK_BYTES * `TB_SHARED_BANK_COUNT &&
                u_dut.IM2COL_CACHE_BYTES == `TB_IM2COL_CACHE_BYTES &&
                u_dut.u_matrix_engine.u_task_configuration.PS_REQUIRE_RAW_CAPACITY)
            else $fatal(1, "Shared memory configuration differs from the experiment");
        $display("COMMON_HARDWARE shared_enabled=%0d shared_bytes=%0d bank_bytes=%0d bank_count=%0d im2col_bytes=%0d",
            u_dut.SHARED_RAM_ENABLED, u_dut.SHARED_TOTAL_BYTES, `TB_SHARED_BANK_BYTES,
            `TB_SHARED_BANK_COUNT, u_dut.IM2COL_CACHE_BYTES);
'''
    text = text.replace('        assert (sa_ready) else', check + '        assert (sa_ready) else')
    vector_check = '''        assert (u_dut.VECTOR_PE_COUNT == `TB_VECTOR_PE_COUNT &&
                u_dut.g_vector_engine.u_engine.WINDOW_LANES == `TB_WINDOW_LANES)
            else $fatal(1, "Vector parallel configuration differs from the experiment");
'''
    if vector["quantization_parameter"]:
        vector_check += '''        assert (u_dut.g_vector_engine.u_engine.QUANT_LANES == `TB_QUANT_LANES)
            else $fatal(1, "Vector quantization configuration differs from the experiment");
'''
    if vector["shared_quant_parameter"]:
        vector_check += '''        assert (u_dut.g_vector_engine.u_engine.SHARED_QUANT_ENABLE == `TB_SHARED_QUANT_ENABLE)
            else $fatal(1, "Shared vector quantization differs from the experiment");
'''
    vector_check += '''        $display("COMMON_VECTOR pe_count=%0d quantization_lanes=%0d window_lanes=%0d shared_quant_enable=%0d",
            u_dut.VECTOR_PE_COUNT, `TB_QUANT_LANES, u_dut.g_vector_engine.u_engine.WINDOW_LANES, `TB_SHARED_QUANT_ENABLE);
'''
    text = text.replace('        assert (sa_ready) else', vector_check + '        assert (sa_ready) else')
    cache_check = '''        assert (u_dut.CONV_LINE_BYTES == `TB_CONV_LINE_BYTES &&
                u_dut.CONV_CACHE_WAYS == `TB_CONV_CACHE_WAYS &&
                u_dut.CONV_CACHE_SETS == `TB_CONV_CACHE_SETS &&
                u_dut.CONV_LINE_BYTES * u_dut.CONV_CACHE_WAYS * u_dut.CONV_CACHE_SETS == `TB_IM2COL_CACHE_BYTES)
            else $fatal(1, "Cache geometry differs from the experiment");
        $display("COMMON_CACHE cache_line_bytes=%0d cache_sets=%0d cache_ways=%0d conv_cache_demand_outstanding=%0d conv_register_descriptor=%0d conv_register_cache_request=%0d",
            u_dut.CONV_LINE_BYTES, u_dut.CONV_CACHE_SETS, u_dut.CONV_CACHE_WAYS,
            u_dut.u_block_dma_arbiter.u_dma.g_im2col.u_frontend.CACHE_RESPONSE_DEPTH,
            u_dut.u_block_dma_arbiter.u_dma.g_im2col.u_frontend.REGISTER_DESCRIPTOR,
            u_dut.u_block_dma_arbiter.u_dma.g_im2col.u_frontend.REGISTER_CACHE_REQUEST);
'''
    text = text.replace('        assert (sa_ready) else', cache_check + '        assert (sa_ready) else')
    text = text.replace('        done_ready = 1;', '''        $display("COMMON_SCHEDULE ia_banks=%0d ps_control=%0d r=%0d w=%0d dataflow=%0d frame_commands=%0d pressure_events=%0d",
            cfg[62], cfg[61], cfg[6], cfg[7], cfg[8], u_dut.tb_observer.ps_stat_commands, u_dut.tb_observer.ps_stat_pressure_events);
        done_ready = 1;''')
    return text


def build(args, runner, profile):
    out = args.out / "sim"
    out.mkdir(parents=True, exist_ok=True)
    tb = out / "tb_latest_operators.sv"
    desired = testbench(args)
    if not tb.exists() or tb.read_text() != desired:
        tb.write_text(desired)
    sources, includes, tracked = runner.source_files()
    sources = [p for p in sources if p.name not in ("tb_conv_npu.sv", "ps_stream_capture.sv", "axi_memory.sv")]
    memory_source = args.reference_root / "scripts/memory_service/axi_memory.sv"
    memory_manifest = args.reference_root / "scripts/memory_service/source_manifest.json"
    memory_record = json.loads(memory_manifest.read_text())
    if digest(memory_source) != memory_record["source_sha256"]["axi_memory.sv"]:
        raise ValueError("外部 RAM 服务源码与归档记录不一致")
    sources.append(memory_source)
    tracked = [p for p in tracked if p.name != "axi_memory.sv"]
    monitor = args.repo / "test/gemmini_comparison/axi_monitor.sv"
    sources += [tb, monitor]
    primitive_models = None
    if args.fpga:
        required_models = sorted({name for path in sources
            for name in re.findall(r'\b(LUT5|LUT6|LUT6_2)\b', path.read_text())})
        if required_models:
            helper = args.repo / 'test/rtl_primitives.py'
            model, primitive_models = runpy.run_path(str(helper))['xilinx_lut_models'](
                out, required_models)
            sources.append(model)
            tracked.append(helper)
    if args.synthesis:
        monitor_root = out / 'synthesis_monitors'
        monitor_root.mkdir(exist_ok=True)
        # 生产模块使用综合表达式，观察模块继续检查协议与数据。
        for index, path in enumerate(sources):
            if path.is_relative_to(args.repo / 'test/monitors'):
                selected = monitor_root / path.name
                selected.write_text('`undef SYNTHESIS\n' + path.read_text() + '\n`define SYNTHESIS 1\n')
                sources[index] = selected
    tracked = list(dict.fromkeys([*sources, *tracked, *getattr(args, "verification_sources", ()), HERE / "storage_planner_bridge.c",
        HERE / "storage_vector_profile.py", memory_manifest, Path(__file__).resolve()]))
    hashes = {str(p): digest(p) for p in tracked}
    binary = out / "obj/Vtb_latest_operators"
    manifest_path = out / "build.json"
    # 仅在编译输入和配置完全相同时复用仿真器。
    if args.skip_build:
        recorded = json.loads(manifest_path.read_text())
        if recorded.get("source_sha256") != hashes or recorded.get("profile") != profile or recorded.get("returncode"):
            raise ValueError("Existing operator simulator differs from the requested sources or configuration")
        if not binary.is_file() or recorded.get("binary_sha256") != digest(binary):
            raise ValueError("已有仿真器的文件内容与构建记录不一致")
        return binary
    defines = ["-DGEMPACT_PS_COMPRESS=1", "-DGEMMORA_PS_FORCE_RAW=1", f"-DGEMMORA_PS_POOL_BYTES={(args.bank_count-1)*args.bank_bytes}",
        f"-DTB_VECTOR_PE_COUNT={args.pe_count}",
        f"-DTB_QUANT_LANES={profile['quantization_lanes']}", f"-DTB_WINDOW_LANES={profile['window_lanes']}",
        f"-DTB_SHARED_QUANT_ENABLE={profile['shared_quant_enable']}",
        "-DTB_SIZE=16", "-DTB_BUS_WIDTH=64", "-DTB_IA_CACHE_BLOCKS=4", "-DTB_PS_FRAME_COUNT=16",
        "-DTB_PS_STORAGE_ROWS=0", "-DTB_OA_S16_FIFO_BANKS_MAX=4",
        f"-DTB_SHARED_BANK_BYTES={args.bank_bytes}", f"-DTB_SHARED_BANK_COUNT={args.bank_count}",
        f"-DTB_IM2COL_CACHE_BYTES={args.cache_bytes}", f"-DTB_CONV_CACHE_SETS={profile['cache_sets']}",
        f"-DTB_CONV_CACHE_WAYS={profile['cache_ways']}", f"-DTB_CONV_LINE_BYTES={profile['cache_line_bytes']}",
        "-DTB_CONV_CACHE_POLICY=3", "-DTB_DMA_MAX_BYTES=2048", "-DTB_READ_BEAT_CYCLES=1",
        "-DTB_READ_FIRST_LATENCY=8", "-DTB_PIPELINED_READ=1", "-DCOMMON_WINDOWED_INPUT",
        "-DCOMMON_PREFETCH_INPUT", "-DCOMMON_MONITOR_TOP=tb_latest_operators"]
    defines += ['-D' + name + '=1' for name in profile['rtl_simulation_defines']]
    command = [args.verilator, "--binary", "--timing", "--assert", "-sv", "--top-module", "tb_latest_operators",
        "-Wno-fatal", *["-I"+str(p) for p in includes], *defines,
        "--Mdir", str(out / "obj"), "-j", str(args.jobs),
        "--output-groups", "0", "--output-split", "12000", "-CFLAGS", "-std=c++20 -O1",
        "-MAKEFLAGS", "OPT_FAST=-O1 OPT_SLOW=-O0 VK_PCH_I_FAST= VK_PCH_I_SLOW= CFG_CXXFLAGS_PCH=-E",
        *map(str, sources)]
    result = runner.command(command, out / "compile.log", timeout=1800)
    unchanged = hashes == {str(p): digest(p) for p in tracked}
    write_json(manifest_path, dict(returncode=result, source_sha256=hashes,
        sources_unchanged_during_build=unchanged, command=command, profile=profile,
        primitive_models=primitive_models))
    if result or not unchanged:
        raise RuntimeError((out / "compile.log").read_text()[-6000:])
    build_record = json.loads(manifest_path.read_text())
    build_record["binary_sha256"] = digest(binary)
    write_json(manifest_path, build_record)
    return binary


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", type=Path, required=True)
    ap.add_argument("--reference-root", type=Path, required=True,
                    help="包含共同 RAM 服务源码的归档环境根目录")
    ap.add_argument("--workloads", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=HERE / "npu_rw4")
    ap.add_argument("--verilator", default="verilator")
    ap.add_argument("--jobs", type=int, default=2)
    ap.add_argument("--bank-bytes", type=int, default=4096)
    ap.add_argument("--bank-count", type=int, default=8)
    ap.add_argument("--cache-bytes", type=int, default=4096)
    ap.add_argument("--pe-count", type=int, choices=(8, 16), default=8,
                    help="向量乘累加单元数量；实际量化及窗口并行度写入配置记录")
    ap.add_argument("--prepare-only", action="store_true")
    ap.add_argument("--skip-build", action="store_true")
    ap.add_argument("--clean-build-products", action="store_true",
                    help="运行结束后清理本次仿真对象目录中的编译中间文件")
    ap.add_argument("--synthesis", action="store_true", help="运行生产综合条件下的 RTL 表达式")
    ap.add_argument("--fpga", action="store_true", help="运行 FPGA 综合条件下的 RTL 表达式")
    ap.add_argument("--cases", nargs="+")
    ap.add_argument("--plusarg", action="append", default=[],
                    help="额外仿真参数，可重复传入；执行记录保存完整命令")
    ap.add_argument("--ar-min-interval", type=int, default=1,
                    help="外部存储相邻读地址接受的最短周期数，默认 1")
    args = ap.parse_args()
    if args.fpga and not args.synthesis:
        ap.error("FPGA 生产分支检查需要同时指定 --synthesis")
    if args.ar_min_interval < 1:
        ap.error("读地址接受间隔必须为正整数")
    if any(argument.lstrip('+').startswith('AR_MIN_INTERVAL=') for argument in args.plusarg):
        ap.error("请使用 --ar-min-interval 指定读地址接受间隔")
    args.repo, args.workloads, args.out = args.repo.resolve(), args.workloads.resolve(), args.out.resolve()
    args.reference_root = args.reference_root.resolve()
    if args.jobs < 1 or args.bank_bytes not in (2048, 4096, 8192) or args.bank_count not in (6, 7, 8, 9):
        ap.error("并行数和共享存储配置无效")
    if args.cache_bytes < 512 or args.cache_bytes > 65536 or args.cache_bytes & (args.cache_bytes - 1):
        ap.error("窗口缓存容量必须为 512 至 65536 字节范围内的二次幂")
    args.out.mkdir(parents=True, exist_ok=True)
    sys.path[:0] = [str(args.repo / "test/gemmini_comparison"), str(args.repo / "test/ps_compression")]
    import run_mini as gemm
    import run_mini_conv as conv
    from planner_profile import normalize_profile, profile_header
    runner = gemm.load_runner(args.repo)
    runner.WORDS = 524288
    profile = hardware_profile(args, normalize_profile)
    write_json(args.out / "hardware_profile.json", profile)
    lib = planner(args, args.out / "planner", profile, profile_header(profile))
    groups = {kind: prepare_group(args, kind, lib, runner, gemm, conv) for kind in ("gemm", "conv")}
    selected = {row["name"] for rows in groups.values() for row in rows}
    if not selected or args.cases and selected != set(args.cases):
        raise ValueError("Requested common cases are absent")
    write_json(args.out / "prepared.json", dict(profile=profile, groups=groups))
    if args.prepare_only:
        print(json.dumps({"prepared": len(selected), "out": str(args.out)}, indent=2))
        return 0
    try:
        binary = build(args, runner, profile)
        commit = subprocess.check_output(["git", "-C", str(args.repo), "rev-parse", "HEAD"], text=True).strip()
        all_passed = True
        for kind, rows in groups.items():
            for row in rows:
                case = Path(row["case_directory"])
                output_file = case / "canonical_output.bin"
                output_bytes = row.get("output_elements", row.get("m", 0) * row.get("n", 0))
                if output_file.exists():
                    output_file.unlink()
                command = [str(binary), "+CONFIG="+str(case/"config.mem"),
                    "+INIT="+str(case/"init.mem"), "+GOLDEN="+str(case/"golden.mem"),
                    "+NO_RANDOM_WAIT", "+NPU_UTIL_TRACE", "+NPU_UTIL_SUMMARY",
                    f"+AR_MIN_INTERVAL={args.ar_min_interval}",
                    "+OUTPUT_DUMP=" + str(output_file),
                    f"+OUTPUT_BASE={row['addresses']['c']:x}", f"+OUTPUT_BYTES={output_bytes}",
                    *["+" + argument.lstrip("+") for argument in args.plusarg]]
                returncode = runner.command(command, case / "run.log", timeout=900)
                log = (case / "run.log").read_text()
                measurement = gemm.records(log, "COMMON_OPERATOR_PASS")
                timing = gemm.records(log, "COMMON_TIMING")
                hardware = gemm.records(log, "COMMON_HARDWARE")
                actual_schedule = gemm.records(log, "COMMON_SCHEDULE")
                actual_vector = gemm.records(log, "COMMON_VECTOR")
                actual_cache = gemm.records(log, "COMMON_CACHE")
                actual_ar_interval = gemm.records(log, "COMMON_AR_INTERVAL")
                passed = returncode == 0 and len(measurement) == len(timing) == len(hardware) == len(actual_schedule) == len(actual_vector) == len(actual_cache) == len(actual_ar_interval) == 1
                if passed:
                    passed = measurement[0]["cycles"] == timing[0]["done"] and timing[0]["read_latency_min"] >= 8
                    passed = passed and hardware[0]["shared_enabled"] == 1
                    passed = passed and max(timing[0]["read_burst_bytes_max"], timing[0]["write_burst_bytes_max"]) <= 2048
                    passed = passed and actual_vector[0] == dict(pe_count=profile["vector_pe_count"],
                        quantization_lanes=profile["quantization_lanes"], window_lanes=profile["window_lanes"],
                        shared_quant_enable=profile["shared_quant_enable"])
                    passed = passed and actual_cache[0] == {key: profile[key] for key in (
                        "cache_line_bytes", "cache_sets", "cache_ways",
                        "conv_cache_demand_outstanding", "conv_register_descriptor", "conv_register_cache_request")}
                    interval = actual_ar_interval[0]
                    passed = passed and interval['required'] == args.ar_min_interval
                    passed = passed and interval['accepted'] == timing[0]['read_commands']
                    passed = passed and (interval['accepted'] < 2 or interval['minimum'] >= args.ar_min_interval)
                    passed = passed and output_file.is_file() and output_file.stat().st_size == output_bytes
                    passed = passed and digest(output_file) == row["output_sha256"]
                row.update(passed=passed, returncode=returncode, command=command)
                if passed:
                    row.update(measurement=measurement[0], timing=timing[0], observed_hardware=hardware[0],
                        observed_schedule=actual_schedule[0], observed_output_sha256=digest(output_file),
                        observed_output_file=str(output_file), observed_output_bytes=output_bytes,
                        observed_vector=actual_vector[0],
                        observed_cache=actual_cache[0],
                        observed_ar_interval=actual_ar_interval[0],
                        utilization=gemm.records(log, "[NPU_UTIL]"))
                    print(json.dumps({"case": row["name"], "passed": True, "cycles": measurement[0]["cycles"]}), flush=True)
                else:
                    all_passed = False
                    print(log[-6000:], flush=True)
                write_json(case / "result.json", row)
                if not passed:
                    break
            group = dict(passed=all(row.get("passed", False) for row in rows), source_commit=commit,
                source_repository=str(args.repo), binary_sha256=digest(binary), profile=profile,
                build_manifest_sha256=digest(args.out / "sim/build.json"),
                workload_catalogue_sha256=digest(args.workloads / kind / "workloads.json"),
                memory_service=dict(ar_min_interval=args.ar_min_interval),
                timing="Accepted launch through completed accelerator and drained AXI responses; host layout preparation excluded",
                numerical_check="Every 32-bit system-memory word equals the expected memory image after completion",
                cases=rows)
            write_json(args.out / kind / "summary.json", group)
            if not group["passed"]:
                all_passed = False
                break
        write_json(args.out / "summary.json", dict(passed=all_passed, source_commit=commit,
            profile=profile, memory_service=dict(ar_min_interval=args.ar_min_interval),
            case_count=len(selected), groups={k: str(args.out/k/"summary.json") for k in groups}))
        return 0 if all_passed else 1
    finally:
        if args.clean_build_products:
            write_json(args.out / "sim/build_cleanup.json", clean_build_products(args.out))


if __name__ == "__main__":
    raise SystemExit(main())
