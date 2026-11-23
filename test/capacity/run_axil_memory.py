#!/usr/bin/env python3
"""验证 AXI-Lite 包装使用的 RAM 模型、文件列表和 32/64 位 AXI 事务。"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--verilator", default="verilator")
    args = parser.parse_args()
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=True)
    ram = ROOT / "test/models/soc_axi_ram.sv"
    bench = ROOT / "test/conv_soc_ram/tb_soc_axi_ram_narrow.sv"
    filelist = ROOT / "veri/flist/dut_axil.f"
    environment = ROOT / "veri/flist/env.f"
    files = [(ROOT / "veri/sim" / line.strip()).resolve()
             for line in filelist.read_text().splitlines()
             if line.strip().endswith((".sv", ".v"))]
    definitions = [path for path in files
                   if re.search(r"\bmodule\s+soc_axi_ram\b", path.read_text())]
    if definitions != [ram]:
        raise ValueError("AXI-Lite file list must contain exactly the selected RAM model")
    if "../tb/sram/axi_sim_ram.v" in environment.read_text().splitlines():
        raise ValueError("AXI-Lite environment includes another RAM implementation")
    tracked = [ram, bench, filelist, environment, ROOT / "rtl/axi_top/axil_top_with_ram.sv"]
    before = {str(path.relative_to(ROOT)): digest(path) for path in tracked}
    results = []
    for width in (32, 64):
        directory = output / f"axi{width}"
        directory.mkdir(exist_ok=True)
        command = [args.verilator, "--binary", "--timing", "--assert", "-Wall", "-Wno-fatal",
                   "--top-module", "tb_soc_axi_ram_narrow", f"-GDW={width}", "-GDP=1031",
                   "-GOUTSTANDING=4", "-GFIRST_LATENCY=2", "--Mdir", str(directory / "obj"),
                   "-j", "1", "-CFLAGS", "-std=c++20 -O0", "-MAKEFLAGS", "OPT_FAST=-O0 OPT_SLOW=-O0",
                   str(ram), str(bench)]
        with (directory / "build.log").open("w") as log:
            subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        diagnostics = [line for line in (directory / "build.log").read_text().splitlines()
                       if line.startswith(("%Error", "%Warning-WIDTH", "%Warning-LATCH",
                                           "%Warning-MULTIDRIVEN", "%Warning-PINMISSING", "%Warning-MODDUP"))]
        if diagnostics:
            raise ValueError("RAM diagnostics: " + "\n".join(diagnostics))
        for randomized in (False, True):
            run_command = [str(directory / "obj/Vtb_soc_axi_ram_narrow"), f"+NO_RANDOM={int(not randomized)}"]
            if randomized:
                run_command += ["+RAM_RAND_LAT=1", "+RAM_CMD_MAX_LAT=7", "+RAM_RSP_MAX_LAT=9", "+RAM_W_MAX_LAT=3"]
            run = subprocess.run(run_command, cwd=ROOT, capture_output=True, text=True, timeout=60, check=True)
            log = directory / f"random{int(randomized)}.log"
            log.write_text(run.stdout + run.stderr)
            line = next((line for line in run.stdout.splitlines() if line.startswith("SOC_RAM_NARROW_PASS")), None)
            if line is None:
                raise ValueError("RAM transaction checks did not complete")
            results.append(dict(width=width, randomized=randomized, passed=True,
                                command=run_command, summary=line, log_sha256=digest(log)))
    if before != {str(path.relative_to(ROOT)): digest(path) for path in tracked}:
        raise ValueError("AXI-Lite memory inputs changed during verification")
    report = dict(passed=True, source_sha256=before, cases=results,
                  scope="AXI-Lite file list and its RAM model; wrapper hierarchy is checked by run_ia_build_elaboration.py")
    (output / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(dict(passed=True, cases=len(results))))


if __name__ == "__main__":
    main()
