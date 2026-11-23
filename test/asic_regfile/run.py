#!/usr/bin/env python3
"""检查 SRAM 分段存储的四态行为、逻辑容量和宏实例数量。"""
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

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "scripts/fpga"))
from open_fpga_synth import run_stage

PROFILES = [
    # 位宽、深度、写入分段、读取端口、同步读取、预期128行宏数、预期1024行宏数。
    (16, 48, 16, 1, 1, 1, 0),
    (64, 512, 8, 1, 1, 0, 8),
    (32, 256, 32, 1, 1, 4, 0),
    (7, 256, 7, 1, 1, 2, 0),
    (32, 256, 32, 2, 1, 8, 0),
    (16, 384, 16, 1, 1, 3, 0),
    (16, 385, 16, 1, 1, 0, 1),
    (16, 1100, 16, 1, 1, 0, 2),
    (19, 128, 19, 1, 1, 2, 0),
    (32, 256, 8, 1, 1, 8, 0),
    (8, 130, 8, 1, 1, 0, 0),
    (1, 128, 1, 7, 1, 0, 0),
    (32, 64, 8, 1, 1, 0, 0),
    (64, 512, 8, 1, 0, 0, 0),
    (513, 1024, 513, 1, 1, 0, 33),
]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--simulation-only", action="store_true")
    parser.add_argument("--profiles", nargs="+", type=int,
                        help="选择 PROFILES 中的配置序号，省略时检查全部配置")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    files = [ROOT / "rtl/common/regfile.v", ROOT / "asic/rtl/smic40_sram_1r1w.sv",
             HERE / "sram_model.sv", HERE / "tb_regfile_asic.sv",
             ROOT / "test/requant_group_buffer_npu/sram_blackboxes.sv"]
    snapshots = []
    for path in files:
        target = out / "inputs" / path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
        snapshots.append(target)
    hashes = {str(path.relative_to(out)): digest(path) for path in snapshots}
    report = {"passed": False, "source_sha256": hashes, "profiles": [],
              "macro_model": "同步功能模型，物理端口同址读写立即报告失败"}
    if args.profiles is not None and any(index < 0 or index >= len(PROFILES) for index in args.profiles):
        parser.error("配置序号超出 PROFILES 范围")
    profiles = PROFILES if args.profiles is None else [PROFILES[index] for index in args.profiles]
    for width, depth, unit, ports, sync, macros128, macros1024 in profiles:
        name = f"w{width}_d{depth}_u{unit}_r{ports}_s{sync}"
        folder = out / name
        folder.mkdir(exist_ok=True)
        binary = folder / "simulation.vvp"
        command = ["iverilog", "-g2012", "-DASIC_SRAM", "-s", "tb_regfile_asic",
                   f"-Ptb_regfile_asic.p_width={width}", f"-Ptb_regfile_asic.p_depth={depth}",
                   f"-Ptb_regfile_asic.p_unit={unit}", f"-Ptb_regfile_asic.p_ports={ports}",
                   f"-Ptb_regfile_asic.p_sync={sync}", "-o", str(binary),
                   *map(str, snapshots[:4])]
        with (folder / "compile.log").open("w") as log:
            subprocess.run(command, check=True, stdout=log, stderr=subprocess.STDOUT)
        result = subprocess.run(["vvp", str(binary)], check=True, capture_output=True, text=True)
        (folder / "simulation.log").write_text(result.stdout + result.stderr)
        line = next(line for line in result.stdout.splitlines() if line.startswith("ASIC_REGFILE_PASS"))
        record = {key: int(value) for key, value in re.findall(r"(\w+)=(\d+)", line)}
        record["passed"] = True
        if not args.simulation_only:
            script = folder / "structure.ys"
            mapped = folder / "structure.json"
            script.write_text(
                "read_slang --top regfile -D ASIC_SRAM=1 --blackboxed-module RAMTP128X16 "
                "--blackboxed-module RAMTP1024X16 "
                f"-Gp_data_width={width} -Gp_depth={depth} -Gp_write_unit={unit} "
                f"-Gp_read_ports={ports} -Gp_sync_read={sync} " +
                shlex.join(map(str, [*snapshots[:2], snapshots[4]])) +
                "\nprep -top regfile -flatten\nopt_clean\nwrite_json " + shlex.quote(str(mapped)) + "\n")
            run_stage(script, folder / "structure.log", dict(os.environ))
            cells = json.loads(mapped.read_text())["modules"]["regfile"]["cells"]
            counts = Counter(cell["type"] for cell in cells.values() if cell["type"].startswith("RAMTP"))
            expected = Counter({"RAMTP128X16": macros128, "RAMTP1024X16": macros1024})
            if counts != +expected:
                raise RuntimeError(f"{name}: 宏数量不符，observed={dict(counts)}, expected={dict(+expected)}")
            record["macro_instances"] = dict(counts)
            record["logical_storage_bits"] = width * depth
            record["physical_storage_bits"] = macros128 * 128 * 16 + macros1024 * 1024 * 16
        report["profiles"].append(record)
        (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(record), flush=True)
    if hashes != {str(path.relative_to(out)): digest(path) for path in snapshots}:
        raise RuntimeError("验证期间源文件发生变化")
    report["passed"] = True
    (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
