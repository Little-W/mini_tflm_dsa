#!/usr/bin/env python3
"""读取完整 IA 模块的写入输入、内部状态与写端口寄存器之间的实际路径。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/fpga"))
from netlist_metrics import connected_paths, register_origins


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def measure(folder):
    mapped, pre_lut = folder / "mapped.json", folder / "pre_lut.il"
    stages = json.loads((folder / "stages.json").read_text())
    if digest(mapped) != stages["03_map_lut"]["output_sha256"]:
        raise RuntimeError("Mapped netlist differs from saved synthesis")
    if digest(pre_lut) != stages["02_pre_lut"]["output_sha256"]:
        raise RuntimeError("Register origins differ from saved synthesis")
    module = json.loads(mapped.read_text())["modules"]["ia_loader"]
    for name, origin in register_origins(pre_lut).items():
        if name in module["cells"]:
            module["cells"][name].setdefault("attributes", {})["fpga_register_origin"] = origin

    def query(start=None, end=None):
        result = connected_paths(module, limit=4, group_limit=4,
                                 root_filter=start, sink_filter=end)
        if not result["graph_complete"]:
            raise RuntimeError("IA path graph is incomplete")
        return result

    metrics = json.loads((folder / "metrics.json").read_text())
    result = {"mapped_sha256": digest(mapped), "pre_lut_sha256": digest(pre_lut),
              "resources": metrics["resources"], "complete_module": query(),
              "source_manifest": json.loads((folder / "manifest.json").read_text())}
    outputs = {
        name: set(module["netnames"]["u_cache_mgr.ram_port_wr_" + name]["bits"])
        for name in ("data", "mask", "addr", "en")
    }
    inputs = ("ext_dma_wr_col_base", "ext_dma_wr_valid", "ext_dma_wr_data")
    for name in inputs:
        for index, bit in enumerate(module["ports"][name]["bits"]):
            # 输入寄存器仅用于路径查询，资源数取自加入查询单元之前的综合网表。
            module["cells"][f"analysis_input_{name}_{index}"] = {
                "type": "FDRE", "attributes": {}, "parameters": {},
                "port_directions": {"D": "input", "Q": "output"},
                "connections": {"D": ["0"], "Q": [bit]},
            }
    result["write_paths"] = {}
    for name in inputs:
        start = lambda n, c, p, prefix="analysis_input_" + name + "_": n.startswith(prefix)
        for output, bits in outputs.items():
            end = lambda n, c, p, selected=bits: p == "D" and bool(
                selected.intersection(c["connections"].get("Q", [])))
            result["write_paths"][name + "_to_ram_" + output] = query(start, end)
    for output, bits in outputs.items():
        start = lambda n, c, p: not n.startswith("analysis_input_")
        end = lambda n, c, p, selected=bits: bool(
            selected.intersection(c["connections"].get("Q", [])))
        result["write_paths"]["register_to_ram_" + output] = query(start, end)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = {name: measure(folder) for name, folder in
              (("reference", args.reference), ("current", args.current))}
    for name, case in result.items():
        print(name, case["resources"]["logic_lut_cells"],
              case["complete_module"]["longest_register_path_cells"],
              {key: value["longest_register_path_cells"]
               for key, value in case["write_paths"].items()}, flush=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
