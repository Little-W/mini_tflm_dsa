#!/usr/bin/env python3
"""测量真实帧存储网表中解码计数与其他状态到帧接收端口的组合级数。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/fpga"))
from netlist_metrics import connected_paths, register_origins


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mapped", type=Path, required=True)
    parser.add_argument("--pre-lut", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    module = max(json.loads(args.mapped.read_text())["modules"].values(),
                 key=lambda item: len(item.get("cells", {})))
    for name, origin in register_origins(args.pre_lut).items():
        if name in module["cells"]:
            module["cells"][name].setdefault("attributes", {})["fpga_register_origin"] = origin
    spare = max(bit for net in module["netnames"].values()
                for bit in net["bits"] if isinstance(bit, int))+1
    # 这些分析节点表示实际模块端口，不参与综合，也不计入组合单元数量。
    for name, port in module["ports"].items():
        if name not in ("frame_ready", "ram_read_en", "frame_request", "frame_accept"):
            continue
        for index, bit in enumerate(port["bits"]):
            is_input = port["direction"] == "input"
            module["cells"][f"analysis_{name}_{index}"] = dict(
                type="FDRE", parameters={}, attributes={"fpga_register_origin": name},
                port_directions={"D": "input", "Q": "output"},
                connections={"D": [spare if is_input else bit], "Q": [bit if is_input else spare]})
            spare += 1
    report = {"mapped_sha256": hashlib.sha256(args.mapped.read_bytes()).hexdigest(),
              "pre_lut_sha256": hashlib.sha256(args.pre_lut.read_bytes()).hexdigest(), "paths": {}}
    for field in ("decoded_count", "decoder_inflight", "command_accepted", "frame_request", "frame_accept", "all_state"):
        for sink_port in ("frame_ready", "ram_read_en"):
            root = None if field == "all_state" else lambda name, cell, port, field=field: field in cell.get("attributes", {}).get("fpga_register_origin", "")
            sink = lambda name, cell, port, sink_port=sink_port: name.startswith("analysis_"+sink_port+"_")
            paths = connected_paths(module, root_filter=root, sink_filter=sink, limit=4, group_limit=6)
            assert paths["graph_complete"]
            report["paths"][field+"_to_"+sink_port] = paths
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps({name: result["longest_register_path_cells"] for name, result in report["paths"].items()}))


if __name__ == "__main__":
    main()
