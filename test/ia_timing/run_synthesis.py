#!/usr/bin/env python3
"""以外置数据 RAM 配置比较 IA 加载器的面积及寄存器之间的路径。"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference-rev", default="aa2ef9a3")
    parser.add_argument("--count-width", type=int, default=32)
    parser.add_argument("--synth-script", type=Path, default=ROOT / "scripts/fpga/open_fpga_synth.py")
    parser.add_argument("--lock-file", type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference = out / "reference"
    reference.mkdir(exist_ok=True)
    modules = ("ia_loader", "ia_loader_ctrl", "ia_loader_cache_mgr")
    for module in modules:
        source = read_rtl_source(args.reference_rev +
                                          ":rtl/npu/loaders/" + module + ".sv", cwd=ROOT, text=True)
        (reference / (module + ".sv")).write_text(source)
    cases = {}
    for label in ("reference", "candidate"):
        paths = [str(reference / (name + ".sv")) if label == "reference" else
                 "rtl/npu/loaders/" + name + ".sv" for name in modules]
        cases["loader_" + label] = {
            "top": "ia_loader", "options": ["-GSIZE=16", "-GBUS_WIDTH=64", "-GCACHE_BLOCKS=32",
                                               "-GCOUNT_WIDTH=" + str(args.count_width),
                                               "-GEXTERNAL_RAM=1", "-GORDERED_JOB=1"],
            "sources": paths,
            "configuration": "SIZE16 BUS64 CACHE32 COUNT_WIDTH" + str(args.count_width) +
                             " EXTERNAL_RAM1 ORDERED_JOB1",
        }
    case_file = out / "cases.json"
    case_file.write_text(json.dumps(cases, indent=2) + "\n")
    command = [sys.executable, str(args.synth_script.resolve()), "--source-root", str(ROOT),
               "--case-config", str(case_file), "--cases", *cases, "--out", str(out / "results")]
    if args.lock_file:
        command += ["--lock-file", str(args.lock_file.resolve())]
    subprocess.run(command, cwd=ROOT, check=True)
    sys.path.insert(0, str(args.synth_script.resolve().parent))
    from netlist_metrics import connected_paths, register_origins
    for label in cases:
        folder = out / "results" / label
        module = json.loads((folder / "mapped.json").read_text())["modules"]["ia_loader"]
        for name, origin in register_origins(folder / "pre_lut.il").items():
            if name in module["cells"]:
                module["cells"][name].setdefault("attributes", {})["fpga_register_origin"] = origin
        paths = connected_paths(module, limit=20000, group_limit=1000)["register_to_register_paths"]
        prefetch = [item for item in paths if
                    (item["endpoint"].get("register_origin") or "").startswith("prefetch_descriptor")]
        (folder / "prefetch_paths.json").write_text(json.dumps(prefetch[:10], indent=2) + "\n")


if __name__ == "__main__":
    main()
