#!/usr/bin/env python3
"""汇总同源前端范围逻辑的正式证明、实际输出路径与窗口周期检查。"""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = "rtl/npu/conv/conv_im2col_frontend.sv"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    build = args.build.resolve()
    names = ("formal", "local_range", "window", "numeric")
    reports = {name: json.loads((build / name / "summary.json").read_text()) for name in names}
    proof = reports["formal"]
    current_hash, reference_hash = proof["source_sha256"], proof["reference_sha256"]
    if digest(ROOT / SOURCE) != current_hash:
        raise RuntimeError("The current frontend differs from the verified source")
    for name, report in reports.items():
        if not report["passed"]:
            raise RuntimeError("Incomplete verification: " + name)
    for name in ("local_range", "numeric"):
        if reports[name]["source_sha256"] != current_hash or reports[name]["reference_sha256"] != reference_hash:
            raise RuntimeError("Verification source mismatch: " + name)
    if not proof["compositional_range_merge"] or len(proof["cases"]) != 8 or len(proof["merge_cases"]) != 4:
        raise RuntimeError("The complete range output proof is required")
    if not reports["numeric"]["cycle_identical"] or not reports["window"]["resident_stream_cycle_equivalent"]:
        raise RuntimeError("Cycle comparisons are incomplete")
    window_hashes = {"rtl/" + path.rsplit("/rtl/", 1)[1]: value
        for path, value in reports["window"]["source_sha256"].items() if "/rtl/" in path}
    if window_hashes[SOURCE] != current_hash:
        raise RuntimeError("The window model differs from the formal proof")
    local = reports["local_range"]
    if local["outputs"] != "group_range_next[5]":
        raise RuntimeError("The mapped outputs must include the complete four-bit range")
    for label, report in local["cases"].items():
        for name, field in (("mapped.json", "mapped_sha256"), ("pre_lut.il", "pre_lut_sha256")):
            if digest(build / "local_range" / label / name) != report[field]:
                raise RuntimeError("Mapped data changed: " + label + "/" + name)
        if not report["all_paths"]["graph_complete"] or not report["mask_paths"]["graph_complete"]:
            raise RuntimeError("The mapped dependency graph is incomplete")
    report = dict(passed=True, reference_commit=proof["reference_commit"],
        source_sha256=current_hash, reference_sha256=reference_hash,
        isolated_changed_source=SOURCE, added_register_bits=0, added_interface_cycles=0,
        complete_range_output_proved=True, formal=proof, local_range=local,
        window=reports["window"], numeric=reports["numeric"],
        report_sha256={name: digest(build / name / "summary.json") for name in names},
        scripts_sha256={path.name: digest(path) for path in sorted(Path(__file__).parent.glob("*.py"))})
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(dict(passed=True, source_sha256=current_hash,
        logic_luts=local["cases"]["current"]["resources"]["logic_lut_cells"],
        longest_register_path_cells=local["cases"]["current"]["all_paths"]["longest_register_path_cells"],
        mask_path_cells=local["cases"]["current"]["mask_paths"]["longest_register_path_cells"])))


if __name__ == "__main__":
    main()
