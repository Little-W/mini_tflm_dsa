#!/usr/bin/env python3
"""核对描述符选择修改的形式证明、窗口行为和联合映射源码。"""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DMA = "rtl/npu/dma/axi_dual_block_dma.sv"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    build = args.build.resolve()
    names = {"formal": "formal/summary.json", "window": "window_fpga/summary.json",
             "boundary": "window_boundary/summary.json", "paths": "paths.json"}
    data = {name: json.loads((build / path).read_text()) for name, path in names.items()}
    source_hash = digest(ROOT / DMA)
    for name in ("formal", "window", "boundary"):
        if not data[name]["passed"]:
            raise RuntimeError("A required functional check is incomplete")
    if not data["window"]["resident_stream_cycle_equivalent"] or not data["boundary"]["cycle_identical"]:
        raise RuntimeError("Cycle comparison incomplete")
    if data["formal"]["source_sha256"][DMA] != source_hash or data["boundary"]["source_sha256"][DMA] != source_hash:
        raise RuntimeError("Formal and boundary sources differ")
    for name, value in data["formal"]["source_sha256"].items():
        if digest(ROOT / name) != value:
            raise RuntimeError("Formal source differs from the current RTL")
    for path, value in data["window"]["source_sha256"].items():
        if digest(Path(path)) != value:
            raise RuntimeError("FPGA model source changed")
    window_sources = {"rtl/" + path.rsplit("/rtl/", 1)[1]: value
                      for path, value in data["window"]["source_sha256"].items() if "/rtl/" in path}
    if window_sources[DMA] != source_hash:
        raise RuntimeError("FPGA model differs from the formal source")
    joint = {}
    for label in ("reference", "current"):
        item = data["paths"][label]
        summary = json.loads((build / "joint" / label / "summary.json").read_text())
        if item["mapped_sha256"] != summary["mapped_sha256"] or item["pre_lut_sha256"] != summary["pre_lut_sha256"]:
            raise RuntimeError("Path analysis uses a different mapped source")
        if not summary["cache_included"] or not summary["predictor_included"] or not summary["paths"]["graph_complete"]:
            raise RuntimeError("Joint mapping scope is incomplete")
        joint[label] = dict(resources=item["resources"], complete_max=item["complete_max"],
            source_sha256=item["source_sha256"], mapped_sha256=item["mapped_sha256"],
            pre_lut_sha256=item["pre_lut_sha256"], interface_boundaries=summary["interface_boundaries"],
            paths={name: dict(cells=path["longest_register_path_cells"], graph_complete=path["graph_complete"],
                             longest=path["register_to_register_paths"][:1]) for name, path in item["paths"].items()},
            remaining_long_paths=[path for path in summary["paths"]["distinct_register_path_groups"]
                                  if path["combinational_cells"] > 15])
    if joint["current"]["source_sha256"][DMA] != source_hash:
        raise RuntimeError("Joint mapping source differs from the functional checks")
    changes = {name for name, value in joint["current"]["source_sha256"].items()
               if joint["reference"]["source_sha256"].get(name) != value}
    if changes != {DMA}:
        raise RuntimeError("Joint mapping has additional RTL changes")
    for name, value in joint["current"]["source_sha256"].items():
        if digest(ROOT / name) != value:
            raise RuntimeError("Joint mapping source changed")
    window = data["window"]
    result = dict(functional_checks_passed=True, same_source_verified=True,
        reference_commit=data["formal"]["reference_ref"], source_sha256={DMA: source_hash},
        formal=data["formal"], window=dict(passed=True, fpga=window["fpga"], tests=window["tests"],
            resident_stream_cycles=window["resident_stream_cycles"],
            resident_stream_cycle_equivalent=True,
            resident_stream_sha256=window["resident_stream_sha256"],
            executable_sha256=window["executable_sha256"], reference_ref=window["reference_ref"]),
        boundary=data["boundary"], joint=joint,
        artifact_sha256={name: digest(build / path) for name, path in names.items()},
        tool_sha256={str(path.relative_to(ROOT)): digest(path) for path in
            [*sorted((ROOT / "test/frontend_pending_select").glob("*.py")),
             ROOT / "test/frontend_ia_depth/window_boundary.py",
             ROOT / "test/window_descriptor_stage/synthesis.py",
             ROOT / "test/window_dma/run.py", ROOT / "scripts/fpga/netlist_metrics.py",
             ROOT / "scripts/fpga/lut_dependencies.py"]})
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(dict(functional_checks_passed=True, source_sha256=source_hash,
        logic_lut_change=joint["current"]["resources"]["logic_lut_cells"] -
                         joint["reference"]["resources"]["logic_lut_cells"]), ensure_ascii=False))


if __name__ == "__main__":
    main()
