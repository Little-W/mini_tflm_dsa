#!/usr/bin/env python3
"""Generate shared NHWC Conv and genuine depthwise Conv comparison cases."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from prepare import rne_divide, sha256, values, write_tensor


def create_case(out: Path, name: str, kind: str, h: int, w: int, cin: int,
                cout: int, stride: int, padding: int, seed: int) -> dict:
    kh = kw = 3
    oh, ow = (h + stride - 1) // stride, (w + stride - 1) // stride
    depthwise = kind == "depthwise"
    if depthwise and cin != cout:
        raise ValueError("Depthwise comparison uses channel multiplier one")
    directory = out / name
    directory.mkdir(parents=True, exist_ok=True)
    seed ^= int.from_bytes(hashlib.sha256(name.encode()).digest()[:4], "little")
    inputs = values(h * w * cin, seed, 7, 3).reshape(1, h, w, cin)
    count = kh * kw * cin * (1 if depthwise else cout)
    weights = values(count, seed ^ 0xA59C3741, 7, 3)
    weights = weights.reshape(kh, kw, cin) if depthwise else weights.reshape(kh, kw, cin, cout)
    bias = values(cout, seed ^ 0x13B729D4, 17, 8).astype("<i4")
    bottom = max(0, (oh - 1) * stride + kh - h - padding)
    right = max(0, (ow - 1) * stride + kw - w - padding)
    padded = np.pad(inputs.astype(np.int64), ((0, 0), (padding, bottom), (padding, right), (0, 0)))
    accumulators = np.broadcast_to(bias, (1, oh, ow, cout)).astype(np.int64).copy()
    for ky in range(kh):
        for kx in range(kw):
            pixels = padded[:, ky:ky + oh * stride:stride, kx:kx + ow * stride:stride, :]
            if depthwise:
                accumulators += pixels * weights[ky, kx].astype(np.int64)
            else:
                accumulators += pixels @ weights[ky, kx].astype(np.int64)
    if np.max(np.abs(accumulators)) >= 1 << 24:
        raise ValueError("Convolution exceeds exact FP32 integer range")
    outputs = np.clip(rne_divide(accumulators, 32), -128, 127).astype(np.int8)
    for flat_index in np.linspace(0, outputs.size - 1, min(257, outputs.size), dtype=int):
        y, remainder = divmod(int(flat_index), ow * cout)
        x, oc = divmod(remainder, cout)
        expected = int(bias[oc])
        for ky in range(kh):
            for kx in range(kw):
                iy, ix = y * stride + ky - padding, x * stride + kx - padding
                if 0 <= iy < h and 0 <= ix < w:
                    if depthwise:
                        expected += int(inputs[0, iy, ix, oc]) * int(weights[ky, kx, oc])
                    else:
                        expected += sum(int(inputs[0, iy, ix, ic]) * int(weights[ky, kx, ic, oc])
                                        for ic in range(cin))
        if expected != int(accumulators[0, y, x, oc]):
            raise ValueError("Direct scalar convolution disagrees with array reference")
    gemmini_weights = weights.transpose(2, 0, 1).copy() if depthwise else weights
    npu_weights = weights if depthwise else weights.transpose(3, 0, 1, 2).copy()
    record = {"name": name, "operator": kind, "operation": "dw" if depthwise else "conv",
              "conv": {"batch": 1, "input_h": h, "input_w": w, "input_channels": cin,
                       "output_channels": cout, "output_h": oh, "output_w": ow, "stride": stride,
                       "input_dilation": 1, "kernel_dilation": 1, "padding": padding, "kernel": 3},
              "batch": 1, "input_h": h, "input_w": w,
              "input_channels": cin, "output_channels": cout, "output_h": oh, "output_w": ow,
              "kernel_h": kh, "kernel_w": kw, "stride_h": stride, "stride_w": stride,
              "dilation_h": 1, "dilation_w": 1,
              "pad_top": padding, "pad_left": padding, "pad_bottom": bottom, "pad_right": right,
              "useful_macs": oh * ow * kh * kw * cin * (1 if depthwise else cout),
              "seed": seed, "zero_points": {"input": 0, "weights": 0, "output": 0},
              "scale": 0.03125, "npu_quant_multiplier": 1073741824, "npu_quant_shift": -4,
              "formula": "NHWC cross-correlation with explicit zero padding, bias, clip(RNE(accumulator / 32), -128, 127)",
              "weight_order": {"b": "C_KH_KW" if depthwise else "KH_KW_CI_CO",
                               "weights_npu": "KH_KW_C" if depthwise else "CO_KH_KW_CI"},
              "reference": "INT64 array convolution checked by direct scalar convolution at 257 output positions",
              "accumulator_min": int(accumulators.min()), "accumulator_max": int(accumulators.max()),
              "tensors": {"a": write_tensor(directory, "input_nhwc_s8.bin", inputs),
                          "b": write_tensor(directory, "weights_gemmini_s8.bin", gemmini_weights),
                          "weights_npu": write_tensor(directory, "weights_npu_s8.bin", npu_weights),
                          "bias": write_tensor(directory, "bias_s32.bin", bias),
                          "c_s32": write_tensor(directory, "output_nhwc_s32.bin", accumulators.astype("<i4")),
                          "c_s8": write_tensor(directory, "output_nhwc_s8.bin", outputs)}}
    (directory / "case.json").write_text(json.dumps(record, indent=2) + "\n")
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20261116)
    parser.add_argument("--extended", action="store_true",
                        help="Include the 32x32 C16 and 8x8 C64 convolution cases")
    args = parser.parse_args()
    records = [create_case(args.out, "conv3x3_s2_96_c3_o8", "conv2d", 96, 96, 3, 8, 2, 0, args.seed),
               create_case(args.out, "dw3x3_s1_48_c8", "depthwise", 48, 48, 8, 8, 1, 1, args.seed),
               create_case(args.out, "dw3x3_s2_48_c8", "depthwise", 48, 48, 8, 8, 2, 0, args.seed)]
    if args.extended:
        records.extend([
            create_case(args.out, "conv3x3_32_c16_o16", "conv2d", 32, 32, 16, 16, 1, 1, args.seed),
            create_case(args.out, "conv3x3_8_c64_o64", "conv2d", 8, 8, 64, 64, 1, 1, args.seed),
        ])
    catalogue = {"format_version": 1, "scope": "Raw NHWC input through hardware Conv/DW input gathering and output writeback",
                 "arithmetic": "signed_int8_inputs_int32_bias_accumulation_rne_divide32_int8_output",
                 "cases": [{"name": record["name"], "operator": record["operator"],
                            "manifest": record["name"] + "/case.json",
                            "manifest_sha256": sha256((args.out / record["name"] / "case.json").read_bytes())}
                           for record in records]}
    (args.out / "workloads.json").write_text(json.dumps(catalogue, indent=2) + "\n")
    print(json.dumps({"cases": len(records), "outputs": sum(record["output_h"] * record["output_w"] * record["output_channels"] for record in records),
                      "path": str(args.out.resolve())}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
