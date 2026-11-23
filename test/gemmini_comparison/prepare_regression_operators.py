#!/usr/bin/env python3
"""生成覆盖矩阵分块余数和卷积通道分组的独立数值测试。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from prepare import case, sha256
from prepare_conv import create_case


GEMM_SHAPES = (
    (1, 1, 1), (1, 17, 1), (15, 15, 15), (16, 16, 1),
    (17, 1, 17), (17, 17, 17), (31, 33, 31), (33, 31, 33),
    (48, 48, 96), (63, 65, 143), (65, 63, 145),
    (64, 64, 575), (64, 64, 577), (9, 255, 255), (9, 257, 257),
    (1023, 15, 143), (1025, 17, 145), (256, 32, 143), (256, 32, 145),
    (1, 65, 783),
)

SPATIAL_SHAPES = (
    ("depthwise", 7, 9, 1, 1, 1, 1),
    ("depthwise", 9, 7, 8, 8, 1, 1),
    ("depthwise", 11, 13, 17, 17, 1, 1),
    ("depthwise", 13, 11, 17, 17, 2, 0),
    ("conv2d", 7, 9, 3, 5, 1, 1),
    ("conv2d", 17, 15, 17, 19, 2, 1),
)


def write_catalogue(directory: Path, rows: list[dict]) -> None:
    entries = []
    for row in rows:
        manifest = directory / row["name"] / "case.json"
        entry = {"name": row["name"], "manifest": str(manifest.relative_to(directory)),
                 "manifest_sha256": sha256(manifest.read_bytes())}
        entry.update({key: row[key] for key in ("m", "n", "k", "operator") if key in row})
        entries.append(entry)
    (directory / "workloads.json").write_text(json.dumps({
        "format_version": 1,
        "scope": "Independent numeric tests for partial tiles, repeated K groups and spatial channel groups",
        "arithmetic": "signed_int8_inputs_int32_bias_accumulation_rne_divide32_int8_output",
        "cases": entries,
    }, indent=2) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20261123)
    args = parser.parse_args()
    gemm, spatial = args.out / "gemm", args.out / "conv"
    gemm.mkdir(parents=True, exist_ok=True)
    spatial.mkdir(parents=True, exist_ok=True)
    gemm_rows = [case(gemm, f"numeric_m{m}_n{n}_k{k}", m, n, k,
                      {"kind": "numeric_regression"}, args.seed) for m, n, k in GEMM_SHAPES]
    spatial_rows = []
    for kind, h, w, cin, cout, stride, padding in SPATIAL_SHAPES:
        name = f"numeric_{kind}_{h}x{w}_c{cin}_o{cout}_s{stride}_p{padding}"
        spatial_rows.append(create_case(spatial, name, kind, h, w, cin, cout,
                                        stride, padding, args.seed))
    write_catalogue(gemm, gemm_rows)
    write_catalogue(spatial, spatial_rows)
    print(json.dumps({"gemm_cases": len(gemm_rows), "spatial_cases": len(spatial_rows),
                      "seed": args.seed, "out": str(args.out.resolve())}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
