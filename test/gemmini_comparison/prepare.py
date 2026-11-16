#!/usr/bin/env python3
"""Create common INT8 GEMM inputs from exact benchmark operator dimensions."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import numpy as np

MODELS = ("mnist_cnn", "mobilenet_v1_vww", "ds_cnn_kws", "resnet8_cifar10")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_tensor(directory: Path, name: str, array: np.ndarray) -> dict:
    path = directory / name
    data = array.tobytes(order="C")
    path.write_bytes(data)
    return {"path": name, "shape": list(array.shape), "dtype": array.dtype.str,
            "bytes": len(data), "sha256": sha256(data), "order": "row_major"}


def values(count: int, seed: int, modulus: int, offset: int) -> np.ndarray:
    output = np.empty(count, dtype=np.int8)
    for index in range(count):
        seed = (1664525 * seed + 1013904223) & 0xFFFFFFFF
        output[index] = ((seed >> 16) % modulus) - offset
    return output


def rne_divide(values: np.ndarray, denominator: int) -> np.ndarray:
    quotient = values // denominator
    remainder = values - quotient * denominator
    return quotient + ((remainder > denominator // 2) |
                       ((remainder == denominator // 2) & ((quotient & 1) != 0)))


def case(out: Path, name: str, m: int, n: int, k: int, source: dict, seed: int) -> dict:
    directory = out / name
    directory.mkdir(parents=True, exist_ok=True)
    seed = (seed ^ int.from_bytes(hashlib.sha256(name.encode()).digest()[:4], "little")) & 0xFFFFFFFF
    a = values(m * k, seed, 7, 3).reshape(m, k)
    b = values(k * n, seed ^ 0xA59C3741, 7, 3).reshape(k, n)
    bias = values(n, seed ^ 0x13B729D4, 17, 8).astype("<i4")
    accumulator = a.astype(np.int64) @ b.astype(np.int64) + bias
    if np.max(np.abs(accumulator)) >= 1 << 24:
        raise ValueError("Common test exceeds exact FP32 integer range")
    result = np.clip(rne_divide(accumulator, 32), -128, 127).astype(np.int8)
    # Cross-check independent scalar dot products at regularly spaced outputs.
    flat = accumulator.reshape(-1)
    locations = range(len(flat)) if len(flat) <= 4096 else np.linspace(0, len(flat) - 1, 257, dtype=int)
    checks = 0
    for location in locations:
        row, column = divmod(int(location), n)
        expected = sum(int(a[row, reduction]) * int(b[reduction, column]) for reduction in range(k)) + int(bias[column])
        if expected != int(flat[location]):
            raise ValueError("Independent scalar GEMM differs from matrix calculation")
        checks += 1
    record = {"name": name, "m": m, "n": n, "k": k, "dense_macs": m * n * k,
              "source": source, "input_values": "deterministic synthetic integers in [-3,3]",
              "seed": seed, "formula": "C_s32 = A_s8 @ B_s8 + bias_s32; C_s8 = clip(RNE(C_s32 / 32), -128, 127)",
              "zero_points": {"a": 0, "b": 0, "c": 0}, "scale": 0.03125,
              "npu_quant_multiplier": 1073741824, "npu_quant_shift": -4,
              "reference": "NumPy INT64 matrix product and integer quotient/remainder RNE",
              "scalar_dot_products_checked": checks,
              "accumulator_min": int(accumulator.min()), "accumulator_max": int(accumulator.max()),
              "tensors": {"a": write_tensor(directory, "a_s8.bin", a),
                          "b": write_tensor(directory, "b_s8.bin", b),
                          "b_transposed": write_tensor(directory, "b_nk_s8.bin", b.T.copy()),
                          "bias": write_tensor(directory, "bias_s32.bin", bias),
                          "c_s32": write_tensor(directory, "c_s32.bin", accumulator.astype("<i4")),
                          "c_s8": write_tensor(directory, "c_s8.bin", result)}}
    (directory / "case.json").write_text(json.dumps(record, indent=2) + "\n")
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20261116)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    catalogue = []
    unique = {}
    for name in MODELS:
        path = args.prepared / name / "manifest.json"
        manifest = json.loads(path.read_text())
        for node in manifest["graph"]["nodes"]:
            op = node["op"]
            if op not in ("CONV_2D", "FULLY_CONNECTED", "DEPTHWISE_CONV_2D"):
                continue
            weight = node["input_shapes"][1]
            if op == "DEPTHWISE_CONV_2D":
                m = int(np.prod(node["output_shapes"][0][:-1]))
                k, n = weight[1] * weight[2], 1
                groups = node["output_shapes"][0][-1]
            else:
                n, k = weight[0], int(np.prod(weight[1:]))
                m, groups = int(np.prod(node["output_shapes"][0])) // n, 1
            origin = {"model": name, "model_sha256": manifest["model"]["sha256"],
                      "node": node["index"], "operator": op,
                      "m": m, "n": n, "k": k, "groups": groups,
                      "input_shapes": node["input_shapes"], "output_shapes": node["output_shapes"]}
            catalogue.append(origin)
            if op != "DEPTHWISE_CONV_2D":
                unique.setdefault((m, n, k), []).append(origin)
    records = []
    for name, dims in (("tile16", (16, 16, 16)), ("tile32", (32, 32, 32)),
                       ("tile64", (64, 64, 64)), ("tail17", (17, 23, 19)),
                       ("vector_m1", (1, 64, 64))):
        records.append(case(args.out, name, *dims, {"kind": "matrix_shape_test"}, args.seed))
    for (m, n, k), origins in unique.items():
        name = f"model_m{m}_n{n}_k{k}"
        records.append(case(args.out, name, m, n, k,
                            {"kind": "exact_model_operator_shape", "operators": origins}, args.seed))
    result = {"format_version": 1, "arithmetic": "signed_int8_inputs_int32_bias_accumulation_rne_divide32_int8_output",
              "scope": "GEMM shape comparison using shared synthetic operands; convolution lowering is performed before device timing",
              "cases": [{"name": row["name"], "m": row["m"], "n": row["n"], "k": row["k"],
                         "manifest": row["name"] + "/case.json",
                         "manifest_sha256": sha256((args.out / row["name"] / "case.json").read_bytes())}
                        for row in records], "model_operator_catalogue": catalogue}
    (args.out / "workloads.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"cases": len(records), "model_operators": len(catalogue),
                      "outputs": sum(row["m"] * row["n"] for row in records), "path": str(args.out)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
