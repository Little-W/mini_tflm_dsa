#!/usr/bin/env python3
"""核对同一前端源码的形式、窗口数值及联合映射报告。"""
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
    reports = {name: json.loads((build / name / "summary.json").read_text())
               for name in ("formal", "local", "window", "numeric", "joint")}
    formal = reports["formal"]
    current_hash, reference_hash = formal["source_sha256"], formal["reference_sha256"]
    if digest(ROOT / SOURCE) != current_hash:
        raise RuntimeError("Current source differs from the proved frontend")
    for name in ("formal", "local", "window", "numeric"):
        if not reports[name]["passed"]:
            raise RuntimeError("Incomplete verification: " + name)
    for name in ("local", "numeric"):
        if reports[name]["source_sha256"] != current_hash or reports[name]["reference_sha256"] != reference_hash:
            raise RuntimeError("Verification source mismatch: " + name)
    if not reports["numeric"]["cycle_identical"] or not reports["window"]["resident_stream_cycle_equivalent"]:
        raise RuntimeError("Cycle comparison is incomplete")
    joint = reports["joint"]
    for label, expected in (("reference", reference_hash), ("current", current_hash)):
        row = joint[label]
        if row["source_sha256"][SOURCE] != expected:
            raise RuntimeError("Joint source mismatch: " + label)
        for file_name, field in (("mapped.json", "mapped_sha256"), ("pre_lut.il", "pre_lut_sha256")):
            if digest(build / "joint" / label / file_name) != row[field]:
                raise RuntimeError("Joint mapped data changed: " + label + "/" + file_name)
        if any(not path["graph_complete"] for path in row["paths"].values()):
            raise RuntimeError("Incomplete joint connectivity")
    changed = {name for name, value in joint["current"]["source_sha256"].items()
               if joint["reference"]["source_sha256"].get(name) != value}
    if changed != {SOURCE}:
        raise RuntimeError("Joint comparison changes additional RTL sources")
    report = dict(passed=True, reference_commit=formal["reference_commit"],
        source_sha256=current_hash, reference_sha256=reference_hash,
        isolated_changed_source=SOURCE, additional_register_bits=0, additional_cycles=0,
        formal=formal, local=reports["local"], window=reports["window"],
        numeric=reports["numeric"], joint=joint,
        reports_sha256={name: digest(build / name / "summary.json") for name in reports},
        scripts_sha256={path.name: digest(path) for path in sorted(Path(__file__).parent.iterdir())
                        if path.suffix in (".py", ".cpp")})
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"passed": True, "source_sha256": current_hash,
        "joint_logic_delta": joint["current"]["resources"]["logic_lut_cells"] - joint["reference"]["resources"]["logic_lut_cells"],
        "joint_write_data_depth": joint["current"]["paths"]["frontend_to_ia_write_data"]["longest_register_path_cells"]}))


if __name__ == "__main__":
    main()
