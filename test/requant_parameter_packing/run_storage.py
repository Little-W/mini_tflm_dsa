#!/usr/bin/env python3
"""验证移位量成对存储的四态数据、同步读取、尾部和取消行为。"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

from support import ROOT, RTL, amount_storage

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "scripts/fpga"))
from open_fpga_synth import run_stage


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--depths", type=int, nargs="+", default=[1, 2, 3, 7, 8, 63, 128, 255, 256, 257, 512])
    parser.add_argument("--models", nargs="+", choices=["rtl", "asic"], default=["rtl", "asic"])
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    names = [RTL, Path("rtl/common/regfile.v"), Path("asic/rtl/smic40_sram_1r1w.sv"),
             Path("test/asic_regfile/sram_model.sv"), Path("test/requant_group_buffer_npu/sram_blackboxes.sv"),
             Path("test/requant_parameter_packing/tb_storage.sv")]
    inputs = {}
    for name in names:
        target = out / "inputs" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / name).read_bytes())
        inputs[name] = target
    wrapper = out / "amount_storage.sv"
    wrapper.write_text(amount_storage(inputs[RTL].read_text()))
    report = {"passed": False, "source_sha256": {str(name): digest(path) for name, path in inputs.items()},
              "wrapper_sha256": digest(wrapper), "profiles": []}
    for model in args.models:
        for depth in args.depths:
            folder = out / f"{model}_d{depth}"
            folder.mkdir(exist_ok=True)
            executable = folder / "simulation.vvp"
            command = ["iverilog", "-g2012", "-s", "tb_storage", f"-Ptb_storage.p_depth={depth}",
                       "-o", str(executable), str(wrapper), str(inputs[Path("rtl/common/regfile.v")]),
                       str(inputs[Path("test/requant_parameter_packing/tb_storage.sv")])]
            if model == "asic":
                command += ["-DASIC_SRAM", str(inputs[Path("asic/rtl/smic40_sram_1r1w.sv")]),
                            str(inputs[Path("test/asic_regfile/sram_model.sv")])]
            with (folder / "compile.log").open("w") as stream:
                subprocess.run(command, check=True, stdout=stream, stderr=subprocess.STDOUT)
            result = subprocess.run(["vvp", str(executable)], capture_output=True, text=True)
            (folder / "run.log").write_text(result.stdout + result.stderr)
            result.check_returncode()
            line = next(line for line in result.stdout.splitlines() if line.startswith("PACKING_PASS"))
            record = {key: int(value) for key, value in re.findall(r"(\w+)=(\d+)", line)}
            record.update(model=model, passed=True)
            if model == "asic":
                script, mapped = folder / "structure.ys", folder / "structure.json"
                sources = [wrapper, inputs[Path("rtl/common/regfile.v")],
                           inputs[Path("asic/rtl/smic40_sram_1r1w.sv")],
                           inputs[Path("test/requant_group_buffer_npu/sram_blackboxes.sv")]]
                script.write_text("read_slang --top amount_storage -D ASIC_SRAM=1 "
                                  "--blackboxed-module RAMTP128X16 --blackboxed-module RAMTP1024X16 "
                                  f"-GBANK_DEPTH={depth} " + shlex.join(map(str, sources)) +
                                  "\nprep -top amount_storage -flatten\nopt_clean\nwrite_json " + shlex.quote(str(mapped)) + "\n")
                run_stage(script, folder / "structure.log", dict(os.environ))
                cells = json.loads(mapped.read_text())["modules"]["amount_storage"]["cells"]
                macros = Counter(cell["type"] for cell in cells.values() if cell["type"].startswith("RAMTP"))
                record["macro_instances"] = dict(macros)
                record["logical_bits"] = 7 * depth
                record["values_per_word"] = 2 if depth > 128 else 1
                record["stored_bits"] = 7 * record["values_per_word"] * ((depth + record["values_per_word"] - 1) // record["values_per_word"])
                record["physical_sram_bits"] = 2048 * macros["RAMTP128X16"] + 16384 * macros["RAMTP1024X16"]
                if depth == 256 and macros != Counter({"RAMTP128X16": 1}):
                    raise RuntimeError("256 条移位量应使用一个 128×16 SRAM")
            report["profiles"].append(record)
            print(json.dumps(record), flush=True)
            (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    report["passed"] = True
    (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
