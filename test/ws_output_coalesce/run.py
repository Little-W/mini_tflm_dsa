#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Verify WS output row tails, bank traversal, page splits and recovery."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def sparse_image(path: Path, width: int, size: int, fill: bytes) -> bytearray:
    result = bytearray(fill * (size // len(fill)))
    address = 0
    for token in path.read_text().split():
        if token.startswith("@"):
            address = int(token[1:], 16) * width
        else:
            result[address:address + width] = int(token, 16).to_bytes(width, "little")
            address += width
    return result


def configure_output(runner, directory: Path, r: int, w: int,
                     base: int, stride: int) -> None:
    config = [int(value, 16) for value in (directory / "config.mem").read_text().split()]
    m, n = config[3], config[5]
    element_bytes = 2 if config[28] else 1
    size = runner.WORDS * 4
    golden = sparse_image(directory / "golden.mem", 4, size, runner.SENTINEL)
    access = sparse_image(directory / "access.mem", 1, size, b"\0")
    row_bytes = n * element_bytes
    output = [golden[config[17] + row * config[20]:
                     config[17] + row * config[20] + row_bytes] for row in range(m)]
    for row in range(m):
        address = config[17] + row * config[20]
        for byte in range(row_bytes):
            golden[address + byte] = runner.SENTINEL[(address + byte) % 4]
        access[address:address + row_bytes] = b"\0" * row_bytes
    for row in range(m):
        address = base + row * stride
        assert address + row_bytes <= size
        golden[address:address + row_bytes] = output[row]
        access[address:address + row_bytes] = b"\x02" * row_bytes
    tr, tc = (m + 15) // 16, (n + 15) // 16
    config[6], config[7], config[17], config[20] = r, w, base, stride
    config[30] = (tr + r - 1) // r | (((tc + w - 1) // w) << 16)
    config[31] = (tr - 1) % r + 1 | (((tc - 1) % w + 1) << 16)
    (directory / "config.mem").write_text("".join(f"{value:08x}\n" for value in config))
    runner.sparse_words(directory / "golden.mem", golden)
    runner.sparse_access(directory / "access.mem", access)
    metadata = json.loads((directory / "case.json").read_text())
    metadata["output"] = dict(base=base, stride=stride, element_bytes=element_bytes)
    metadata["tiling"] = dict(ia_reuse=r, w_reuse=w,
        row_groups=(tr + r - 1) // r, col_groups=(tc + w - 1) // w,
        row_tail_tiles=(tr - 1) % r + 1, col_tail_tiles=(tc - 1) % w + 1)
    metadata["ps_required_rows"] = ((min(r, tr) + 1) * 16 - 1) * (min(w, tc) + 1) if config[4] > 16 else 0
    (directory / "case.json").write_text(json.dumps(metadata, indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "build/ws_output_coalesce")
    parser.add_argument("--profiles", type=int, nargs="+", choices=(8, 16), default=(8, 16))
    parser.add_argument("--verilator", default="verilator")
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--ws-only", action="store_true")
    parser.add_argument("--case", help="Regular expression selecting case names")
    args = parser.parse_args()
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=True)
    args.extra_sources = [HERE / "checks.sv"]
    runner_path = ROOT / "test/matrix_layout/run.py"
    spec = importlib.util.spec_from_file_location("matrix_layout_runner", runner_path)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    summary = dict(passed=True, source_commit=subprocess.check_output(
                   ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                   generator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                   matrix_runner_sha256=hashlib.sha256(runner_path.read_bytes()).hexdigest(), profiles=[])

    for ia in args.profiles:
        directory = args.out / f"ia{ia}"
        directory.mkdir(parents=True, exist_ok=True)
        cases = []

        def add(name, *, m=36, n=128, k=17, r=4, w=8,
                base=0x30fc0, stride=None, **options):
            if args.case and not re.search(args.case, name):
                return
            initial = dict(mode=0, layout=3, channel=True, zp=True,
                requested_r=min(r, (m + 15) // 16), requested_w=min(w, (n + 15) // 16),
                exact_reuse=True, check_busy=True, crossing=True)
            initial.update(options)
            path = runner.case(directory / "cases", name, ia, m=m, n=n, k=k,
                               seed=6000 + len(cases), **initial)
            row_bytes = n * (2 if options.get("output16", False) else 1)
            configure_output(runner, path, r, w, base, row_bytes if stride is None else stride)
            cases.append(path)

        for layout in range(4):
            add(f"m36_n128_layout{layout}", k=64, layout=layout)
        for offset in range(4):
            add(f"m64_n64_k32_offset{offset}", m=64, n=64, k=32, r=4, w=4, base=0x30ffc + offset)
            add(f"m9_n256_offset{offset}", m=9, n=256, k=64, r=1, w=16, base=0x30ffc + offset)
        add("m1_n256_full_chunk", m=1, n=256, r=1, w=16, base=0x30fff)
        for m in range(2, 15):
            add(f"m{m}_short_group", m=m, n=64, r=1, w=4)
        for m in (1, 15, 16, 17, 31, 32, 33, 47, 48, 63, 64, 65, 70, 79, 80, 81, 125, 129):
            add(f"m{m}_row_groups", m=m, n=128, r=4, w=8)
        add("m36_multiple_column_segments", m=36, n=256, r=4, w=4)
        add("m65_multiple_row_column_groups", m=65, n=256, r=4, w=8)
        add("m17_n512_ps799", m=17, n=512, r=2, w=16)
        add("m36_w16_tail", m=36, n=128, r=4, w=16)
        add("m81_w16_tail", m=81, n=128, r=4, w=16)
        add("m33_channel_tail", m=33, n=48, r=4, w=4)
        add("strided_output", m=36, n=64, w=4, stride=80)
        add("s16_input_s8_output", m=17, n=64, r=2, w=4, input16=True)
        add("s16_output_tail", m=17, n=64, r=2, w=4, output16=True)
        add("s16_fifo_backpressure", m=64, n=64, k=33, r=4, w=4,
            output16=True, hold=12000, require_full=True)
        add("per_tensor_parameters", m=9, n=64, r=1, w=4, channel=False)
        add("write_backpressure", m=65, n=128, k=16, r=4, w=8, hold=12000)
        add("write_response_error", m=17, n=128, r=2, w=8,
            error=3, injection=2, check_busy=False, crossing=False)
        add("after_write_error", m=17, n=128, r=2, w=8)
        add("read_response_error", m=17, n=128, r=2, w=8,
            error=3, injection=1, check_busy=False, crossing=False)
        add("after_read_error", m=17, n=128, r=2, w=8)
        if ia == 16:
            for m in (113, 127, 128, 129, 145):
                add(f"r8_m{m}", m=m, n=64, r=8, w=4)
        assert cases
        binary = runner.build(directory, ia, args)
        runs = [runner.run(binary, directory, cases, False)]
        if runs[0]["passed"]:
            runs.append(runner.run(binary, directory, cases, True))
        for result in runs:
            log = directory / ("random_axi.log" if "+NO_RANDOM_WAIT" not in result["command"] else "fixed_axi.log")
            counters = [{key: int(value) for key, value in re.findall(r"(\w+)=(\d+)", line)}
                for line in log.read_text().splitlines() if line.startswith("WS_OUTPUT_COUNTS")]
            assert len(counters) == len(result["measurements"])
            for record, values in zip(result["measurements"], counters):
                record["output_counters"] = values
            result["log_sha256"] = hashlib.sha256(log.read_bytes()).hexdigest()
        profile = dict(ia_cache_blocks=ia, ps_storage_rows=799, s16_fifo_banks=4,
                       enable_is_mode=int(not args.ws_only),
                       build_manifest=str(directory / "build.json"), runs=runs)
        summary["profiles"].append(profile)
        summary["passed"] = summary["passed"] and all(run["passed"] for run in runs)
        (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        if not summary["passed"]:
            break
    print(args.out / "summary.json", flush=True)
    raise SystemExit(0 if summary["passed"] else 1)


if __name__ == "__main__":
    main()
