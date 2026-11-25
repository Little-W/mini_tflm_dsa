#!/usr/bin/env python3
"""使用完整 FPGA 功能模型证明 IA 算术映射后的所有输出。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/fpga"))
from open_fpga_synth import run_stage
from map_abc9_batches import LIBRARIES, discover_profile
from check_write_format import extract as extract_write_format


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_restore_source(source, name="ia_restore_arithmetic"):
    first = source.index("    for (genvar lane = 0; lane < SIZE; lane++) begin : g_lane",
                         source.index("if (p_compact_supported) begin : g_read_register"))
    last = source.index("  end else begin : g_read_direct", first)
    body = source[first:last]
    body = body.replace("read_metadata_q[1].valid", "i_enable")
    body = body.replace("read_metadata_q[p_read_stages-1].offset", "i_offset")
    body = body.replace("read_metadata_q[p_read_stages-1].compact", "i_compact")
    body = body.replace("ram_rd_raw_data[lane]", "i_data[lane]")
    body = body.replace("ram_rd_data[lane]", "o_data[lane]")
    return f"""module {name} #(
    parameter integer p_compact_offset_width=9, SIZE=16, DATA_WIDTH=16
)(
    input logic clk, i_enable, i_compact,
    input logic signed [p_compact_offset_width-1:0] i_offset,
    input logic signed [DATA_WIDTH-1:0] i_data [SIZE],
    output logic signed [DATA_WIDTH-1:0] o_data [SIZE]
);
    localparam int p_sum_width = ((p_compact_offset_width > 8) ? p_compact_offset_width : 8) + 1;
    localparam int p_restore_width = (p_sum_width < DATA_WIDTH) ? p_sum_width : DATA_WIDTH;
""" + body + "\nendmodule\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cases", nargs="+", choices=("address", "write", "restore"),
                        default=["address", "write", "restore"])
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    import pyosys
    env = dict(os.environ)
    env["PATH"] = str(Path(pyosys.__file__).parent) + os.pathsep + env.get("PATH", "")
    (out / "profile").mkdir(exist_ok=True)
    profile = discover_profile(out / "profile", env)
    cache = ROOT / "rtl/npu/loaders/ia_loader_cache_mgr.sv"
    address = ROOT / "rtl/npu/loaders/ia_address_add.sv"
    common = ROOT / "rtl/common/parallel_prefix_add.sv"
    write_source, restore_source = out / "write.sv", out / "restore.sv"
    write_source.write_text(extract_write_format(cache.read_text(), "ia_write_arithmetic"))
    restore_source.write_text(read_restore_source(cache.read_text()))
    cases = {
        "address": ("ia_address_add", [address, common]),
        "write": ("ia_write_arithmetic", [write_source]),
        "restore": ("ia_restore_arithmetic", [restore_source, common]),
    }
    hashes = {str(path.relative_to(ROOT)): digest(path) for path in (cache, address, common)}
    summary = dict(passed=False, source_sha256=hashes,
                   primitive_library_sha256=digest(Path(pyosys.__file__).parent / "share/xilinx/cells_sim.v"),
                   profile=profile, cases={})
    for label in args.cases:
        top, sources = cases[label]
        folder = out / label
        folder.mkdir(exist_ok=True)
        # 与生产展开使用相同的层次选项，保留原生部分和的综合属性。
        read_source = "read_slang --best-effort-hierarchy --top " + top + " -DSYNTHESIS=1 " + " ".join(map(str, sources))
        stages = []

        def stage(name, commands):
            script, log = folder / (name + ".ys"), folder / (name + ".log")
            script.write_text("\n".join(commands) + "\n")
            timing = run_stage(script, log, env)
            stages.append(dict(name=name, passed=True, **timing))
            return log.read_text()

        stage("prepare", [read_source, "flatten -noscopeinfo",
              f"synth_xilinx -top {top} -family xc7 -noiopad -noclkbuf -flatten -run begin:map_luts",
              "bufnorm -conn", "check -assert", "write_rtlil " + str(folder / "pre_lut.il")])
        stage("map", ["read_rtlil " + str(folder / "pre_lut.il"), *LIBRARIES,
              "bufnorm -conn", "check -assert", *profile["prefix"],
              "bufnorm -conn", "check -assert", profile["abc9"],
              "bufnorm -conn", "check -assert", *profile["suffix"],
              "bufnorm -conn", "check -assert", "blackbox =A:whitebox",
              "setattr -mod -unset keep_hierarchy", "setattr -unset keep_hierarchy",
              "flatten -noscopeinfo", "opt_clean", "check -assert",
              "write_json " + str(folder / "mapped.json"),
              "write_rtlil " + str(folder / "mapped.il")])
        mapped = json.loads((folder / "mapped.json").read_text())["modules"][top]
        if any(cell["type"].startswith("$") for cell in mapped["cells"].values()):
            raise RuntimeError("Arithmetic mapping contains internal cells")
        content = stage("equivalence", [read_source,
              "setattr -mod -unset keep_hierarchy", "setattr -unset keep_hierarchy",
              f"prep -top {top} -flatten",
              "async2sync", "opt -full", "rename -hide w:* w:*data_q %d", "rename -top reference", "design -stash reference",
              "read_rtlil " + str(folder / "mapped.il"), "delete =A:blackbox",
              "read_verilog -overwrite +/xilinx/cells_sim.v", f"rename {top} current",
              "setattr -mod -unset keep_hierarchy", "setattr -unset keep_hierarchy",
              "hierarchy -top current", "flatten -wb",
              "proc", "memory_map", "async2sync", "opt -full", "rename -hide w:* w:*data_q %d", "design -stash current",
              "design -copy-from reference -as reference reference",
              "design -copy-from current -as current current",
              "equiv_make reference current proof", "hierarchy -top proof",
              "equiv_simple -seq 3", "opt_clean", "equiv_induct -seq 5", "equiv_status -assert"])
        count = re.search(r"Of those cells (\d+) are proven and 0 are unproven", content)
        outputs = sum(len(p["bits"]) for p in mapped["ports"].values() if p["direction"] == "output")
        if not count or int(count[1]) < outputs:
            raise RuntimeError("Arithmetic output equivalence is incomplete")
        from netlist_metrics import resources
        mapped_resources = resources(mapped["cells"])
        if label == "address" and mapped_resources["dsp48e1"] == 0:
            raise RuntimeError("Address mapping requires inferred DSP arithmetic")
        summary["cases"][label] = dict(passed=True, compared_output_bits=outputs,
                                       resources=mapped_resources, stages=stages,
                                       mapped_sha256=digest(folder / "mapped.json"))
        summary["passed"] = all(item["passed"] for item in summary["cases"].values())
        (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps(dict(case=label, passed=True, compared_output_bits=outputs,
                              dsp48e1=summary["cases"][label]["resources"]["dsp48e1"])), flush=True)
    if hashes != {str(path.relative_to(ROOT)): digest(path) for path in (cache, address, common)}:
        raise RuntimeError("RTL changed during mapped arithmetic verification")


if __name__ == "__main__":
    main()
