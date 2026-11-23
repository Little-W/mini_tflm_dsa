#!/usr/bin/env python3
"""统计实际移位量存储的 ASIC 结构及 XC7 综合资源。"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

from support import ROOT, RTL, amount_storage

sys.path.insert(0, str(ROOT / "scripts/fpga"))
from netlist_metrics import analyze, register_origins
from open_fpga_synth import run_stage


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference", default="820c2b18")
    parser.add_argument("--depth", type=int, default=256)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    inputs = {}
    for name in [str(RTL), "rtl/common/regfile.v", "asic/rtl/smic40_sram_1r1w.sv",
                 "test/requant_group_buffer_npu/sram_blackboxes.sv"]:
        path = out / "inputs" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((ROOT / name).read_bytes())
        inputs[name] = path
    original = subprocess.check_output(["git", "show", args.reference+":"+str(RTL)], cwd=ROOT, text=True)
    report = {"passed": False, "reference": args.reference, "logical_depth": args.depth,
              "logical_bits": args.depth * 7, "scope": "单个 IS 移位量 bank，尾部判断输入为独立端口",
              "dc_synthesis_performed": False, "source_sha256": {name: sha(path) for name, path in inputs.items()},
              "reference_rtl_sha256": hashlib.sha256(original.encode()).hexdigest(), "variants": {}}
    for variant, source in [("reference", original), ("packed", inputs[str(RTL)].read_text())]:
        folder = out / variant
        folder.mkdir(exist_ok=True)
        wrapper = folder / "amount_storage.sv"
        wrapper.write_text(amount_storage(source))
        asic_script, asic_json = folder / "asic.ys", folder / "asic.json"
        sources = [wrapper, inputs["rtl/common/regfile.v"], inputs["asic/rtl/smic40_sram_1r1w.sv"],
                   inputs["test/requant_group_buffer_npu/sram_blackboxes.sv"]]
        asic_script.write_text("read_slang --top amount_storage -D ASIC_SRAM=1 "
                              "--blackboxed-module RAMTP128X16 --blackboxed-module RAMTP1024X16 "
                              f"-GBANK_DEPTH={args.depth} " + shlex.join(map(str, sources)) +
                              "\nprep -top amount_storage -flatten\nmemory_map\nopt -full\nwrite_json " +
                              shlex.quote(str(asic_json)) + "\n")
        stage_results = {"asic": run_stage(asic_script, folder / "asic.log", dict(os.environ))}
        cells = json.loads(asic_json.read_text())["modules"]["amount_storage"]["cells"]
        macros = Counter(cell["type"] for cell in cells.values() if cell["type"].startswith("RAMTP"))
        sequential_bits = sum(int(cell["parameters"]["WIDTH"], 2) for cell in cells.values() if "dff" in cell["type"])
        asic = {"macro_instances": dict(macros), "register_bits": sequential_bits,
                "physical_sram_bits": 2048*macros["RAMTP128X16"]+16384*macros["RAMTP1024X16"]}
        pre, mapped = folder / "pre_lut.il", folder / "mapped.json"
        synth = "synth_xilinx -top amount_storage -family xc7 -noiopad -noclkbuf -flatten"
        stages = {
            "pre_lut": f"read_slang --top amount_storage -GBANK_DEPTH={args.depth} " +
                shlex.join(map(str, [wrapper, inputs["rtl/common/regfile.v"]])) +
                "\nread_verilog -lib -specify -overwrite +/xilinx/cells_sim.v\n" +
                "read_verilog -lib -overwrite +/xilinx/cells_xtra.v\n" + synth +
                " -run begin:map_luts\nwrite_rtlil " + shlex.quote(str(pre)) + "\n",
            "map_lut": "read_rtlil " + shlex.quote(str(pre)) +
                "\nread_verilog -lib -specify -overwrite +/xilinx/cells_sim.v\n" +
                "read_verilog -lib -overwrite +/xilinx/cells_xtra.v\n" + synth +
                " -run map_luts:\ncheck -assert\nwrite_json " + shlex.quote(str(mapped)) + "\n",
        }
        for stage, text in stages.items():
            script = folder / (stage + ".ys")
            script.write_text(text)
            stage_results[stage] = run_stage(script, folder / (stage + ".log"), dict(os.environ))
        module = json.loads(mapped.read_text())["modules"]["amount_storage"]
        for name, origin in register_origins(pre).items():
            if name in module["cells"]:
                module["cells"][name].setdefault("attributes", {})["fpga_register_origin"] = origin
        metrics = analyze(module, limit=10, group_limit=10)
        (folder / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
        record = {"asic": asic, "fpga": {"resources": metrics["resources"],
                  "longest_register_path_cells": metrics["paths"]["longest_register_path_cells"]},
                  "wrapper_sha256": sha(wrapper), "mapped_sha256": sha(mapped), "stages": stage_results}
        report["variants"][variant] = record
        print(json.dumps({"variant": variant, **record}), flush=True)
    report["passed"] = True
    (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n")


if __name__ == "__main__":
    main()
