#!/usr/bin/env python3
"""综合完整量化模块，记录相同参数下的资源数量和组合路径长度。"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import runpy
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference-rev", default="aa2ef9a")
    parser.add_argument("--bus-width", type=int, default=64)
    parser.add_argument("--lanes", type=int, default=16)
    parser.add_argument("--reuse", type=int, default=32)
    parser.add_argument("--worker", type=Path)
    parser.add_argument("--synthesis-tools", type=Path, default=ROOT / "scripts/fpga/open_fpga_synth.py")
    args = parser.parse_args()
    if args.worker:
        from pyosys import libyosys
        libyosys.run_pass("script " + shlex.quote(str(args.worker)))
        return
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference = out / "reference.sv"
    reference.write_bytes(subprocess.check_output(
        ["git", "show", args.reference_rev + ":rtl/npu/writeback/vec_requant.sv"], cwd=ROOT))
    snapshot = out / "current.sv"
    snapshot.write_bytes((ROOT / "rtl/npu/writeback/vec_requant.sv").read_bytes())
    sources = {"reference": reference, "current": snapshot}
    sys.path.insert(0, str(args.synthesis_tools.parent))
    tools = runpy.run_path(str(args.synthesis_tools))
    depth = tools["logic_depth"]
    import pyosys
    library_directory = Path(pyosys.__file__).parent / "share/xilinx"

    summary = {
        "top": "vec_requant",
        "bus_width": args.bus_width,
        "lanes": args.lanes,
        "max_ia_reuse": args.reuse,
        "enable_s16": True,
        "family": "xc7",
        "timing_scope": "mapped combinational cell depth; no device routing delay",
        "variants": {},
    }
    for label, source in sources.items():
        folder = out / label
        folder.mkdir(exist_ok=True)
        mapped = folder / "mapped.json"
        script = folder / "run.ys"
        primitive_options = ""
        design_sources = [source, ROOT / 'rtl/common/REGFILE.v',
                          ROOT / 'rtl/npu/conv/vector_scalar_multiplier.sv']
        if "primitive_models" in tools:
            primitive_options, primitive_manifest = tools["primitive_models"](
                folder, [str(path) for path in design_sources], library_directory)
        script.write_text(
            f"read_slang --top vec_requant -GBUS_WIDTH={args.bus_width} -GVLEN={args.lanes} "
            f"-GMAX_IA_REUSE={args.reuse} -GENABLE_S16=1 {primitive_options} " +
            ' '.join(shlex.quote(str(path)) for path in design_sources) + "\n"
            "read_verilog -lib -specify -overwrite +/xilinx/cells_sim.v\n"
            "read_verilog -lib -overwrite +/xilinx/cells_xtra.v\n"
            "hierarchy -check -top vec_requant\n"
            "synth_xilinx -top vec_requant -family xc7 -noiopad -noclkbuf -flatten\n"
            "check -assert\n"
            "stat -tech xilinx\n"
            f"write_json {shlex.quote(str(mapped))}\n"
        )
        with (folder / "synthesis.log").open("w") as stream:
            subprocess.run([sys.executable, str(Path(__file__).resolve()), "--out", str(out),
                            "--worker", str(script)], cwd=ROOT, stdout=stream,
                           stderr=subprocess.STDOUT, check=True)
        cells = json.loads(mapped.read_text())["modules"]["vec_requant"]["cells"]
        counts = Counter(cell["type"] for cell in cells.values())
        depth_cells = {name: dict(cell, type="LUT6" if cell["type"] == "LUT6_2" else cell["type"]) for name, cell in cells.items()}
        path = depth(depth_cells)
        for item in path:
            item["type"] = cells[item["cell"]]["type"]
        summary["variants"][label] = {
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "lut_cells": sum(count for kind, count in counts.items() if re.fullmatch(r"LUT[1-6]|LUT6_2", kind)),
            "flip_flops": sum(count for kind, count in counts.items() if kind.startswith(("FDRE", "FDCE", "FDSE", "FDPE"))),
            "dsp48e1": counts["DSP48E1"],
            "longest_combinational_path_cells": len(path),
            "cell_counts": dict(sorted(counts.items())),
            "longest_combinational_path": path,
        }
        (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(label, json.dumps({key: summary["variants"][label][key] for key in
                               ("lut_cells", "flip_flops", "dsp48e1", "longest_combinational_path_cells")}))


if __name__ == "__main__":
    main()
