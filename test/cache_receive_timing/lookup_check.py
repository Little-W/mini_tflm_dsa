#!/usr/bin/env python3
"""验证缓存查询有效位的同步保存及同周期写入转发。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shlex

from run import execute, observed_cache, prove_response, restore_valid_storage_names
from support import REFERENCE, check_sources, digest, prepare_inputs


def prepare_observers(out, paths):
    observed = {}
    for label, path in paths.items():
        body = observed_cache(path.read_text(), label, payload_when_valid=True)
        if label == "current":
            if "g_saved_lookup_valid" not in body:
                raise RuntimeError("待测源码未包含查询有效位保存结构")
        target = out / (label + "_observed.sv")
        target.write_text(body)
        observed[label] = target
    return observed


def prove_cache(out, observed, helpers, profile):
    sets, ways, depth, line_bytes = profile
    name = f"s{sets}_w{ways}_d{depth}_l{line_bytes}"
    script, log = out / (name + ".ys"), out / (name + ".log")
    commands = []
    for label, path in observed.items():
        commands += [
            "read_slang -D SYNTHESIS=1 -D XILINX_FPGA=1 --top conv_windowed_cache "
            f"-GSETS={sets} -GWAYS={ways} -GDEMAND_DEPTH={depth} "
            f"-GLINE_BYTES={line_bytes} -GBUS_WIDTH=64 -GREAD_WIDTH=64 "
            "-Gp_defer_retire_shift=1 " + shlex.join(map(str, [path] + helpers)),
            "prep -top conv_windowed_cache -flatten",
            "memory_map", "async2sync", "opt_clean",
        ]
        if label == "current":
            # 存储内容继续逐位比较，端口名称的变化不减少内部存储检查范围。
            commands += restore_valid_storage_names(sets, ways)
        commands += [f"rename conv_windowed_cache {label}", f"design -stash {label}"]
    commands += [
        "design -copy-from reference -as reference reference",
        "design -copy-from current -as current current",
        "equiv_make reference current equivalent", "hierarchy -top equivalent",
        "equiv_simple -seq 1", "opt_clean", "equiv_induct -seq 3",
        "equiv_status -assert",
    ]
    script.write_text("\n".join(commands) + "\n")
    execute(script, log, "Equivalence successfully proven")
    match = re.search(r"Of those cells (\d+) are proven and (\d+) are unproven", log.read_text())
    if match is None or int(match[2]) != 0:
        raise RuntimeError("完整缓存等价位检查未完成: " + name)
    print("LOOKUP_VALID_PROOF_PASS", name, flush=True)
    return dict(SETS=sets, WAYS=ways, DEMAND_DEPTH=depth, LINE_BYTES=line_bytes,
                BUS_WIDTH=64, READ_WIDTH=64, passed=True,
                equivalent_bits=int(match[1]), log_sha256=digest(log))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference", default=REFERENCE,
                        help="参考提交或参考 RTL 文件")
    parser.add_argument("--candidate", type=Path,
                        help="待测缓存 RTL，默认读取当前仓库")
    parser.add_argument("--profiles", nargs="+",
                        default=["2:1:1:16", "2:2:1:16", "4:2:4:16", "2:2:1:128", "16:2:1:128"],
                        help="完整缓存参数，格式为 SETS:WAYS:DEMAND_DEPTH:LINE_BYTES")
    args = parser.parse_args()
    profiles = []
    for value in args.profiles:
        fields = value.split(":")
        if len(fields) != 4 or any(not field.isdigit() or int(field) < 1 for field in fields):
            parser.error("无效的完整缓存参数: " + value)
        profiles.append(tuple(map(int, fields)))
    out = args.out.resolve()
    _, paths, helpers, manifest = prepare_inputs(out, args.reference, args.candidate)
    report = {"passed": False, "inputs": manifest, "input_assumptions": [],
              "response_profiles": prove_response(out, paths, payload_when_valid=True),
              "profiles": []}
    observed = prepare_observers(out, paths)
    for profile in profiles:
        report["profiles"].append(prove_cache(out, observed, helpers, profile))
    check_sources(manifest)
    report["passed"] = True
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
