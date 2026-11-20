#!/usr/bin/env python3
"""读取指定 IA 写数据寄存位的实际跨模块路径。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

from frontend_paths import OriginFile, content

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/fpga"))
from netlist_metrics import connected_paths, register_origins


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--joint", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = {}
    for label in ("reference", "current"):
        folder = args.joint / label
        saved = json.loads((folder / "summary.json").read_text())
        raw = content(folder / "mapped.json")
        if hashlib.sha256(raw).hexdigest() != saved["mapped_sha256"]:
            raise RuntimeError("Mapped IA joint source differs")
        module = json.loads(raw)["modules"]["npu_top"]
        for name, origin in register_origins(OriginFile(folder / "pre_lut.il")).items():
            if name in module["cells"]:
                module["cells"][name].setdefault("attributes", {})["fpga_register_origin"] = origin
        removed = {item["cell"] for item in saved["interface_boundaries"]}
        module["cells"] = {name: cell for name,cell in module["cells"].items() if name not in removed}
        paths = {}
        start = re.compile(r"u_frontend\.state \[4\]$")
        for index in (140, 148):
            end = re.compile(r"u_ia_loader\.u_cache_mgr\.ram_port_wr_data \[" + str(index) + r"\]$")
            paths[str(index)] = connected_paths(module, limit=2, group_limit=2,
                root_filter=lambda n,c,p: bool(start.search(c.get("attributes", {}).get("fpga_register_origin", ""))),
                sink_filter=lambda n,c,p: p == "D" and bool(end.search(c.get("attributes", {}).get("fpga_register_origin", ""))))
            if not paths[str(index)]["graph_complete"]:
                raise RuntimeError("IA target path graph is incomplete")
        result[label] = dict(paths=paths, mapped_sha256=saved["mapped_sha256"], source_sha256=saved["source_sha256"])
        print(label, {name: item["longest_register_path_cells"] for name,item in paths.items()}, flush=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
