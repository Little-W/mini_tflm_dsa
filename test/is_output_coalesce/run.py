#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Verify IS output grouping, row tails, AXI boundaries and recovery."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MATRIX_RUNNER = ROOT / "test/matrix_layout/run.py"


def read_sparse(path: Path, width: int, count: int, fill: bytes) -> bytearray:
    image = bytearray(fill * (count // len(fill)))
    address = 0
    for token in path.read_text().split():
        if token.startswith("@"):
            address = int(token[1:], 16) * width
        else:
            image[address:address + width] = int(token, 16).to_bytes(width, "little")
            address += width
    return image


def configure_output(runner, directory: Path, base: int, stride: int, w: int) -> None:
    config = [int(token, 16) for token in (directory / "config.mem").read_text().split()]
    m, n, old_base, old_stride = config[3], config[5], config[17], config[20]
    size = runner.WORDS * 4
    golden = read_sparse(directory / "golden.mem", 4, size, runner.SENTINEL)
    access = read_sparse(directory / "access.mem", 1, size, b"\0")
    output = [golden[old_base + row * old_stride:old_base + row * old_stride + n] for row in range(m)]
    for row in range(m):
        address = old_base + row * old_stride
        for byte in range(n):
            golden[address + byte] = runner.SENTINEL[(address + byte) % 4]
        access[address:address + n] = b"\0" * n
    for row in range(m):
        address = base + row * stride
        golden[address:address + n] = output[row]
        access[address:address + n] = b"\x02" * n
    config[7], config[17], config[20] = w, base, stride
    col_tiles = (m + 15) // 16
    col_groups, col_tail = (col_tiles + w - 1) // w, (col_tiles - 1) % w + 1
    config[30] = (config[30] & 65535) | (col_groups << 16)
    config[31] = (config[31] & 65535) | (col_tail << 16)
    (directory / "config.mem").write_text("".join(f"{value:08x}\n" for value in config))
    runner.sparse_words(directory / "golden.mem", golden)
    runner.sparse_access(directory / "access.mem", access)
    metadata = json.loads((directory / "case.json").read_text())
    metadata["output"] = dict(base=base, stride=stride)
    metadata["tiling"].update(w_reuse=w, col_groups=col_groups, col_tail_tiles=col_tail)
    metadata["ps_required_rows"] = ((config[6] + 1) * 16 - 1) * (min(w, col_tiles) + 1)
    (directory / "case.json").write_text(json.dumps(metadata, indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "build/is_output_coalesce")
    parser.add_argument("--build-dir", type=Path)
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--verilator", default="verilator")
    parser.add_argument("--jobs", type=int, default=2)
    args = parser.parse_args()
    args.ws_only = False
    args.out = args.out.resolve()
    args.extra_sources = [Path(__file__).resolve().with_name("axi_checks.sv")]
    args.out.mkdir(parents=True, exist_ok=True)
    build_dir = (args.build_dir or args.out / "sim").resolve()
    build_dir.mkdir(parents=True, exist_ok=True)
    spec = importlib.util.spec_from_file_location("matrix_layout_runner", MATRIX_RUNNER)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    cases = []

    def add(name, *, m=125, n=64, k=64, r=4, w=8,
            output_base=0x30fc0, output_stride=None, **kwargs):
        options = dict(mode=1, layout=3, channel=True, zp=True,
                       requested_r=r, requested_w=min(w, (m + 15) // 16), exact_reuse=True,
                       check_busy=True, crossing=True)
        options.update(kwargs)
        directory = runner.case(args.out / "cases", name, 8, m=m, n=n, k=k,
                                seed=4000 + len(cases), **options)
        stride = ((n + r * 16 - 1) // (r * 16)) * (r * 16) if output_stride is None else output_stride
        configure_output(runner, directory, output_base, stride, w)
        cases.append(directory)

    for layout in range(4):
        add(f"m125_n64_k64_layout{layout}", layout=layout)
    add("m144_r4_w16", m=144, w=16)
    add("m125_n128_two_groups", n=128)
    add("m33_n128_two_groups", m=33, n=128, k=17, w=4)
    add("m17_n96_r2_three_groups", m=17, n=96, k=35, r=2, w=2)
    add("m31_n64_r2_two_groups", m=31, k=35, r=2, w=2)
    add("m125_input_s16", input16=True)
    add("m125_n96_channel_tail", n=96, k=17)
    add("m144_n128_write_backpressure", m=144, n=128, k=16, w=16, hold=12000)
    add("m125_write_error", error=3, injection=2, check_busy=False, crossing=False)
    add("m125_after_write_error")
    add("m125_read_error", error=3, injection=1, check_busy=False, crossing=False)
    add("m125_after_read_error")
    add("m1_n128_two_groups", m=1, n=128, w=1)
    for m in (15, 16, 17):
        add(f"m{m}_row_boundary", m=m, k=17, w=1 if m <= 16 else 2)
    add("m125_base_fallback", output_base=0x30ff0)
    add("m125_stride_fallback", output_stride=80)
    add("m17_large_output_stride", m=17, k=17, w=2, output_stride=4096)

    binary = runner.build(build_dir, 8, args)
    results = [runner.run(binary, args.out, cases, False)]
    if results[0]["passed"]:
        results.append(runner.run(binary, args.out, cases, True))
    summary = dict(
        passed=all(result["passed"] for result in results),
        ia_cache_blocks=8, ps_storage_rows=799, s16_fifo_banks=4,
        generator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        matrix_runner_sha256=hashlib.sha256(MATRIX_RUNNER.read_bytes()).hexdigest(),
        simulator_build_manifest=str(build_dir / "build.json"),
        binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
        runs=results,
    )
    path = args.out / "summary.json"
    path.write_text(json.dumps(summary, indent=2) + "\n")
    print(path, flush=True)
    raise SystemExit(0 if summary["passed"] else 1)


if __name__ == "__main__":
    main()
