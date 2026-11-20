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

from geometry_oracle import Current, Geometry, INF, ROOT, predict, relative, sha256

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source


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
    parser.add_argument("--reference-ref", help="Compare every public output with this Git revision")
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
    boundaries = [
        ("large_padding_dilation", replace(base, input_h=16, input_w=16,
            kernel_h=5, kernel_w=5, output_h=3, output_w=3,
            dilation_h=65535, dilation_w=65535, pad_top=65535, pad_left=65535,
            r=1, groups=2), (0, 1, 2, 3, 15), (0, 1, 2, 3, 15)),
        ("large_stride_mask", replace(base, input_h=65535, input_w=1,
            kernel_h=1, kernel_w=1, output_h=65535, output_w=1,
            stride_h=32768, stride_w=1, dilation_h=1, dilation_w=1,
            pad_top=65535, pad_left=0, r=1, groups=2),
            (0, 1, 32768, 32769, 65534), (0,)),
    ]
    for name, g, ys, xs in boundaries:
        if g.unsupported_reasons():
            raise AssertionError((name, g.unsupported_reasons()))
        boundary_vectors = []
        for iy in ys:
            for ix in xs:
                for group in range(2):
                    for position in (0, 1, 2):
                        current = Current(position, 0, group)
                        boundary_vectors.append(dict(input_y=iy, input_x=ix, channel=0,
                            current_p=position, current_q=0, current_group=group,
                            expected_next_rank=predict(g, current, iy, ix, 0).next_rank))
        cases.append(dict(case=name, source="coordinate width and signed boundary model",
                          geometry=asdict(g), enabled=True, bypass=False, vectors=boundary_vectors))
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
    sources = [ROOT / "rtl/npu/conv/conv_im2col_pkg.sv", ROOT / "rtl/common/onehot_check.sv",
               ROOT / "rtl/npu/dma/cache/conv_next_use_predictor.sv", HERE / "predictor_tb.sv"]
    if args.reference_ref:
        reference = args.build / "reference_predictor.sv"
        original = read_rtl_source(args.reference_ref +
            ":rtl/npu/dma/cache/conv_next_use_predictor.sv", cwd=ROOT, text=True)
        reference.write_text(original.replace("module conv_next_use_predictor", "module reference_conv_next_use_predictor"))
        comparison = args.build / "predictor_tb.sv"
        tb = (HERE / "predictor_tb.sv").read_text()
        check = '''
  logic reference_cfg_eligible, reference_cfg_busy, reference_enabled, reference_busy, reference_done;
  logic [31:0] reference_next_rank;
  integer compared_cycles=0;
  reference_conv_next_use_predictor u_reference (
    .cfg_eligible(reference_cfg_eligible), .cfg_busy(reference_cfg_busy), .enabled(reference_enabled),
    .busy(reference_busy), .done(reference_done), .next_rank(reference_next_rank), .*);
  always @(posedge clk) begin
    #2;
    if(rst_n) begin
      compared_cycles++;
      if({cfg_eligible,cfg_busy,enabled,busy,done,next_rank} !==
         {reference_cfg_eligible,reference_cfg_busy,reference_enabled,reference_busy,reference_done,reference_next_rank})
        $fatal(1,"predictor public output mismatch cycle=%0d",compared_cycles);
    end
  end
'''
        tb = tb.replace("  conv_next_use_predictor dut (.*);", "  conv_next_use_predictor dut (.*);\n" + check)
        tb = tb.replace("    $finish;", '    @(negedge clk);\n    $display("PREDICTOR_CYCLE_COMPARE_PASS cycles=%0d",compared_cycles);\n    $finish;')
        comparison.write_text(tb)
        sources[-1] = comparison
        sources.append(reference)
    source_hashes = {relative(path): sha256(path) for path in sources + [Path(__file__), HERE / "geometry_oracle.py"]}
    obj_dir = args.build / "obj_dir"
    binary = obj_dir / "Vpredictor_tb"
    command([args.verilator, "--binary", "--timing", "--assert", "-DCONV_ASSERT", "-DNPU_SIM_ASSERT", "-Wno-fatal",
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
    if args.reference_ref:
        comparison = next(line for line in run_log.splitlines() if line.startswith("PREDICTOR_CYCLE_COMPARE_PASS"))
        report.update(reference_ref=args.reference_ref, cycle_comparison=comparison,
                      public_outputs_cycle_equivalent=True)
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
