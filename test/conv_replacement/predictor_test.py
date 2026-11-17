#!/usr/bin/env python3
"""Run geometry-derived next-use vectors through the standalone production RTL.

This validates the predictor and its eligibility guards.  Cache admission,
memory traffic and whole-NPU numerical correctness are separate tests.
"""
import argparse
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from geometry_oracle import Geometry, INF, ROOT, relative, sha256


HERE = Path(__file__).resolve().parent
CONFIG_FIELDS = ["input_base", "input_h", "input_w", "input_c", "group_c", "group_offset",
                 "kernel_h", "kernel_w", "output_h", "output_w", "stride_h", "stride_w",
                 "dilation_h", "dilation_w", "pad_top", "pad_left", "r", "groups", "input_s16"]
VECTOR_FIELDS = ["input_y", "input_x", "channel", "current_p", "current_q", "current_group", "expected_next_rank"]


def command(argv, log, timeout=120):
    with log.open("w") as stream:
        stream.write("COMMAND: " + repr([str(x) for x in argv]) + "\n")
        stream.flush()
        result = subprocess.run([str(x) for x in argv], cwd=ROOT, stdout=stream,
                                stderr=subprocess.STDOUT, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"command failed ({result.returncode}): {log}\n{log.read_text()[-8000:]}")


def disabled_case(name, geometry, bypass=False):
    return {"case": name, "source": "predictor eligibility guard", "geometry": asdict(geometry),
            "enabled": False, "bypass": bypass,
            "vectors": [{"input_y": 0, "input_x": 0, "channel": 0,
                         "current_p": 0, "current_q": 0, "current_group": 0,
                         "expected_next_rank": INF}]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build/conv_replacement/predictor")
    parser.add_argument("--out", type=Path, default=ROOT / "build/conv_replacement/predictor/validation.json")
    parser.add_argument("--verilator", type=Path,
                        default=Path(shutil.which("verilator") or "verilator"))
    args = parser.parse_args()
    args.build = args.build.resolve()
    args.out = args.out.resolve()
    args.build.mkdir(parents=True, exist_ok=True)
    oracle_json = args.build / "oracle_validation.json"
    vector_json = args.build / "vectors.json"
    command([sys.executable, HERE / "geometry_oracle.py", "--out", oracle_json, "--vectors", vector_json],
            args.build / "oracle.log")
    cases = json.loads(vector_json.read_text())["cases"]
    for case in cases:
        case.update(enabled=True, bypass=False)
    geometry = json.loads(oracle_json.read_text())
    for layer in geometry["layers"]:
        g = Geometry(**layer["geometry"])
        if g.unsupported_reasons():
            cases.append(disabled_case(layer["layer_id"] + ":unsupported", g))
    base = Geometry(0x10000, 8, 8, 32, 16, 16, 3, 3, 8, 8, 1, 1, 1, 1, 1, 1, 2, 1)
    disabled = [
        ("s16", {"input_s16": True}), ("base_alignment", {"input_base": 0x10001}),
        ("cin_alignment", {"input_c": 33}), ("group_alignment", {"group_c": 15}),
        ("group_offset_alignment", {"group_offset": 1}), ("r_not_power_of_two", {"r": 3}),
        ("stride_h_not_power_of_two", {"stride_h": 3}),
        ("stride_w_not_power_of_two", {"stride_w": 3}),
        ("kernel_tap_limit", {"kernel_h": 6, "kernel_w": 5}),
        ("rank_block_span_overflow", {"groups": 1 << 30}),
        ("rank_total_overflow", {"output_h": 65535, "output_w": 65535}),
        ("zero_dilation", {"dilation_h": 0}), ("zero_groups", {"groups": 0}),
        ("zero_r", {"r": 0}), ("zero_stride", {"stride_w": 0}),
    ]
    for name, changes in disabled:
        cases.append(disabled_case(name, replace(base, **changes)))
    cases.append(disabled_case("explicit_bypass", base, bypass=True))
    configs, vectors = [], []
    for case in cases:
        fields = [int(case["geometry"][name]) for name in CONFIG_FIELDS]
        fields += [int(case["bypass"]), int(case["enabled"]), len(case["vectors"])]
        configs.append(" ".join(f"{value:08x}" for value in fields))
        for vector in case["vectors"]:
            vectors.append(" ".join(f"{vector[name]:08x}" for name in VECTOR_FIELDS))
    config_path, vectors_path = args.build / "config.txt", args.build / "vectors.txt"
    config_path.write_text("\n".join(configs) + "\n")
    vectors_path.write_text("\n".join(vectors) + "\n")
    sources = [ROOT / "rtl/npu/conv/conv_im2col_pkg.sv",
               ROOT / "rtl/npu/dma/cache/conv_next_use_predictor.sv", HERE / "predictor_tb.sv"]
    source_hashes = {relative(path): sha256(path) for path in sources + [Path(__file__), HERE / "geometry_oracle.py"]}
    obj_dir = args.build / "obj_dir"
    binary = obj_dir / "Vpredictor_tb"
    command([args.verilator, "--binary", "--timing", "--assert", "-DCONV_ASSERT", "-Wno-fatal",
             "--top-module", "predictor_tb", "--Mdir", obj_dir, "-j", "2", *sources],
            args.build / "build.log")
    command([binary, f"+CONFIG={config_path}", f"+VECTORS={vectors_path}", f"+CASES={len(cases)}"],
            args.build / "run.log", timeout=60)
    run_log = (args.build / "run.log").read_text()
    if f"PREDICTOR_PASS cases={len(cases)}" not in run_log:
        raise AssertionError("predictor success marker missing")
    for path, before in source_hashes.items():
        if sha256(ROOT / path) != before:
            raise AssertionError(f"source changed during predictor validation: {path}")
    report = {
        "passed": True,
        "scope": "Standalone production conv_next_use_predictor RTL; every next-rank vector and eligibility case checked, not a whole-NPU/cache performance run",
        "sources": source_hashes, "geometry_is_generated_on_each_run": True,
        "oracle_validation_sha256": sha256(oracle_json), "vector_json_sha256": sha256(vector_json),
        "config_text_sha256": sha256(config_path), "vector_text_sha256": sha256(vectors_path),
        "total_cases": len(cases), "enabled_cases": sum(case["enabled"] for case in cases),
        "disabled_cases": sum(not case["enabled"] for case in cases),
        "total_vectors": len(vectors), "max_kernel_taps_tested": 25,
        "result_checks": ["exact next_rank", "no-future INF", "eligibility before and after latch",
                          "one cycle per kernel tap", "single-cycle done", "result holds until next request"],
        "cases": [{"case": case["case"], "source": case["source"],
                   "enabled": case["enabled"], "vectors": len(case["vectors"])} for case in cases],
        "build": str(args.build), "build_log_sha256": sha256(args.build / "build.log"),
        "run_log_sha256": sha256(args.build / "run.log"),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    # All generated vectors, logs and reports remain beneath selected build/output paths.
    for name in ("build.log", "run.log"):
        destination = args.out.with_name("predictor_" + name)
        if destination != args.build / name:
            shutil.copyfile(args.build / name, destination)
    print(run_log.strip())
    print("PREDICTOR_VALIDATION_PASS", args.out)


if __name__ == "__main__":
    main()
