#!/usr/bin/env python3
"""展开实际 SoC/FPGA 包装，检查 IA 存储开关传到 NPU 和加载器。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.capacity.elaboration import constant_parameters
from scripts.rtl.source_files import input_files, with_dependencies


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--verilator", default="verilator")
    args = parser.parse_args()
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=True)
    fpga = ROOT / "fpga/vivado/tflm_ai_dsa_soc"
    cases = [
        ("fpga_top_behav_smoke_tb", [fpga / "sim/fpga_top_behav_smoke_tb.sv",
                                     fpga / "rtl/fpga_top.sv", fpga / "rtl/clk_wiz_0_sim_stub.sv"],
         ["-GCPU_MEM_DP=64"], ["fpga_top_behav_smoke_tb", "fpga_top", "soc_top"]),
        ("axil_top_with_ram", [ROOT / "rtl/axi_top/axil_top_with_ram.sv",
                                ROOT / "test/models/soc_axi_ram.sv"],
         ["-GMEM_DP=64", "-GMEM_INIT_EN=0"], ["axil_top_with_ram"]),
    ]
    before = {}
    results = []
    for top, sources, options, wrappers in cases:
        sources = [*sources, ROOT / "picorv32/picosoc/simpleuart.v"]
        sources = with_dependencies(sources, ROOT)
        for path in input_files(sources, ROOT):
            before[str(path.relative_to(ROOT))] = digest(path)
        for compact in (0, 1):
            directory = output / f"{top}_compact{compact}"
            directory.mkdir(exist_ok=True)
            tree_path = directory / "elaborated.tree.json"
            command = [args.verilator, "--json-only", "--timing", "-Wno-fatal",
                       "-DSYNTHESIS", "-DASIC_SYNTHESIS", "-DGEMPACT_PS_COMPRESS",
                       "-DGEMMORA_PS_POOL_BYTES=49152", "-DGEMMORA_PS_FORCE_RAW",
                       "--top-module", top, "--json-only-output", str(tree_path),
                       "--Mdir", str(directory / "obj"), "-GSIZE=16", "-GBUS_WIDTH=64",
                       "-GSHARED_BANK_BYTES=8192", "-GSHARED_BANK_COUNT=7",
                       f"-GIA_COMPACT_ENABLE={compact}", *options,
                       "-I" + str(ROOT / "include"), "-I" + str(ROOT / "asic/rtl"),
                       *map(str, sources)]
            log = directory / "elaboration.log"
            with log.open("w") as stream:
                subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, check=True)
            tree = json.loads(tree_path.read_text())
            parameters = {name: constant_parameters(tree, name, ("IA_COMPACT_ENABLE",))["IA_COMPACT_ENABLE"]
                          for name in [*wrappers, "npu_axil_top", "npu_top"]}
            parameters["ia_loader.COMPACT_S8"] = constant_parameters(tree, "ia_loader", ("COMPACT_S8",))["COMPACT_S8"]
            if any(value != compact for value in parameters.values()):
                raise ValueError(f"IA_COMPACT_ENABLE parameter mismatch: {parameters}")
            warnings = [line for line in log.read_text().splitlines()
                        if line.startswith(("%Error", "%Warning-PINMISSING", "%Warning-MODDUP"))]
            if warnings:
                raise ValueError("Incomplete hierarchy: " + "\n".join(warnings))
            results.append(dict(top=top, ia_compact_enable=compact, parameters=parameters,
                                command=command, log_sha256=digest(log)))
            tree_path.unlink()
    changed = [name for name, value in before.items() if digest(ROOT / name) != value]
    if changed:
        raise ValueError("RTL inputs changed during parameter checks: " + ", ".join(changed))
    report = dict(passed=True, scope="Verilator hierarchy and constant parameters; clock model is simulation-only",
                  source_sha256=before, cases=results)
    (output / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(dict(passed=True, cases=len(results))))


if __name__ == "__main__":
    main()
