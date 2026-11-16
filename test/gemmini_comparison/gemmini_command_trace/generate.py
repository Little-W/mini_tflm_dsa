#!/usr/bin/env python3
"""Generate hardware command inputs with the official Gemmini C scheduler."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

HERE = Path(__file__).resolve().parent


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n")


def git_revision(directory: Path) -> str | None:
    result = subprocess.run(["git", "-C", str(directory), "rev-parse", "HEAD"],
                            text=True, capture_output=True)
    return result.stdout.strip() if result.returncode == 0 else None


def build(out: Path, tests: Path, params: Path, params_origin: str, cc: str) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    stage = out / "include_root"
    (stage / "include").mkdir(parents=True, exist_ok=True)
    (stage / "rocc-software/src").mkdir(parents=True, exist_ok=True)
    source = tests / "include/gemmini.h"
    original = source.read_text()
    fence = '#define gemmini_fence() asm volatile("fence")'
    if original.count(fence) != 1:
        raise ValueError("Expected exactly one official fence assembler definition")
    adapted = original.replace(fence, "#define gemmini_fence() gemmini_trace_fence()")
    (stage / "include/gemmini.h").write_text(adapted)
    shutil.copyfile(tests / "include/gemmini_counter.h", stage / "include/gemmini_counter.h")
    shutil.copyfile(params, stage / "include/gemmini_params.h")
    shutil.copyfile(HERE / "xcustom.h", stage / "rocc-software/src/xcustom.h")
    binary = out / "trace_generator"
    command = [cc, "-std=gnu11", "-O2", "-fwrapv", "-DGEMMINI_ASSERTIONS", "-Wall", "-Wextra",
               "-Wno-unused-function", "-Wno-unused-variable", "-Wno-unused-parameter",
               "-fsanitize=undefined", "-fno-sanitize-recover=all", "-I", str(stage),
               str(HERE / "trace.c"), "-lm", "-o", str(binary)]
    result = subprocess.run(command, text=True, capture_output=True)
    (out / "build.log").write_text(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError(result.stderr)
    config = json.loads(subprocess.check_output([str(binary), "--describe"], text=True))
    record = {"official_tests_path": str(tests), "official_tests_revision": git_revision(tests),
              "official_gemmini_h_sha256": digest(source),
              "adapted_gemmini_h_sha256": digest(stage / "include/gemmini.h"),
              "adaptation": "Only the fence assembler macro is replaced; xcustom.h records the original RoCC operands",
              "params_header_path": str(params), "params_header_sha256": digest(params),
              "params_origin": params_origin, "config": config,
              "compiler": subprocess.check_output([cc, "--version"], text=True).splitlines()[0],
              "build_command": command, "binary": str(binary), "binary_sha256": digest(binary),
              "trace_c_sha256": digest(HERE / "trace.c"),
              "xcustom_h_sha256": digest(HERE / "xcustom.h")}
    write_json(out / "build.json", record)
    return record


def verified_tensor(directory: Path, spec: dict) -> bytes:
    path = directory / spec["path"]
    data = path.read_bytes()
    if len(data) != spec["bytes"] or digest(path) != spec["sha256"]:
        raise ValueError("Tensor differs from its workload manifest: " + str(path))
    return data


def read_trace(path: Path) -> list:
    records = []
    for line in path.read_text().splitlines():
        if line == "FENCE":
            records.append({"fence": True})
            continue
        fields = line.split()
        if len(fields) != 3:
            raise ValueError("Invalid command record: " + line)
        funct, rs1, rs2 = (int(field, 0) for field in fields)
        if funct not in range(128) or not 0 <= rs1 < 2**64 or not 0 <= rs2 < 2**64:
            raise ValueError("Command operand exceeds its hardware field")
        records.append({"funct": funct, "rs1": rs1, "rs2": rs2})
    return records


def validate_trace(records: list, case: dict, layout: dict, flow: str, config: dict) -> dict:
    if records[:2] != [{"funct": 7, "rs1": 0, "rs2": 0}, {"fence": True}]:
        raise ValueError("Expected flush and fence before the timed command region")
    if not records[-1].get("fence"):
        raise ValueError("Trace must end with a completion fence")
    counts = Counter(record["funct"] for record in records if "funct" in record)
    if not counts.get(0) or not (counts.get(8) or counts.get(4) or counts.get(5) or counts.get(15)):
        raise ValueError("Official scheduler did not emit a hardware compute command")
    if case.get("operation") in ("conv", "dw"):
        launches = [record for record in records if record.get("funct") == 15]
        depthwise = case["operation"] == "dw"
        if not launches or any(bool(record["rs1"] & (1 << 6)) != depthwise for record in launches):
            raise ValueError("Convolution launch has an incorrect depthwise mode")
    canonical = False
    if (flow == "ws" and case.get("operation", "matmul") == "matmul" and
            case["m"] == case["n"] == case["k"] == config["dim"]):
        by_function = {record["funct"]: record for record in records if "funct" in record}
        if counts[8] != 1 or counts[9] != 1:
            raise ValueError("A single full array tile must produce one LOOP_WS command")
        wanted = {
            9: (0, (1 << 32) | (1 << 16) | 1),
            10: (layout["a"]["address"], layout["b"]["address"]),
            11: (layout["bias"]["address"], layout["output"]["address"]),
            12: (case["k"], case["n"]),
            13: (0, case["n"]),
        }
        for funct, operands in wanted.items():
            actual = by_function[funct]
            if (actual["rs1"], actual["rs2"]) != operands:
                raise ValueError(f"Canonical tile differs at function {funct}")
        canonical = True
    return {"command_format_passed": True, "canonical_full_tile_checked": canonical,
            "funct_histogram": {str(key): value for key, value in sorted(counts.items())}}


def generate_case(out: Path, directory: Path, record: dict, build_record: dict,
                  base: int, flow: str, tile: tuple[int, int, int] | None = None,
                  transpose: str = "none", tensor_alignment: int = 64) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    if record.get("scale") != 0.03125 or any(record.get("zero_points", {}).values()):
        raise ValueError("Common arithmetic requires zero points 0 and exact scale 1/32")
    tensors = record["tensors"]
    payload = {name: verified_tensor(directory, tensors[name]) for name in ("a", "b", "bias", "c_s8")}
    operation = record.get("operation", "matmul")
    if operation == "matmul":
        expected_lengths = {"a": record["m"] * record["k"],
                            "b": record["k"] * record["n"],
                            "bias": record["n"] * 4,
                            "c_s8": record["m"] * record["n"]}
        if {name: len(data) for name, data in payload.items()} != expected_lengths:
            raise ValueError("Matrix dimensions and tensor lengths differ")
    elif operation in ("conv", "dw"):
        conv = record["conv"]
        if flow != "ws":
            raise ValueError("Official convolution hardware scheduling requires WS")
        expected_lengths = {
            "a": conv["batch"] * conv["input_h"] * conv["input_w"] * conv["input_channels"],
            "b": conv["kernel"] ** 2 * conv["input_channels"] *
                 (1 if operation == "dw" else conv["output_channels"]),
            "bias": conv["output_channels"] * 4,
            "c_s8": conv["batch"] * conv["output_h"] * conv["output_w"] * conv["output_channels"],
        }
        if {name: len(data) for name, data in payload.items()} != expected_lengths:
            raise ValueError("Convolution dimensions and tensor lengths differ")
        if operation == "dw" and (conv["input_channels"] != conv["output_channels"] or
                                 conv["input_dilation"] != 1 or conv["kernel_dilation"] != 1):
            raise ValueError("Depthwise convolution requires equal channels and dilation 1")
    else:
        raise ValueError("Unsupported operation: " + operation)
    if transpose != "none":
        if operation != "matmul" or flow != "ws" or transpose not in ("a", "b"):
            raise ValueError("Transposed storage requires a WS matrix workload")
        key, rows, columns = (("a", record["m"], record["k"]) if transpose == "a" else
                              ("b", record["k"], record["n"]))
        original = payload[key]
        payload[key] = bytes(original[row * columns + column]
                             for column in range(columns) for row in range(rows))
    if tensor_alignment < 64 or tensor_alignment & (tensor_alignment - 1):
        raise ValueError("Tensor alignment must be a power of two of at least 64 bytes")
    data = bytearray()
    layout = {}
    for name in ("a", "b", "bias", "output"):
        offset = ((base + len(data) + tensor_alignment - 1) // tensor_alignment * tensor_alignment) - base
        data.extend(bytes([0xA5]) * (offset - len(data)))
        contents = payload[name] if name != "output" else bytes([0x55]) * len(payload["c_s8"])
        layout[name] = {"address": base + offset, "offset": offset,
                        "bytes": len(contents), "initial_sha256": hashlib.sha256(contents).hexdigest()}
        data.extend(contents)
        data.extend(bytes([0xA5]) * 64)
    if base <= 0 or base + len(data) >= 2**32:
        raise ValueError("Memory image exceeds the shared 32-bit physical address range")
    (out / "memory.bin").write_bytes(data)
    (out / "expected_s8.bin").write_bytes(payload["c_s8"])
    command = [build_record["binary"], "--operation", operation, "--flow", flow,
               "--memory", str(out / "memory.bin"), "--commands", str(out / "commands.txt"),
               "--metadata", str(out / "emission.json"), "--base", str(base)]
    for flag, name in (("a", "a"), ("b", "b"), ("d", "bias"), ("c", "output")):
        command += ["--" + flag, str(layout[name]["address"])]
    if operation == "matmul":
        command += ["--transpose", transpose]
        for key in ("m", "n", "k"):
            command += ["--" + key, str(record[key])]
        if tile:
            command += ["--tile", ",".join(map(str, tile))]
    elif tile:
        raise ValueError("Explicit matrix tiling is only valid for matmul")
    elif operation in ("conv", "dw"):
        conv = record["conv"]
        keys = ("batch", "input_h", "input_w", "input_channels", "output_channels", "output_h",
                "output_w", "stride", "input_dilation", "kernel_dilation", "padding", "kernel")
        command += ["--conv", ",".join(str(conv[key]) for key in keys)]
        command += ["--expected", str(out / "expected_s8.bin")]
    result = subprocess.run(command, text=True, capture_output=True)
    (out / "generation.log").write_text(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    emission = json.loads((out / "emission.json").read_text())
    records = read_trace(out / "commands.txt")
    if emission["records"] != len(records) or emission["config"] != build_record["config"]:
        raise ValueError("Trace count or parameter metadata differs from the build")
    validation = validate_trace(records, record, layout, flow, emission["config"])
    if emission["transpose"] != transpose:
        raise ValueError("Matrix storage and official transpose flags differ")
    metadata = {"format_version": 1, "name": record["name"], "operation": operation,
                "workload_manifest": str(directory / "case.json"),
                "workload_manifest_sha256": digest(directory / "case.json"),
                "m": record.get("m"), "n": record.get("n"), "k": record.get("k"),
                "scale": 0.03125, "repeating_bias": True, "output_type": "int8",
                "transpose": transpose,
                "memory_file": "memory.bin", "memory_base": base, "memory_bytes": len(data),
                "tensor_alignment_bytes": tensor_alignment,
                "memory_sha256": digest(out / "memory.bin"), "tensors": layout,
                "expected_output_file": "expected_s8.bin",
                "expected_output_sha256": digest(out / "expected_s8.bin"),
                "commands_file": "commands.txt", "commands_sha256": digest(out / "commands.txt"),
                "generator_command": command, "emission": emission, "validation": validation,
                "params_header_sha256": build_record["params_header_sha256"],
                "params_origin": build_record["params_origin"],
                "timing_scope": "From timed_start_record through final fence; includes hardware configuration, launch, DMA, execution and completion; host scheduler time is outside this accelerator-only test",
                "hardware_execution_performed": False}
    if operation in ("conv", "dw"):
        if emission["official_cpu_reference_passed"] is not True:
            raise ValueError("Official CPU convolution reference validation did not pass")
        metadata["conv"] = record["conv"]
        metadata["weight_layout"] = "C_KH_KW" if operation == "dw" else "KH_KW_CI_CO"
    write_json(out / "metadata.json", metadata)
    return {"name": record["name"], "metadata": str(out / "metadata.json"),
            "commands": emission["instructions"], "records": emission["records"],
            "command_generation_passed": True, "hardware_execution_performed": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gemmini-tests", type=Path, required=True)
    parser.add_argument("--params-header", type=Path, required=True)
    parser.add_argument("--params-origin", choices=("hardware-generated", "repository-default"), required=True)
    parser.add_argument("--workloads", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cases", nargs="+")
    parser.add_argument("--flow", choices=("ws", "os"), default="ws")
    parser.add_argument("--tile", nargs=3, type=int, metavar=("I", "J", "K"))
    parser.add_argument("--transpose", choices=("none", "a", "b"), default="none")
    parser.add_argument("--base", type=lambda value: int(value, 0), default=0x10000)
    parser.add_argument("--tensor-alignment", type=int, default=64)
    parser.add_argument("--cc", default="gcc")
    args = parser.parse_args()
    if args.tile and any(value <= 0 for value in args.tile):
        parser.error("Explicit tile dimensions must be positive")
    if args.tensor_alignment < 64 or args.tensor_alignment & (args.tensor_alignment - 1):
        parser.error("Tensor alignment must be a power of two of at least 64 bytes")
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    build_record = build(out / "build", args.gemmini_tests.resolve(),
                         args.params_header.resolve(), args.params_origin, args.cc)
    root = args.workloads.resolve()
    catalogue = json.loads((root / "workloads.json").read_text())
    cases = []
    available = {case["name"] for case in catalogue["cases"]}
    if args.cases and set(args.cases) - available:
        raise ValueError("Unknown workload names: " + ", ".join(sorted(set(args.cases) - available)))
    for item in catalogue["cases"]:
        if args.cases and item["name"] not in args.cases:
            continue
        manifest_path = root / item["manifest"]
        if digest(manifest_path) != item["manifest_sha256"]:
            raise ValueError("Workload manifest has changed: " + str(manifest_path))
        record = json.loads(manifest_path.read_text())
        result = generate_case(out / item["name"], manifest_path.parent, record,
                               build_record, args.base, args.flow, tuple(args.tile) if args.tile else None,
                               args.transpose, args.tensor_alignment)
        cases.append(result)
        print(json.dumps(result), flush=True)
    write_json(out / "summary.json", {"command_generation_passed": True,
               "hardware_execution_performed": False, "params_origin": args.params_origin,
               "params_header_sha256": build_record["params_header_sha256"],
               "flow": args.flow, "tensor_alignment_bytes": args.tensor_alignment,
               "cases": cases})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
