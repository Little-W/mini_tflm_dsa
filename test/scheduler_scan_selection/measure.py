#!/usr/bin/env python3
"""测量完整帧调度器及帧开放状态到选择结果的实际组合路径。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "test/scheduler_column_depth"))
from support import PARAMETERS, check_sources, digest, prepare_inputs
from selection_paths import analyze_selection


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference", default="92f722e6")
    args = parser.parse_args()
    out = args.out.resolve()
    reference_root = out / "reference_rtl"
    reference_root.mkdir(parents=True, exist_ok=True)
    for name in ("ps_window_scheduler.sv", "ps_scheduler_priority.sv", "ps_scheduler_any.sv"):
        (reference_root / name).write_bytes(subprocess.check_output(
            ["git", "show", args.reference + ":rtl/npu/control/" + name], cwd=ROOT))
    source_root, paths, _, manifest = prepare_inputs(out, reference_root / "ps_window_scheduler.sv")
    cases = {label: dict(top="ps_window_scheduler",
        options=["-DSYNTHESIS=1", "-DXILINX_FPGA=1", *[f"-G{k}={v}" for k, v in PARAMETERS.items()]],
        sources=[str(path.relative_to(source_root))], configuration=PARAMETERS)
        for label, path in paths.items()}
    case_file = out / "cases.json"
    case_file.write_text(json.dumps(cases, indent=2) + "\n")
    subprocess.run([sys.executable, ROOT / "scripts/fpga/open_fpga_synth.py", "--source-root", source_root,
        "--case-config", case_file, "--cases", *cases, "--out", out / "pre", "--through", "pre_lut"],
        cwd=ROOT, check=True)
    report = dict(reference_commit=args.reference, inputs=manifest, parameters=PARAMETERS, cases={})
    for label in cases:
        cost = out / "mapped" / label
        subprocess.run([sys.executable, ROOT / "scripts/fpga/remap_fpga_luts.py", "--source", out / "pre" / label,
            "--out", cost, "--mode", "physical-cost", "--delay-target-ps", "6667", "--wire-delay-ps", "300",
            "--max-lut-inputs", "8", "--discard-abc9-temporaries"], cwd=ROOT, check=True)
        metrics = json.loads((cost / "metrics.json").read_text())
        summary = json.loads((cost / "summary.json").read_text())
        if not metrics["paths"]["graph_complete"] or not summary["functional_verification"]["passed"]:
            raise RuntimeError("调度器组合图或映射功能验证未完成")
        selection = analyze_selection(cost, out / "pre" / label / "pre_lut.il")
        report["cases"][label] = dict(resources=metrics["resources"],
            longest_register_path_cells=metrics["paths"]["longest_register_path_cells"],
            selection_paths=selection, mapped_sha256=digest(cost / "mapped.json"),
            mapping_verification=summary["functional_verification"])
        print(label, metrics["resources"]["logic_lut_cells"], metrics["paths"]["longest_register_path_cells"],
              "frame_open", {key: value["cells"] for key, value in selection["frame_open_paths"].items()}, flush=True)
    check_sources(manifest)
    (out / "measurement.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
