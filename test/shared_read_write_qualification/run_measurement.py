#!/usr/bin/env python3
"""成对综合共享通道存储并测量各请求到实际 RAM 使能的组合级数。"""
import argparse
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = "rtl/npu/buffers/ia_ps_channel_ram.sv"
ROLE = "rtl/npu/buffers/ia_ps_role_ram.sv"
PARAMETERS = dict(p_bank_bytes=8192, p_total_bytes=57344, p_shared_write_stage=1,
                  p_ia_nonempty_writes=1, p_paired_ia_ports=1,
                  p_allow_inactive_return_updates=1)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def call(arguments):
    subprocess.run([str(item) for item in arguments], cwd=ROOT, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", default="d9f7f15a")
    parser.add_argument("--out", type=Path, required=True)
    for name in ("reference-pre", "candidate-pre", "reference-cost", "candidate-cost"):
        parser.add_argument("--" + name, type=Path)
    args = parser.parse_args()
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=True)
    supplied = [args.reference_pre, args.candidate_pre, args.reference_cost, args.candidate_cost]
    if any(supplied) and not all(supplied):
        parser.error("已有测量需要同时指定两份综合目录和两份映射目录")
    if not all(supplied):
        inputs = output / "inputs"
        inputs.mkdir(exist_ok=True)
        original = subprocess.check_output(["git", "show", args.reference + ":" + SOURCE], cwd=ROOT)
        (inputs / "reference.sv").write_bytes(original)
        (inputs / "candidate.sv").write_bytes((ROOT / SOURCE).read_bytes())
        (inputs / "reference_role.sv").write_bytes(subprocess.check_output(
            ["git", "show", args.reference + ":" + ROLE], cwd=ROOT))
        resolve = runpy.run_path(str(ROOT / "scripts/rtl/source_files.py"))["with_dependencies"]
        cases = {}
        for label in ("reference", "candidate"):
            cases[label] = dict(top="ia_ps_channel_ram", configuration="完整共享存储，8192字节物理块及七个存储块",
                                options=["-DSYNTHESIS=1", "-DXILINX_FPGA=1"] +
                                [f"-G{k}={v}" for k, v in PARAMETERS.items()],
                                sources=list(map(str, resolve([inputs / (label + ".sv"),
                                    inputs / "reference_role.sv" if label == "reference" else ROOT / ROLE], ROOT))))
        case_file = inputs / "cases.json"
        case_file.write_text(json.dumps(cases, indent=2) + "\n")
        call([sys.executable, ROOT / "scripts/fpga/open_fpga_synth.py", "--case-config", case_file,
              "--cases", "reference", "candidate", "--out", output / "pre", "--through", "pre_lut"])
        for label in cases:
            call([sys.executable, ROOT / "scripts/fpga/remap_fpga_luts.py",
                  "--source", output / "pre" / label, "--out", output / "cost" / label,
                  "--mode", "physical-cost", "--max-lut-inputs", "8", "--small-lut-area-cost", "1",
                  "--wire-delay-ps", "300", "--delay-target-ps", "6667"])
        args.reference_pre, args.candidate_pre = [output / "pre" / label for label in cases]
        args.reference_cost, args.candidate_cost = [output / "cost" / label for label in cases]
    report = dict(reference=args.reference, parameters=PARAMETERS, mode="physical-cost",
                  max_lut_inputs=8, small_lut_area_cost=1, wire_delay_ps=300, delay_target_ps=6667,
                  cases={})
    for label, pre, cost in (("reference", args.reference_pre, args.reference_cost),
                             ("candidate", args.candidate_pre, args.candidate_cost)):
        call([sys.executable, ROOT / "test/shared_read_write_qualification/measure_paths.py", "--pre", pre, "--cost", cost])
        metrics = json.loads((cost / "metrics.json").read_text())
        paths = json.loads((cost / "targeted_paths.json").read_text())
        manifest = json.loads((pre / "manifest.json").read_text())
        if label == "candidate":
            assert digest(ROOT / SOURCE) in manifest["sources_sha256"].values()
            assert digest(ROOT / ROLE) in manifest["sources_sha256"].values()
        report["cases"][label] = dict(resources=metrics["resources"],
                                      longest_register_path_cells=metrics["paths"]["longest_register_path_cells"],
                                      request_paths={name: value["longest_register_path_cells"]
                                                     for name, value in paths["paths"].items()},
                                      mapped_sha256=paths["mapped_sha256"], pre_lut_sha256=paths["pre_lut_sha256"],
                                      source_sha256=manifest["sources_sha256"])
    (output / "measurement.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({name: {"lut": value["resources"]["lut_sites_nominal_before_packing"],
                            "longest": value["longest_register_path_cells"]}
                      for name, value in report["cases"].items()}))


if __name__ == "__main__":
    main()
