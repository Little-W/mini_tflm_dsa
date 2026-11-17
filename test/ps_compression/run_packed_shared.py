#!/usr/bin/env python3
"""Check packed operands and global K addressing with configurable IA/PS RAM."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from run_shared_npu import configure, npu, validated_binary


def pack_operand(directory: Path, operand: str) -> None:
    config_path = directory / "config.mem"
    cfg = [int(word, 16) for word in config_path.read_text().split()]
    lhs = operand == "lhs"
    base, rows = (cfg[14], cfg[3]) if lhs else (cfg[15], cfg[5])
    stride, width = (cfg[18], 2 if cfg[12] else 1) if lhs else (cfg[19], 1)
    reduction = cfg[4]
    tiles = (reduction + 15) // 16
    packed = bytearray([0x5A] * (((rows + 15) // 16) * tiles * 256 * width))
    image = npu.load_sparse(directory / "init.mem")
    for row in range(rows):
        for column in range(reduction):
            source = base + row * stride + column * width
            target = (((row // 16) * tiles + column // 16) * 256 +
                      (row % 16) * 16 + column % 16) * width
            packed[target:target + width] = image[source:source + width]
    for name in ("init.mem", "golden.mem"):
        memory = npu.load_sparse(directory / name)
        memory[base:base + len(packed)] = packed
        npu.sparse_mem(directory / name, memory)
    cfg[29] |= 1 if lhs else 2
    config_path.write_text("".join(f"{word:08x}\n" for word in cfg))


def generate(out: Path) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    cases = []
    for mode in (0, 1):
        for layout in (1, 2, 3):
            for raw in (False, True):
                rows, cols = (81, 67) if mode == 0 else (67, 81)
                directory = npu.precision_task(
                    out, 16, name=f"packed_gemm_mode{mode}_layout{layout}_raw{int(raw)}",
                    rows=rows, columns=cols, reduction=53, dataflow=mode,
                    lhs_s16=False)
                configure(directory, banks=2 if raw else 4, r=8, w=5,
                          control=7 if raw else 14)
                for operand, flag in (("lhs", 1), ("rhs", 2)):
                    if layout & flag:
                        pack_operand(directory, operand)
                cases.append(directory)
    reference = npu.make_reference(out)
    for mode in (0, 1):
        for raw in (False, True):
            directory = npu.task(
                out, 16, reference, name=f"packed_conv_mode{mode}_raw{int(raw)}",
                h=9, w=9, c=5, kh=3, kw=3, co=67, dataflow=mode, seed=1937)
            configure(directory, banks=2 if raw else 4, r=8, w=5,
                      control=7 if raw else 14)
            pack_operand(directory, "rhs")
            cases.append(directory)
    return cases


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sim", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    cases = generate(out / "cases")
    binary = validated_binary(args.sim.resolve())
    results = [npu.run_suite(binary, out, name, cases, no_random=fixed)
               for name, fixed in (("fixed", True), ("random", False))]
    summary = dict(passed=all(item["passed"] for item in results),
                   expected_cases=2 * len(cases),
                   completed_cases=sum(len(item["measurements"]) for item in results),
                   int32_checks=sum(row["int32_checks"] for item in results
                                    for row in item["measurements"]),
                   suites=results)
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print("PACKED_SHARED_RESULT", summary["passed"], summary["completed_cases"],
          summary["int32_checks"], flush=True)
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
