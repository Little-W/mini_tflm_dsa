#!/usr/bin/env python3
"""Verify software-proven PS bounds and record-limit errors in the common NPU."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

from frame_npu_test import set_boundary_bias
from run_shared_npu import configure, npu, validated_binary

ROOT = Path(__file__).resolve().parents[2]


def modify_weights(directory, *, small=False, exceed=False):
    cfg = [int(word, 16) for word in (directory / "config.mem").read_text().split()]
    image = npu.load_sparse(directory / "init.mem")
    if small:
        for index in range(cfg[5] * cfg[4]):
            image[cfg[15] + index] = (index % 5 - 2) & 255
    if exceed:
        width = 2 if cfg[12] else 1
        lhs = (-32768 if cfg[12] else -128).to_bytes(width, "little", signed=True)
        image[cfg[14]:cfg[14] + cfg[3] * cfg[4] * width] = lhs * (cfg[3] * cfg[4])
        image[cfg[15]:cfg[15] + cfg[5] * cfg[4]] = bytes([128]) * (cfg[5] * cfg[4])
    npu.sparse_mem(directory / "init.mem", image)
    if exceed:
        npu.sparse_mem(directory / "golden.mem", image)
    else:
        set_boundary_bias(directory)


def proven_bound(directory):
    """Use the full legal input interval and all retained K prefixes."""
    cfg = [int(word, 16) for word in (directory / "config.mem").read_text().split()]
    image = npu.load_sparse(directory / "init.mem")
    offset = npu.signed32(cfg[21])
    low, high = ((-32768, 32767) if cfg[12] else (-128, 127))
    low += offset
    high += offset
    minimum = maximum = 0
    prefix_checks = 0
    for channel in range(cfg[5]):
        lower = upper = 0
        for red in range((cfg[4] - 1) // 16 * 16):
            address = cfg[15] + channel * cfg[19] + red
            weight = int.from_bytes(image[address:address + 1], "little", signed=True)
            weight += npu.signed32(cfg[22])
            a, b = low * weight, high * weight
            lower += min(a, b)
            upper += max(a, b)
            if red % 16 == 15:
                minimum = min(minimum, lower)
                maximum = max(maximum, upper)
                prefix_checks += 1
    bits = 16 if minimum >= -32768 and maximum <= 32767 else (
        24 if minimum >= -8388608 and maximum <= 8388607 else 32)
    return dict(bits=bits, minimum=minimum, maximum=maximum,
                channel_prefix_checks=prefix_checks)


def generate(out):
    out.mkdir(parents=True, exist_ok=True)
    cases = []
    bounds = {}
    for mode in (0, 1):
        for bits, banks, red in ((16, 2, 35), (24, 1, 513)):
            directory = npu.precision_task(out, 16,
                name=f"s{bits}_{'is' if mode else 'ws'}_long", dataflow=mode,
                lhs_s16=False, rows=61, reduction=red, columns=61)
            if bits == 16:
                modify_weights(directory, small=True)
            else:
                set_boundary_bias(directory)
            bound = proven_bound(directory)
            if bound["bits"] != bits:
                raise AssertionError(f"Unexpected strict weight bound: {directory}: {bound}")
            bounds[directory.name] = bound
            cases.append(configure(directory, banks=banks, r=4, w=4,
                                   control=16 if bits == 16 else 32))

    for name, control, wide, error in (
            ("reserved_bound", 48, False, 1),
            ("reserved_control", 64, False, 1),
            ("s16_record_limit", 16, False, 2),
            ("s24_record_limit", 32, True, 2)):
        directory = npu.precision_task(out, 16, name=name, dataflow=0,
            lhs_s16=wide, rows=17, reduction=35, columns=19,
            expected_error=error)
        if error == 2:
            modify_weights(directory, exceed=True)
        cases.append(configure(directory, banks=2 if wide else 1,
                               r=1, w=1, control=control))
        recovery = npu.precision_task(out, 16, name=name + "_recovery", dataflow=0,
            lhs_s16=False, rows=17, reduction=35, columns=19)
        # RAW32 determines record width even when a software bound is present.
        cases.append(configure(recovery, banks=1, r=1, w=1, control=17))
    return cases, bounds


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "build/literal_bound_npu")
    parser.add_argument("--sim", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    cases, bounds = generate(out / "cases")
    binary = validated_binary(args.sim.resolve())
    suites = []
    for random_wait in (False, True):
        result = npu.run_suite(binary, out, "random" if random_wait else "fixed",
                               cases, no_random=not random_wait)
        selections = [{key: int(value) for key, value in re.findall(r"(\w+)=(\d+)", line)}
                      for line in (out / (result["name"] + ".log")).read_text().splitlines()
                      if line.startswith("PS_WINDOW_SELECT ")]
        result["capacity_selections"] = selections
        if len(selections) != len(cases):
            result["passed"] = False
        else:
            for directory, selected in zip(cases, selections):
                if directory.name in bounds:
                    bits = bounds[directory.name]["bits"]
                    result["passed"] &= selected["cap"] == bits // 8 and selected["micro"] == 0
                if directory.name.endswith("_recovery"):
                    result["passed"] &= selected["cap"] == 4 and selected["force_raw"] == 1
        suites.append(result)
        if not result["passed"]:
            break
    summary = dict(passed=all(result["passed"] for result in suites),
        expected_cases=2 * len(cases),
        completed_cases=sum(len(result["measurements"]) for result in suites),
        int32_checks=sum(row["int32_checks"] for result in suites for row in result["measurements"]),
        strict_weight_bounds=bounds, suites=suites)
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print("LITERAL_BOUND_NPU_RESULT", summary["passed"], summary["completed_cases"],
          summary["int32_checks"], flush=True)
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
