#!/usr/bin/env python3
"""Verify strict S8-weight PS bounds, including prepared model constants."""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import time


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command(argv, log, env=None):
    run = subprocess.run([str(value) for value in argv], text=True, capture_output=True, env=env)
    log.write_text(run.stdout + run.stderr)
    if run.returncode:
        raise RuntimeError(f"Command failed; see {log}")
    return run.stdout


def prepared_models(prepared, bound):
    schema_path = ROOT / "drivers/tflm/tflm/tflite-micro/tensorflow/lite/python/schema_py_generated.py"
    spec = importlib.util.spec_from_file_location("ps_bound_schema", schema_path)
    schema = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(schema)
    reports, sources = [], {}
    for model_name in ("mnist_cnn", "mobilenet_v1_vww", "ds_cnn_kws", "resnet8_cifar10"):
        directory = prepared / model_name
        manifest_path = directory / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        model_path = directory / manifest["model"]["path"]
        if digest(model_path) != manifest["model"]["sha256"]:
            raise ValueError(f"Model checksum mismatch: {model_path}")
        sources[model_name] = dict(model_sha256=digest(model_path), manifest_sha256=digest(manifest_path))
        model = schema.Model.GetRootAsModel(model_path.read_bytes(), 0)
        graph = model.Subgraphs(0)
        tensors = {tensor["index"]: tensor for tensor in manifest["graph"]["tensors"]}
        for node in manifest["graph"]["nodes"]:
            if node["op"] not in ("CONV_2D", "FULLY_CONNECTED"):
                continue
            inp, filt = (tensors[index] for index in node["inputs"][:2])
            if inp["dtype"] != "int8" or filt["dtype"] != "int8":
                raise ValueError("Model constant test requires S8 inputs and weights")
            if len(set(inp["zero_points"])) != 1 or len(set(filt["zero_points"])) != 1:
                raise ValueError("Model constant test requires uniform zero points")
            input_offset, weight_offset = -inp["zero_points"][0], -filt["zero_points"][0]
            xlo, xhi = -128 + input_offset, 127 + input_offset
            rows, depth = filt["shape"][0], math.prod(filt["shape"][1:])
            retained = (depth - 1) & ~15
            buffer = model.Buffers(graph.Tensors(filt["index"]).Buffer())
            weights = buffer.DataAsNumpy().tobytes()
            if len(weights) != rows * depth:
                raise ValueError("Weight shape does not match constant data")
            minimum = maximum = 0
            prefix_checks = 0
            for channel in range(rows):
                row_min = row_max = 0
                for k in range(retained):
                    raw = weights[channel * depth + k]
                    w = (raw if raw < 128 else raw - 256) + weight_offset
                    row_min += min(xlo * w, xhi * w)
                    row_max += max(xlo * w, xhi * w)
                    if k % 16 == 15:
                        minimum = min(minimum, row_min)
                        maximum = max(maximum, row_max)
                        prefix_checks += 1
            expected = (0 if not retained else
                        64 if minimum < -8388608 or maximum > 8388607 else
                        48 if minimum < -32768 or maximum > 32767 else 32)
            ordinary = ctypes.create_string_buffer(weights)
            measured = bound(ordinary, rows, depth, depth, 0, input_offset, weight_offset)
            kt, rt = (depth + 15) // 16, (rows + 15) // 16
            packed = bytearray([0x80]) * (rt * kt * 256)
            for row in range(rows):
                for k in range(depth):
                    packed[((row // 16) * kt + k // 16) * 256 + (row % 16) * 16 + k % 16] = weights[row * depth + k]
            packed_buffer = ctypes.create_string_buffer(bytes(packed))
            measured_packed = bound(packed_buffer, rows, depth, 0, 1, input_offset, weight_offset)
            if measured != expected or measured_packed != expected:
                raise ValueError(f"Static weight bound differs: {model_name} operator {node['index']}")
            reports.append(dict(model=model_name, operator_index=node["index"], operator_name=node["op"],
                                output_rows=math.prod(node["output_shapes"][0][:-1]),
                                channels=rows, depth=depth, retained_k=retained,
                                corrected_input_interval=[xlo, xhi], weight_offset=weight_offset,
                                prefix_minimum=minimum, prefix_maximum=maximum,
                                ps_literal_bytes=measured, prefix_channel_checks=prefix_checks,
                                scanned_weights=rows * retained, weight_bytes=len(weights),
                                weight_sha256=hashlib.sha256(weights).hexdigest(),
                                ordinary_and_packed_match=True))
    return dict(passed=True, prepared=str(prepared), sources=sources, layers=reports,
                layer_count=len(reports),
                scanned_weights=sum(row["scanned_weights"] for row in reports),
                prefix_channel_checks=sum(row["prefix_channel_checks"] for row in reports),
                assumption="Every input value in its complete signed-byte interval plus offset; no activation samples; final-K bias is excluded.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "build/ps_bound")
    parser.add_argument("--prepared", type=Path)
    parser.add_argument("--cc", default="gcc")
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources = [Path(__file__), HERE / "bound_test.cpp", ROOT / "drivers/dsa_ps_bound.h"]
    hashes = {str(path.relative_to(ROOT)): digest(path) for path in sources}
    started = time.monotonic()
    binary = out / "bound_test"
    compile_command = [args.cxx, "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror",
                       "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                       "-I" + str(ROOT / "drivers"), HERE / "bound_test.cpp", "-o", binary]
    command(compile_command, out / "compile.log")
    report = json.loads(command([binary], out / "run.log",
                                env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}))
    if args.prepared:
        wrapper = out / "bound_wrapper.c"
        wrapper.write_text('#include "dsa_ps_bound.h"\n'
                           'uint32_t checked_bound(const void *p,uint32_t n,uint32_t k,uint32_t stride,'
                           'uint32_t packed,int32_t x,int32_t w)'
                           '{return dsa_ps_bound_s8(p,n,k,stride,packed,x,w);}\n')
        library = out / "bound.so"
        command([args.cc, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-shared", "-fPIC",
                 "-fsanitize=undefined", "-fno-sanitize-recover=all", "-I" + str(ROOT / "drivers"),
                 wrapper, "-o", library], out / "wrapper_compile.log")
        shared = ctypes.CDLL(str(library))
        function = shared.checked_bound
        function.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
                             ctypes.c_uint32, ctypes.c_uint32, ctypes.c_int32, ctypes.c_int32]
        function.restype = ctypes.c_uint32
        model_report = prepared_models(args.prepared.resolve(), function)
        (out / "model_bounds.json").write_text(json.dumps(model_report, indent=2) + "\n")
        report["model_constants"] = {key: model_report[key] for key in
                                     ("passed", "layer_count", "scanned_weights", "prefix_channel_checks")}
        report["model_constants"]["library_sha256"] = digest(library)
    unchanged = hashes == {str(path.relative_to(ROOT)): digest(path) for path in sources}
    if not unchanged:
        raise ValueError("Bound sources changed during verification")
    report.update(source_sha256=hashes, sources_unchanged=True,
                  binary_sha256=digest(binary), address_sanitizer=True,
                  undefined_behavior_sanitizer=True,
                  compile_command=[str(value) for value in compile_command],
                  compiler_version=subprocess.check_output([args.cxx, "--version"], text=True).splitlines()[0],
                  elapsed_seconds=time.monotonic() - started)
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key not in
                      ("source_sha256", "compile_command")}, indent=2))


if __name__ == "__main__":
    main()
