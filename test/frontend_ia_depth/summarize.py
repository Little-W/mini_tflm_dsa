#!/usr/bin/env python3
"""核对前端与 IA 写入优化的源码、证明、周期检查和联合映射。"""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = "rtl/npu/conv/conv_im2col_frontend.sv"
PREDICTOR = "rtl/npu/dma/cache/conv_next_use_predictor.sv"
CACHE = "rtl/npu/loaders/ia_loader_cache_mgr.sv"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def brief_paths(paths):
    return {name: {"cells": item["longest_register_path_cells"],
                   "graph_complete": item["graph_complete"],
                   "path": item["register_to_register_paths"][:1]}
            for name, item in paths.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    build = args.build.resolve()
    hashes = {name: digest(ROOT / name) for name in (FRONTEND, PREDICTOR, CACHE)}
    files = {
        "formal": "frontend_formal/summary.json", "ia_formal": "ia_formal/summary.json",
        "window": "window_fpga/summary.json", "boundary": "window_boundary/summary.json",
        "predictor": "predictor_numeric/summary.json", "ia_interface": "ia_interface/summary.json",
        "ia_shared": "ia_shared/summary.json", "frontend_paths": "frontend_paths.json",
    }
    data = {name: json.loads((build / path).read_text()) for name, path in files.items()}
    if any(not item["passed"] for name, item in data.items() if name != "frontend_paths"):
        raise RuntimeError("A required functional check is incomplete")
    if data["formal"]["source_sha256"] != {name: hashes[name] for name in (FRONTEND, PREDICTOR)}:
        raise RuntimeError("Frontend proof source differs")
    if data["ia_formal"]["source_sha256"][CACHE] != hashes[CACHE]:
        raise RuntimeError("IA formal source differs")
    if data["ia_interface"]["source_sha256"][CACHE] != hashes[CACHE] or \
            data["ia_shared"]["source_sha256"][CACHE] != hashes[CACHE]:
        raise RuntimeError("IA numeric source differs")
    for path, expected in data["window"]["source_sha256"].items():
        if digest(Path(path)) != expected:
            raise RuntimeError("Compiled FPGA window source differs")
    window_hashes = {"rtl/" + path.rsplit("/rtl/", 1)[1]: value for path, value in
                     data["window"]["source_sha256"].items() if "/rtl/" in path}
    if any(window_hashes[name] != hashes[name] for name in (FRONTEND, PREDICTOR)):
        raise RuntimeError("FPGA window model differs from formal source")
    if data["predictor"]["sources"][PREDICTOR] != hashes[PREDICTOR] or \
            data["boundary"]["source_sha256"] != data["formal"]["source_sha256"]:
        raise RuntimeError("Predictor or boundary model source differs")

    frontend, ia = {}, {}
    for label in ("reference", "current"):
        fp = data["frontend_paths"][label]
        fs = json.loads((build / "frontend_joint" / label / "summary.json").read_text())
        if fs["mapped_sha256"] != fp["mapped_sha256"]:
            raise RuntimeError("Frontend path source differs")
        frontend[label] = dict(resources=fp["resources"], paths=brief_paths(fp["paths"]),
            complete_max=fp["complete_max"], source_sha256=fp["source_sha256"],
            mapped_sha256=fp["mapped_sha256"], pre_lut_sha256=fp["pre_lut_sha256"],
            complete_scope_long_paths=[path for path in fs["paths"]["distinct_register_path_groups"]
                                       if path["combinational_cells"] > 15])
        current = json.loads((build / "ia_joint" / label / "summary.json").read_text())
        ia[label] = dict(resources=current["resources"], paths=brief_paths(current["paths"]),
            source_sha256=current["source_sha256"], mapped_sha256=current["mapped_sha256"],
            pre_lut_sha256=current["pre_lut_sha256"], interface_boundaries=current["interface_boundaries"])
    if any(frontend["current"]["source_sha256"][name] != hashes[name] for name in (FRONTEND, PREDICTOR)):
        raise RuntimeError("Frontend mapped source differs")
    if ia["current"]["source_sha256"][CACHE] != hashes[CACHE]:
        raise RuntimeError("IA mapped source differs")
    if {name for name, value in frontend["current"]["source_sha256"].items()
            if frontend["reference"]["source_sha256"].get(name) != value} != {FRONTEND, PREDICTOR}:
        raise RuntimeError("Frontend joint synthesis has additional source changes")
    if {name for name, value in ia["current"]["source_sha256"].items()
            if ia["reference"]["source_sha256"].get(name) != value} != {CACHE}:
        raise RuntimeError("IA joint synthesis has additional source changes")
    exact = json.loads((build / "ia_exact_paths.json").read_text())
    for label in ("reference", "current"):
        if exact[label]["mapped_sha256"] != ia[label]["mapped_sha256"]:
            raise RuntimeError("IA selected-bit path source differs")
        ia[label]["selected_bit_paths"] = brief_paths(exact[label]["paths"])
    result = dict(functional_checks_passed=True, same_source_verified=True,
        reference_commit=data["formal"]["reference_commit"],
        source_sha256=hashes, frontend_joint=frontend, ia_joint=ia,
        verification={name: item for name, item in data.items() if name != "frontend_paths"},
        artifact_sha256={name: digest(build / path) for name, path in files.items()},
        tool_sha256={str(path.relative_to(ROOT)): digest(path) for path in
            [*sorted((ROOT / "test/frontend_ia_depth").glob("*.py")),
             ROOT / "scripts/fpga/netlist_metrics.py", ROOT / "scripts/fpga/lut_dependencies.py",
             ROOT / "test/window_descriptor_stage/synthesis.py"]})
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"functional_checks_passed": True, "source_sha256": hashes,
        "frontend_lut_change": frontend["current"]["resources"]["logic_lut_cells"] -
                               frontend["reference"]["resources"]["logic_lut_cells"],
        "ia_lut_change": ia["current"]["resources"]["logic_lut_cells"] -
                         ia["reference"]["resources"]["logic_lut_cells"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
