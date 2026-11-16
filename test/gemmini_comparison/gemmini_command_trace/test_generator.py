#!/usr/bin/env python3
"""Check official scheduler trace emission, physical addresses and Conv support."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct

from generate import build, digest, generate_case, read_trace, write_json


def make_conv_case(directory: Path, operation: str, stride: int, batch: int) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    h, w, kernel = 4, 6, 3
    ci, co = (5, 5) if operation == "dw" else (3, 8)
    oh, ow, padding = h // stride, w // stride, 1 if stride == 1 else 0
    name = f"{operation}_rectangular_s{stride}_b{batch}"
    a = [((i * 5 + i // 9) % 7) - 3 for i in range(batch * h * w * ci)]
    weights = kernel * kernel * ci * (1 if operation == "dw" else co)
    b = [((i * 3 + 1) % 7) - 3 for i in range(weights)]
    bias = [i - 4 for i in range(co)]
    output = []
    for bi in range(batch):
        for y in range(oh):
            for x in range(ow):
                for oc in range(co):
                    total = bias[oc]
                    for ky in range(kernel):
                        for kx in range(kernel):
                            iy, ix = y * stride + ky - padding, x * stride + kx - padding
                            if 0 <= iy < h and 0 <= ix < w:
                                if operation == "dw":
                                    total += a[((bi * h + iy) * w + ix) * ci + oc] * b[(oc * kernel + ky) * kernel + kx]
                                else:
                                    for ic in range(ci):
                                        total += a[((bi * h + iy) * w + ix) * ci + ic] * b[((ky * kernel + kx) * ci + ic) * co + oc]
                    output.append(max(-128, min(127, round(total / 32))))
    weight_shape = [ci, kernel, kernel] if operation == "dw" else [kernel, kernel, ci, co]
    values = {"a": (bytes(value & 255 for value in a), [batch, h, w, ci], "|i1"),
              "b": (bytes(value & 255 for value in b), weight_shape, "|i1"),
              "bias": (struct.pack("<" + "i" * co, *bias), [co], "<i4"),
              "c_s8": (bytes(value & 255 for value in output), [batch, oh, ow, co], "|i1")}
    tensors = {}
    for name, (data, shape, dtype) in values.items():
        filename = name + ".bin"
        (directory / filename).write_bytes(data)
        tensors[name] = {"path": filename, "shape": shape, "dtype": dtype,
                         "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    case = {"name": name, "operation": operation, "m": batch * oh * ow, "n": co,
            "k": kernel * kernel * (1 if operation == "dw" else ci), "scale": 0.03125,
            "zero_points": {"a": 0, "b": 0, "c": 0}, "tensors": tensors,
            "conv": {"batch": batch, "input_h": h, "input_w": w, "input_channels": ci,
                     "output_channels": co, "output_h": oh, "output_w": ow,
                     "stride": stride, "input_dilation": 1, "kernel_dilation": 1,
                     "padding": padding, "kernel": kernel}}
    write_json(directory / "case.json", case)
    return case


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gemmini-tests", type=Path, required=True)
    parser.add_argument("--params-header", type=Path, required=True)
    parser.add_argument("--params-origin", choices=("hardware-generated", "repository-default"), required=True)
    parser.add_argument("--workloads", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    built = build(out / "build", args.gemmini_tests.resolve(), args.params_header.resolve(),
                  args.params_origin, "gcc")
    tests = []
    for name in ("tile16", "tail17", "vector_m1"):
        source = args.workloads.resolve() / name
        case = json.loads((source / "case.json").read_text())
        traces = []
        for base in (0x10000, 0x80010000):
            target = out / (name + "_" + hex(base))
            generate_case(target, source, case, built, base, "ws")
            traces.append(read_trace(target / "commands.txt"))
        for low, high in zip(traces[0], traces[1], strict=True):
            expected = dict(low)
            if low.get("funct") in (1, 2, 3, 14) and low["rs1"]:
                expected["rs1"] += 0x80000000
            if low.get("funct") in (10, 11, 20, 21):
                for key in ("rs1", "rs2"):
                    if low[key]:
                        expected[key] += 0x80000000
            assert high == expected, (name, low, high)
        if name == "tail17":
            bounds = [record for record in traces[0] if record.get("funct") == 9]
            assert len(bounds) == 1
            assert bounds[0]["rs1"] == (13 << 32) | (9 << 16) | 15
            assert bounds[0]["rs2"] == (2 << 32) | (2 << 16) | 2
        tests.append({"case": name, "physical_address_relocation_passed": True})
    source = args.workloads.resolve() / "tile16"
    case = json.loads((source / "case.json").read_text())
    generate_case(out / "tile16_os", source, case, built, 0x10000, "os")
    os_records = read_trace(out / "tile16_os/commands.txt")
    assert any(record.get("funct") == 4 for record in os_records)
    tests.append({"case": "tile16_os", "official_output_stationary_commands_passed": True})
    for operation, stride, batch in (("conv", 1, 1), ("conv", 2, 1), ("dw", 1, 1), ("dw", 2, 2)):
        source = out / f"{operation}_input_s{stride}_b{batch}"
        conv = make_conv_case(source, operation, stride, batch)
        target = out / conv["name"]
        generate_case(target, source, conv, built, 0x10000, "ws")
        conv_records = read_trace(target / "commands.txt")
        launches = [record for record in conv_records if record.get("funct") == 15]
        assert launches
        assert all(any(record.get("funct") == function for record in conv_records)
                   for function in range(16, 22))
        assert all(bool(record["rs1"] & (1 << 6)) == (operation == "dw") for record in launches)
        emission = json.loads((target / "emission.json").read_text())
        assert emission["official_cpu_reference_passed"] is True
        if operation == "dw":
            assert len(launches) == conv["conv"]["input_channels"]
            weights = [record["rs1"] for record in conv_records if record.get("funct") == 20]
            assert weights == [weights[0] + channel * 9 for channel in range(5)]
        tests.append({"case": conv["name"], "official_convolution_commands_passed": True,
                      "official_cpu_reference_passed": True})
    write_json(out / "summary.json", {"command_generation_passed": True,
               "hardware_execution_performed": False, "ubsan": True,
               "params_header_sha256": digest(args.params_header),
               "params_origin": args.params_origin, "config": built["config"], "tests": tests})
    print("GEMMINI_COMMAND_TRACE_PASS tests=" + str(len(tests)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
