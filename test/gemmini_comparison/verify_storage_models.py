#!/usr/bin/env python3
"""核验完整模型的实际二进制、输入输出、逐层计时和共同存储配置。"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import struct
import sys


MODELS = ("mnist_cnn", "mobilenet_v1_vww", "resnet8_cifar10", "ds_cnn_kws")
CPU = dict(cpu_enable_mul=1, cpu_enable_fast_mul=1, cpu_enable_div=1,
    cpu_enable_regs_dualport=1, cpu_two_stage_shift=1, cpu_barrel_shifter=1,
    cpu_two_cycle_compare=0, cpu_two_cycle_alu=0, cpu_icache=1)


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_current_source as read_rtl_text

def require(condition, message):
    if not condition:
        raise ValueError(message)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def normalized(path):
    return Path(os.path.abspath(os.path.normpath(str(path))))


class Verification:
    def __init__(self, mappings=()):
        self.mappings = []
        self.files = {}
        self.cache = {}
        for old, new in mappings:
            self.add_mapping(old, new)

    def add_mapping(self, old, new):
        self.mappings.append((normalized(old), normalized(new)))
        self.mappings.sort(key=lambda item: len(item[0].parts), reverse=True)

    def resolve(self, value, root=None):
        path = Path(value)
        if not path.is_absolute():
            require(root is not None, "A relative path needs an explicit root: " + str(path))
            path = Path(root) / path
        path = normalized(path)
        for old, new in self.mappings:
            if path.is_relative_to(old):
                return new / path.relative_to(old)
        return path

    def digest(self, path, expected=None, role="payload"):
        path = normalized(path)
        require(path.is_file(), "Required file is absent: " + str(path))
        info = path.stat()
        key = (info.st_mtime_ns, info.st_size)
        if self.cache.get(path, (None,))[0] != key:
            value = hashlib.sha256(path.read_bytes()).hexdigest()
            self.cache[path] = (key, value)
        actual = self.cache[path][1]
        if expected is not None:
            require(actual == expected, "SHA-256 differs: " + str(path))
        self.files[path] = dict(path=str(path), bytes=info.st_size, sha256=actual, role=role)
        return actual

    def read(self, path, role="record"):
        self.digest(path, role=role)
        return json.loads(read_rtl_text(Path(path)))

    def hashes(self, values, root=None, role="source"):
        for name, expected in values.items():
            self.digest(self.resolve(name, root), expected, role)

    def artifact_records(self, value):
        if isinstance(value, dict):
            if isinstance(value.get("path"), str) and isinstance(value.get("sha256"), str):
                if Path(value["path"]).is_absolute():
                    self.digest(self.resolve(value["path"]), value["sha256"])
            for item in value.values():
                self.artifact_records(item)
        elif isinstance(value, list):
            for item in value:
                self.artifact_records(item)

    def mapped_record(self, value):
        if isinstance(value, dict):
            return {key: self.mapped_record(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.mapped_record(item) for item in value]
        if isinstance(value, str) and value.startswith("/"):
            return str(self.resolve(value))
        return value


def parse_log(path):
    text = read_rtl_text(Path(path))
    groups = {}
    for prefix, key in (("SOC_NETWORK_COUNTER", "counters"),
        ("SOC_NETWORK_CPU_PROFILE", "cpu_profiles"), ("SOC_NETWORK_DMA_PROFILE", "dma_profiles"),
        ("SOC_NETWORK_WINDOW_JOB", "window_jobs")):
        rows = []
        for line in text.splitlines():
            if line.startswith(prefix + " "):
                fields = re.findall(r"(\w+)=([^\s]+)", line)
                rows.append({name: value if name == "scope" else int(value) for name, value in fields})
        groups[key] = rows
    require("SOC_NETWORK_PASS " in text and "%Error" not in text, "Simulator completion is absent: " + str(path))
    return groups


def verify_window_jobs(rows, network, profile):
    """根据构建参数独立检查日志中的窗口请求与响应守恒。"""
    lanes = profile.get('window_lanes')
    require(type(lanes) is int and lanes > 0, '构建记录必须包含有效的窗口返回并行数')
    require(profile.get('vector_window_outstanding') == 4, '窗口在途请求上限与实验配置不同')
    require(len(rows) == network['dw_jobs'] + network['pool_jobs'], '窗口任务记录数量不完整')
    require(sum(row['requests'] for row in rows) == network['dw_windows'], '窗口请求总数不同')
    for row in rows:
        counts = ('requests', 'completions', 'peak_outstanding', 'response_beats',
                  'requested_elements', 'response_elements', 'return_span_cycles',
                  'consecutive_responses', 'request_response_overlap')
        require(all(type(row[key]) is int and row[key] >= 0 for key in counts), '窗口计数必须是非负整数')
        require(row['requests'] == row['completions'], '已接受窗口请求与完成数不守恒')
        require(row['requested_elements'] == row['response_elements'], '窗口请求元素与响应元素不守恒')
        peak = row['peak_outstanding']
        require((1 <= peak <= min(4, row['requests'])) if row['requests'] else peak == 0,
                '窗口在途请求峰值超出实际容量')
        if row['operation'] == 2:
            require(row['requests'] > 0 and row['response_elements'] > 0, 'DW 窗口任务缺少实际数据传输')
        beats, elements = row['response_beats'], row['response_elements']
        require(beats <= elements <= lanes * beats, '窗口响应元素数超过实际每拍返回宽度')
        require(beats <= row['return_span_cycles'], '窗口响应拍数超过记录周期数')
        require(row['consecutive_responses'] <= max(0, beats - 1), '连续响应计数超过总响应拍数')
        require(row['request_response_overlap'] <= row['requests'], '请求与响应重叠计数超过请求总数')


def memory_words(path, bits, ram_bytes=2097152):
    words, address = {}, 0
    text = re.sub(r"/\*.*?\*/|//[^\n]*", "", read_rtl_text(Path(path)), flags=re.S)
    for token in text.split():
        if token.startswith("@"):
            address = int(token[1:], 16)
            continue
        value = int(token.replace("_", ""), 16)
        require(0 <= value < (1 << bits) and 0 <= address < ram_bytes // (bits // 8),
            "Memory image exceeds its word width or physical RAM: " + str(path))
        words[address] = value
        address += 1
    return words


def memory_bytes(words, address, count, bits=32):
    width = bits // 8
    return bytes((words.get((address + i) // width, 0) >> (8 * ((address + i) % width))) & 255
        for i in range(count))


def elf_symbols(path, requested):
    raw = Path(path).read_bytes()
    require(raw[:7] == b"\x7fELF\x01\x01\x01" and struct.unpack_from("<H", raw, 18)[0] == 243,
        "Firmware must be a little-endian RISC-V ELF32 file")
    offset = struct.unpack_from("<I", raw, 32)[0]
    stride, count = struct.unpack_from("<HH", raw, 46)
    sections = [struct.unpack_from("<10I", raw, offset + i * stride) for i in range(count)]
    result = {}
    for section in sections:
        if section[1] != 2:
            continue
        strings = sections[section[6]]
        names = raw[strings[4]:strings[4] + strings[5]]
        for pos in range(section[4], section[4] + section[5], section[9]):
            name, value, size, _, _, _ = struct.unpack_from("<IIIBBH", raw, pos)
            label = names[name:names.find(b"\0", name)].decode()
            if label in requested:
                result[label] = (value, size)
    require(set(result) == set(requested), "Required firmware symbols are absent")
    return result


def verify_gemmini_artifacts(v, build, repo):
    config = build["configuration"]
    expected = dict(array_rows=16, array_columns=16, scratchpad_bytes=32768, accumulator_bytes=32768,
        dma_bus_bits=64, dma_max_bytes=2048, dma_outstanding_per_direction=4, axi_max_beats=256,
        axi_boundary_bytes=4096, spad_read_delay=1, has_im2col=True, has_dwconv_dataflow=True)
    for key, value in expected.items():
        require(config.get(key) == value, "Gemmini accelerator parameter differs: " + key)
    for key in ("generated_rtl", "generated_configuration", "params_header"):
        v.digest(v.resolve(build[key]), build[key + "_sha256"], "generated_hardware")
    harness = repo / "test/gemmini_comparison/gemmini_dw_rtl"
    if build.get("external_memory_service_sources"):
        v.hashes({name: checksum for name, checksum in build["harness_sha256"].items()
                  if name != "sim/run_compare.cpp"}, harness)
        v.hashes(build["external_memory_service_sources"])
    else:
        v.hashes(build["harness_sha256"], harness)
    pinned = v.read(harness / "dependencies.json")["repositories"]
    for name, record in pinned.items():
        require(all(build["repositories"][name][key] == record[key] for key in ("commit", "url")),
            "Gemmini dependency revision differs: " + name)
    for adaptation in build["source_adaptations"]:
        for key in ("patch", "compiled_source"):
            v.digest(v.resolve(adaptation[key]), adaptation[key + "_sha256"], "hardware_adaptation")
        original = v.resolve(build["repositories"]["gemmini"]["path"]) / adaptation["source"]
        v.digest(original, adaptation["source_sha256"], "original_hardware_source")


def verify_model_build(v, build, repo, gemmini):
    require(build["returncode"] == 0 and build["sources_unchanged_during_build"], "Simulator build is incomplete")
    profile = build["profile"]
    expected = dict(CPU, cpu_profile="performance", cpu="PicoRV32", cpu_isa="RV32IM",
        cpu_icache_data_bytes=1024, ram_words=524288, bus_width=64, dma_max_bytes=2048,
        cpu_axi_data_bits=32, ram_read_first_latency=8, ram_read_latency_origin="accepted_AR",
        ram_continuous_read_beat_cycles=1, cpu_axi_read_timing_buffer=1, cpu_axi_write_timing_buffer=1,
        npu_axi_timing_buffer=1, bypass_ram_pingpong=1, ram_write_timing_buffer=1)
    for key, value in expected.items():
        require(profile.get(key) == value, "Simulator profile differs: " + key)
    if gemmini:
        verify_gemmini_artifacts(v, build["gemmini_build"], repo)
        tb = repo / "test/gemmini_comparison/model_runtime/rtl/tb_gemmini_model.sv"
    else:
        for key, value in dict(core="unified", shared_ia_ps=True, size=16,
            shared_bank_bytes=4096, shared_bank_count=8, shared_total_bytes=32768,
            ps_pool_bytes=28672, ps_compress=True, ia_cache_blocks=4, ps_frame_count=16,
            axi_read_outstanding=4, axi_write_outstanding=4,
            vector_line_cache_bytes=0, vector_window_outstanding=4,
            conv_cache_policy="windowed", rounding_mode="nearest_even").items():
            require(profile.get(key) == value, "Shared NPU profile differs: " + key)
        # 缓存容量由实际构建参数确定，随后与容量展开及总存储上限一并核对。
        require(type(profile.get("im2col_cache_bytes")) is int and profile["im2col_cache_bytes"] > 0,
                "NPU 输入缓存容量必须为正整数")
        tb = repo / "test/model_benchmark/tb_model_benchmark.sv"
    v.hashes(build["source_sha256"], repo)
    v.hashes(build.get("external_dependency_sha256", {}), repo)
    source = re.sub(r"/\*.*?\*/|//[^\n]*", "", read_rtl_text(tb), flags=re.S)
    require(any(v.resolve(path, repo) == tb for path in build["source_sha256"]), "Testbench is absent from the build sources")
    for pattern, description in (
        (r"\.CPU_MEM_WORD_WIDTH\s*\(\s*`SOC_NETWORK_BUS_WIDTH\s*\)", "RAM image word width"),
        (r"\.AXI_READ_OUTSTANDING\s*\(\s*4\s*\)", "read outstanding"),
        (r"\.AXI_WRITE_OUTSTANDING\s*\(\s*4\s*\)", "write outstanding")):
        require(re.search(pattern, source), "Testbench parameter differs: " + description)
    command = build["command"]
    require("--assert" in command, "RTL assertions were not compiled")
    macros = dict(re.findall(r"^\s*`define\s+(\w+)\s+(\d+)\s*$", source, re.M))
    for item in command:
        match = re.fullmatch(r"-D(\w+)(?:=(\d+))?", item)
        if match:
            macros[match[1]] = match[2] or "1"
    for name, value in dict(SOC_NETWORK_BUS_WIDTH=64, SOC_NETWORK_RAM_WORDS=524288,
        SOC_NETWORK_DMA_MAX_BYTES=2048, SOC_NETWORK_READ_FIRST_LATENCY=8,
        **{"SOC_NETWORK_" + key.upper(): value for key, value in CPU.items() if key != "cpu_icache"},
        SOC_NETWORK_ICACHE=1).items():
        require(macros.get(name) == str(value), "Compiled testbench macro differs: " + name)


def verify_complete_models(repo, npu, gemmini_sim, variants, prepared=None, *,
        path_mappings=None, data_root=None, tool_root=None, platforms=None, models=None, samples=(0, 1),
        npu_capacity=None, gemmini_capacity=None, include_software=False):
    """逐项重读运行文件，核对普通推理与逐层记录的实际内容。"""
    repo, npu, gemmini_sim = map(normalized, (repo, npu, gemmini_sim))
    available = (*(("software",) if include_software else ()), "npu", *variants)
    platforms, models, samples = tuple(platforms or available), tuple(models or MODELS), tuple(samples)
    require(set(platforms) <= set(available) and platforms, "Invalid platform selection")
    require(set(models) <= set(MODELS) and models, "Invalid model selection")
    require(set(samples) <= {0, 1} and samples, "Invalid input selection")
    mappings = list(path_mappings.items() if isinstance(path_mappings, dict) else path_mappings or ())
    v = Verification(mappings)
    v.digest(Path(__file__), role="verification_program")
    settings = v.read(npu / "settings_hw_perf_trace.json")
    old_npu = normalized(settings["arguments"]["out"])
    v.add_mapping(settings["repo"], repo)
    v.add_mapping(old_npu, npu)
    v.add_mapping(old_npu.parent, data_root or npu.parent)
    if prepared is not None:
        v.add_mapping(settings["arguments"]["prepared"], prepared)
    if tool_root is not None:
        old_gcc = normalized(settings["arguments"]["gcc"]).parents[1]
        v.add_mapping(old_gcc, normalized(tool_root) / old_gcc.name)
    # 同一前缀采用显式给出的路径映射。
    for old, new in mappings:
        old = normalized(old)
        v.mappings = [(a, b) for a, b in v.mappings if a != old]
        v.add_mapping(old, new)
    builds = {"npu": v.read(npu / "sim/build.json"), "gemmini": v.read(gemmini_sim / "build.json")}
    for key, build in builds.items():
        verify_model_build(v, build, repo, key == "gemmini")
    require(builds["npu"]["picorv32_commit"] == builds["gemmini"]["picorv32_commit"], "Pico source revisions differ")
    require(settings["arguments"]["arena_bytes"] == 512 * 1024, "NPU reserved arena differs")
    directories = {name: normalized(record["directory"]) for name, record in variants.items()}
    firmware_cache, prepared_cache, memory_cache = {}, {}, {}
    observations, tensor_count = [], 0
    for model in models:
        for sample in samples:
            identities = set()
            for platform in platforms:
                gemmini = platform in variants
                policy = variants[platform]["policy"] if gemmini else None
                firmware_repo = normalized(variants[platform]["source"]) if gemmini else repo
                mode = 0 if platform == "software" else 63
                build = builds["gemmini" if gemmini else "npu"]
                reserved = 512 * 1024
                for kind in (("perf",) if platform == "software" else ("perf", "trace")):
                    directory = (directories[platform] / model / f"{sample:04d}" / kind if gemmini else
                        npu / "results/cases" / model / f"sample_{sample:04d}" / f"{kind}_{mode}")
                    run, case = (v.read(directory / name) for name in ("result.json", "case.json"))
                    require(run["passed"] and all(run["checks"].values()), "A saved model run did not pass: " + str(directory))
                    if not gemmini:
                        parser_path = 'test/model_benchmark/run.py'
                        require(run.get('validation_source_sha256', {}).get(parser_path) ==
                                v.digest(repo / parser_path, role='result_parser'), 'NPU 结果解析器来源不匹配')
                        v.hashes(run['validation_source_sha256'], repo, 'result_parser')
                        require(run.get('window_response_lanes') == build['profile'].get('window_lanes'),
                                'NPU 结果记录使用的窗口并行数与实际构建不同')
                    for record in (run, case):
                        require((record["model_id"], record["sample_index"], record["kind"], record["mode"]) ==
                            (model, sample, kind, mode), "Run identity differs: " + str(directory))
                    require(run["ram_fixed_lat"] == 0, "Unexpected fixed-latency override")
                    if gemmini:
                        require(run["convolution_policy"] == case["convolution_policy"] == policy, "Gemmini policy differs")
                    sim = run["simulator"]
                    v.digest(v.resolve(sim["command"][0]), build["binary_sha256"], "simulator")
                    require(sim["simulator_sha256"] == build["binary_sha256"], "Run simulator differs from its build")
                    require(sim["passed"] and sim["returncode"] == 0, "Simulator execution did not complete")
                    require("+RAM_READ_FIRST_LATENCY=8" in sim["command"] and "+RAM_FIXED_LAT=0" in sim["command"],
                        "Actual simulator memory options differ")
                    plusargs = dict(item[1:].split("=", 1) for item in sim["command"][1:] if item.startswith("+") and "=" in item)
                    for key, filename in (("SOC_CPU_MEM", "memory_axi64.mem"), ("RESULT_FILE", "result.bin"),
                        ("OUTPUT_FILE", "output.bin"), ("MODEL_FILE", "model_after.bin"), ("INPUT_FILE", "input_after.bin")):
                        require(v.resolve(plusargs[key]) == directory / filename, "Simulator command path differs: " + key)
                    for key, field in (("MODEL_ADDR", "model_address"), ("INPUT_ADDR", "input_address")):
                        require(int(plusargs[key], 16) == case["config"][field], "Simulator payload address differs: " + key)
                    fw_dir = v.resolve(case["firmware_dir"])
                    if fw_dir not in firmware_cache:
                        fw = v.read(fw_dir / "firmware.json")
                        require(fw["passed"] and fw["returncode"] == 0 and fw["sources_unchanged_during_build"], "Firmware build did not pass")
                        v.hashes(fw["source_sha256"], firmware_repo)
                        v.hashes(fw["external_dependency_sha256"], firmware_repo)
                        v.hashes(fw["runtime_libraries"], firmware_repo, "runtime_library")
                        v.digest(v.resolve(fw["compiler"]), fw["compiler_sha256"], "compiler")
                        for filename, key in (("cpu.elf", "elf_sha256"), ("cpu.mem", "mem_sha256"), ("cpu.bin", "binary_sha256")):
                            v.digest(fw_dir / filename, fw[key], "firmware")
                        symbols = elf_symbols(fw_dir / "cpu.elf", ("full_network_arena", "full_network_result"))
                        require(symbols["full_network_arena"] == (fw["arena_address"], reserved), "ELF arena differs from its reservation")
                        require(symbols["full_network_result"][0] == fw["symbols"]["full_network_result"], "ELF result address differs")
                        require(fw["arena_bytes"] == fw["symbol_sizes"]["full_network_arena"] == reserved and
                            fw["arena_end"] == fw["arena_address"] + reserved and fw["arena_end"] <= 2097152 and
                            fw["ram_bytes"] == 2097152, "Firmware arena or physical memory size differs")
                        firmware_cache[fw_dir] = fw
                    fw = firmware_cache[fw_dir]
                    require(fw["arena_bytes"] == reserved and fw["trace_enabled"] == (kind == "trace"), "Firmware measurement mode differs")
                    require(mode in fw["supported_modes"] and fw["hardware"] == (platform != "software"), "Firmware acceleration mode differs")
                    require(int(plusargs["RESULT_ADDR"], 16) == fw["symbols"]["full_network_result"] and
                        int(plusargs["RESULT_WORDS"]) == len(fw["result_fields"]), "Simulator firmware-result address differs")
                    require(fw["elf_sha256"] == case["firmware_elf_sha256"] == run["firmware_elf_sha256"] and
                        fw["mem_sha256"] == sim["firmware_memory_sha256"], "Run firmware identity differs")
                    if gemmini:
                        require(fw["convolution_policy"] == policy, "Firmware Gemmini policy differs")
                    model_dir = v.resolve(case["prepared_dir"])
                    v.digest(model_dir / "manifest.json", case["prepared_sha256"], "prepared_manifest")
                    if model_dir not in prepared_cache:
                        prepared_cache[model_dir] = v.read(model_dir / "manifest.json")
                    manifest = prepared_cache[model_dir]
                    require(case["model"] == manifest["model"] == run["model"], "Prepared model identity differs")
                    expected_sample = next(item for item in manifest["samples"] if item["sample_index"] == sample)
                    require(case["sample"] == expected_sample, "Prepared sample descriptors differ")
                    for payload in [manifest["model"], expected_sample["input"], expected_sample["output"], *expected_sample["nodes"]]:
                        path = model_dir / payload["path"]
                        v.digest(path, payload["sha256"], "reference_payload")
                        require(path.stat().st_size == payload["bytes"], "Reference payload length differs")
                    expected_output = expected_sample["output"]["sha256"]
                    require(run["input_sha256"] == expected_sample["input"]["sha256"], "Run input differs")
                    identities.add((run["model"]["sha256"], run["input_sha256"], expected_output))
                    for filename, expected in (("model_after.bin", run["model"]["sha256"]),
                        ("input_after.bin", run["input_sha256"]), ("output.bin", expected_output)):
                        v.digest(directory / filename, expected, "observed_payload")
                    require(run["output_comparison"]["actual_sha256"] == run["output_comparison"]["expected_sha256"] ==
                        sim["output_sha256"] == expected_output, "Recorded output differs from the actual payload")
                    v.digest(directory / "result.bin", sim["result_sha256"], "firmware_result")
                    raw_result = (directory / "result.bin").read_bytes()
                    require(len(raw_result) == 4 * len(fw["result_fields"]), "Firmware result length differs")
                    words = list(struct.unpack("<" + "I" * len(fw["result_fields"]), raw_result))
                    result = dict(zip(fw["result_fields"], words))
                    require(result == run["result"] and words == sim["result_words"], "Firmware result fields differ from result.bin")
                    require(result["complete"] == 1 and result["status"] == result["error"] == result["mismatches"] == 0,
                        "Firmware did not complete exact inference")
                    require(0 < result["arena_used_bytes"] <= reserved, "Arena use exceeds the compiled reservation")
                    require(result["invoke_cycles"] == ((result["end_cycle"] - result["start_cycle"]) & 0xffffffff) > 0,
                        "Invoke cycle interval differs")
                    require(result["operator_count"] == len(manifest["graph"]["nodes"]) and
                        result["trace_enabled"] == (kind == "trace"), "Graph count or trace mode differs")
                    v.digest(directory / "data.mem", case["data_mem_sha256"], "simulator_input")
                    require(case["data_mem_sha256"] == sim["data_memory_sha256"], "Data image differs from the run")
                    packed = sim["packed_memory"]
                    require(packed["word_bits"] == 64 and v.resolve(packed["path"]) == directory / "memory_axi64.mem",
                        "RAM image path or word width differs")
                    v.digest(directory / "memory_axi64.mem", packed["sha256"], "simulator_input")
                    if fw_dir not in memory_cache:
                        memory_cache[fw_dir] = memory_words(fw_dir / "cpu.mem", 32)
                    data = memory_words(directory / "data.mem", 32)
                    config_words = memory_bytes(data, 0x001e0000, 4 * len(fw["config_fields"]))
                    require(list(struct.unpack("<" + "I" * len(fw["config_fields"]), config_words)) ==
                        [case["config"][key] for key in fw["config_fields"]], "Initial RAM configuration differs")
                    merged = dict(memory_cache[fw_dir]); merged.update(data)
                    rows = {}
                    for address, word in merged.items():
                        index = address // 2
                        rows[index] = rows.get(index, 0) | (word << (32 * (address % 2)))
                    require(rows == memory_words(directory / "memory_axi64.mem", 64), "Packed AXI64 RAM image differs from firmware and data")
                    for field, payload in (("model", manifest["model"]), ("input", expected_sample["input"]),
                        ("golden", expected_sample["output"])):
                        actual = memory_bytes(data, case["config"][field + "_address"], payload["bytes"])
                        require(hashlib.sha256(actual).hexdigest() == payload["sha256"], "Initial RAM payload differs: " + field)
                    v.digest(directory / "run.log", run.get("run_log_sha256"), "simulation_log")
                    parsed = parse_log(directory / "run.log")
                    for key, value in parsed.items():
                        require(value == sim[key], "Saved simulator log fields differ: " + key)
                    require(parsed["cpu_profiles"] == [CPU], "Observed CPU does not use the performance configuration")
                    require(len(parsed["dma_profiles"]) == 1, "Expected one observed DMA profile")
                    dma = parsed["dma_profiles"][0]
                    require(dma["read_first_latency"] == 8 and dma["observed_ram_first_min"] >= 8 and
                        dma["bus_width"] == 64 and dma["dma_max_bytes"] == 2048 and
                        max(dma["max_read_burst_bytes"], dma["max_write_burst_bytes"]) <= 2048,
                        "Observed DMA bus width, latency or burst limit differs")
                    network = [item for item in parsed["counters"] if item["scope"] == "network"]
                    require(network == [run["network"]], "Network counters differ from the saved log")
                    require(network[0]["axi_errors"] == network[0]["npu_errors"] == 0, "Hardware errors were recorded")
                    if not gemmini:
                        verify_window_jobs(parsed['window_jobs'], network[0], build['profile'])
                    if platform == "software":
                        require(network[0]["npu_busy_cycles"] == network[0]["npu_read_bytes"] == network[0]["npu_write_bytes"] == 0,
                            "Software run issued accelerator work")
                    if kind == "trace":
                        require(v.resolve(plusargs["TRACE_DIR"]) == directory / "tensors" and
                            v.resolve(plusargs["TRACE_FILE"]) == directory / "trace.txt" and
                            int(plusargs["TRACE_ADDR"], 16) == fw["symbols"]["full_network_trace"], "Simulator trace addresses differ")
                        v.digest(directory / "trace.txt", role="trace_descriptors")
                        lines = read_rtl_text(directory / "trace.txt").splitlines()
                        require(len(lines) == len(run["trace"]) == len(expected_sample["nodes"]) == result["trace_records"],
                            "Intermediate tensor count differs")
                        for ordinal, (line, observation, reference) in enumerate(zip(lines, run["trace"], expected_sample["nodes"])):
                            desc = dict(zip(fw["trace_fields"], [int(word, 16) for word in line.split()], strict=True))
                            require(desc == observation["descriptor"] and desc["ordinal"] == ordinal and
                                desc["operator_index"] == reference["index"] and desc["output_index"] == reference["output_index"] and
                                desc["tensor_index"] == reference["tensor_index"] and desc["bytes"] == reference["bytes"],
                                "Intermediate tensor descriptor differs")
                            require(fw["arena_address"] <= desc["address"] and desc["address"] + desc["bytes"] <= fw["arena_end"],
                                "Intermediate tensor exceeds the arena")
                            v.digest(directory / f"tensors/tensor_{ordinal}.bin", reference["sha256"], "observed_intermediate_tensor")
                            require(observation["comparison"]["actual_sha256"] == observation["comparison"]["expected_sha256"] == reference["sha256"],
                                "Intermediate tensor checksum differs")
                            tensor_count += 1
                        counters = [item for item in parsed["counters"] if item["scope"] == "layer"]
                        require(len(counters) == len(run["layers"]) == len(manifest["graph"]["nodes"]), "Layer count differs")
                        for counter, layer, node in zip(counters, run["layers"], manifest["graph"]["nodes"]):
                            require(counter["index"] == layer["index"] == node["index"] and
                                all(layer.get(key) == value for key, value in counter.items()), "Layer counters differ from the simulator log")
                    else:
                        require(result["trace_records"] == 0 and not (directory / "trace.txt").exists(), "Ordinary inference includes tensor tracing")
                    observations.append(dict(platform=platform, model=model, sample=sample, kind=kind,
                        invoke_cycles=result["invoke_cycles"], arena_reserved_bytes=reserved, arena_used_bytes=result["arena_used_bytes"]))
            require(len(identities) == 1, "Compared platforms use different models or input tensors")
    complete = set(platforms) == set(available) and set(models) == set(MODELS) and set(samples) == {0, 1}
    expected_runs = sum(1 if name == "software" else 2 for name in platforms) * len(models) * len(samples)
    require(len(observations) == expected_runs, "Measured run count differs from the requested suite")
    require(npu_capacity is not None and gemmini_capacity is not None, "需要两侧的实际容量统计")
    npu_state = v.read(npu_capacity)
    gemmini_state = v.read(gemmini_capacity)
    require(npu_state["passed"] and npu_state["capabilities_match"] and npu_state["sources_unchanged"] and
            npu_state["elaboration_target"] == "generic", "NPU 容量统计必须使用实际仿真的通用结构")
    require(gemmini_state["passed"], "Gemmini 容量统计尚未通过")
    npu_bits = npu_state["elaborated_state"]["total_bits"]
    gemmini_bits = gemmini_state["state"]["total_bits"]
    require(type(npu_bits) is int and type(gemmini_bits) is int and
            0 < npu_bits <= 81920 * 8 and 0 < gemmini_bits <= 81920 * 8, "容量超过 80 KiB")
    profile = builds["npu"]["profile"]
    for parameter, field in (("SIZE", "size"), ("IA_CACHE_BLOCKS", "ia_cache_blocks"),
            ("PS_FRAME_COUNT", "ps_frame_count"), ("SHARED_BANK_BYTES", "shared_bank_bytes"),
            ("SHARED_BANK_COUNT", "shared_bank_count"), ("PS_POOL_BYTES", "ps_pool_bytes"),
            ("IM2COL_CACHE_BYTES", "im2col_cache_bytes"), ("NPU_AXI_DATA_WIDTH", "bus_width")):
        require(npu_state["hardware_configuration"][parameter] == profile[field],
                "NPU 模型与容量参数不一致：" + parameter)
    require(bool(npu_state["hardware_configuration"]["PS_FORCE_RAW"]) == profile["force_raw"],
            "NPU 部分和存储格式与容量统计不同")
    for filename, checksum in builds["npu"]["source_sha256"].items():
        if filename.startswith("rtl/npu/"):
            require(npu_state["source_sha256"].get(filename) == checksum,
                    "NPU 容量与模型仿真使用不同 RTL：" + filename)
    from check_layer_speedup import verify_vector_resources, verify_cache_resources
    vector = verify_vector_resources(profile, npu_state)
    cache = verify_cache_resources(profile, npu_state)
    gem_rtl = builds["gemmini"]["gemmini_build"]["generated_rtl_sha256"]
    require([value for path, value in gemmini_state["source_sha256"].items()
             if Path(path).name == "GemminiCompare.v"] == [gem_rtl], "Gemmini 容量与模型使用不同 RTL")
    common = ("pico_native_to_axi.sv", "soc_axi_interconnect.sv", "soc_axi_pingpong_buffer.sv",
              "soc_axi_ram.sv", "soc_axil_ctrl.sv", "soc_axil_simpleuart.sv", "sim_main.cpp")
    for filename in common:
        npu_values = [value for path, value in builds["npu"]["source_sha256"].items()
                      if Path(path).name == filename]
        gem_values = [value for path, value in builds["gemmini"]["source_sha256"].items()
                      if Path(path).name == filename]
        require(len(npu_values) == len(gem_values) == 1 and npu_values == gem_values,
                "两侧 CPU 适配或外部存储实现不同：" + filename)
    capacity = dict(passed=True, budget_bytes=81920, npu_total_bits=npu_bits,
                    gemmini_total_bits=gemmini_bits, vector_resources=vector, cache_resources=cache)
    return dict(passed=True, complete_suite=complete, expected_runs=expected_runs,
        checked_runs=len(observations), checked_intermediate_tensors=tensor_count,
        physical_ram_bytes=2097152, reserved_arena_bytes={name: 524288 for name in platforms}, capacity=capacity,
        actual_binary_and_payload_hashes=True, actual_firmware_symbols=True, actual_ram_image_contents=True,
        actual_log_counters=True, source_files_unchanged=True, tb_ram_image_word_bits=64,
        axi_read_outstanding=4, axi_write_outstanding=4, first_read_latency_cycles=8,
        performance_target_is_separate=True, runs=observations, verified_file_count=len(v.files),
        files=sorted(v.files.values(), key=lambda row: row["path"]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--npu", type=Path, required=True)
    parser.add_argument("--gemmini-sim", type=Path, required=True)
    parser.add_argument("--gemmini-variant", action="append", default=[], metavar="NAME=DIRECTORY=SOURCE=POLICY")
    parser.add_argument("--prepared", type=Path)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--map", action="append", default=[], metavar="OLD=NEW")
    parser.add_argument("--platforms", nargs="+")
    parser.add_argument("--models", nargs="+")
    parser.add_argument("--npu-capacity", type=Path, required=True)
    parser.add_argument("--gemmini-capacity", type=Path, required=True)
    parser.add_argument("--include-software", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    variants = {}
    for value in args.gemmini_variant:
        name, directory, source, policy = value.split("=", 3)
        require(name not in variants and name not in ("software", "npu"), "Duplicate platform name")
        variants[name] = dict(directory=directory, source=source, policy=policy)
    mappings = [value.split("=", 1) for value in args.map]
    result = verify_complete_models(args.repo, args.npu, args.gemmini_sim, variants, args.prepared,
        path_mappings=mappings, data_root=args.data_root, platforms=args.platforms, models=args.models,
        npu_capacity=args.npu_capacity, gemmini_capacity=args.gemmini_capacity, include_software=args.include_software)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in ("passed", "complete_suite", "expected_runs",
        "checked_runs", "checked_intermediate_tensors", "verified_file_count")}))


if __name__ == "__main__":
    main()
