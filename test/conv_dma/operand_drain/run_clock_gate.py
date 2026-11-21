#!/usr/bin/env python3
"""验证 NPU 通用时钟门控与 Xilinx BUFGCE 的复位、唤醒和应答等待行为。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def unisim_sources(directory: Path) -> list[Path]:
    """接受 Vivado 的 verilog/src 目录或包含两个模型文件的目录。"""
    paths = []
    for name in ("BUFGCE.v", "glbl.v"):
        candidates = [directory / name, directory / "unisims" / name]
        match = next((path for path in candidates if path.is_file()), None)
        if match is None:
            raise FileNotFoundError(f"未找到 Xilinx 官方模型文件：{name}")
        paths.append(match.resolve())
    return paths


def write_interface_shell(source: Path, destination: Path) -> None:
    """保留子模块的公开接口，由测试程序直接施加门控所需事件。"""
    text = source.read_text(encoding="utf-8")
    header_end = re.search(r"^\);", text, re.MULTILINE)
    if header_end is None:
        raise ValueError(f"未找到模块接口结束位置：{source}")
    destination.write_text(text[:header_end.end()] + "\nendmodule\n", encoding="utf-8")


def run_command(command: list[str], log: Path, timeout: int) -> int:
    with log.open("w", encoding="utf-8") as stream:
        stream.write("COMMAND: " + json.dumps(command, ensure_ascii=False) + "\n")
        stream.flush()
        return subprocess.run(
            command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
            timeout=timeout, check=False,
        ).returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verilator", default="verilator")
    parser.add_argument("--iverilog", default="iverilog")
    parser.add_argument("--vvp", default="vvp")
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--mode", choices=("generic", "xilinx", "all"), default="all")
    parser.add_argument("--unisim-dir", type=Path, help="Xilinx 官方 BUFGCE.v 和 glbl.v 所在目录")
    parser.add_argument("--out", type=Path, default=ROOT / "build/conv_dma/clock_gate")
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs 必须为正整数")
    modes = ("generic", "xilinx") if args.mode == "all" else (args.mode,)
    simulators = {}
    for kind, executable in (("generic", args.verilator), ("xilinx", args.iverilog)):
        if kind in modes:
            resolved = shutil.which(executable)
            if resolved is None:
                parser.error(f"未找到仿真程序：{executable}")
            simulators[kind] = resolved
    models = []
    if "xilinx" in modes:
        vvp = shutil.which(args.vvp)
        if vvp is None:
            parser.error("未找到 vvp")
        if args.unisim_dir is None:
            parser.error("BUFGCE 验证需要 --unisim-dir 指定 Xilinx 官方模型目录")
        try:
            models = unisim_sources(args.unisim_dir.resolve())
        except FileNotFoundError as error:
            parser.error(str(error))

    npu = ROOT / "rtl/npu"
    packages = [npu / "conv/conv_im2col_pkg.sv", npu / "conv/vector_engine_pkg.sv"]
    sources = packages + [path for path in sorted(npu.rglob("*.sv")) if path not in packages]
    sources += sorted(npu.rglob("*.v"))
    sources += sorted((ROOT / "rtl/common").glob("*.sv"))
    sources += sorted((ROOT / "rtl/common").glob("*.v"))
    sources += [ROOT / "rtl/axi_top/npu_axil_top.sv", ROOT / "rtl/axi_top/npu_axil_reg_if.sv",
                HERE / "tb_clock_gate_reset.sv"]
    config = ROOT / "test/conv_npu/simulator.vlt"
    dependencies = sources + sorted(npu.rglob("*.svh")) + [config, Path(__file__).resolve()]
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = {
        "scope": "生产 npu_axil_top 的时钟门控：复位相位、单次唤醒和 AXI 应答等待",
        "simulators": simulators,
        "requested_modes": list(modes),
        "passed": False,
        "runs": [],
    }

    for mode in modes:
        folder = output / mode
        folder.mkdir(exist_ok=True)
        selected_models = models if mode == "xilinx" else []
        tracked_sources = dependencies + selected_models
        if mode == "xilinx":
            # 子模块计算与寄存器写入另由事务测试验证，本测试驱动门控的各项输入事件。
            child_sources = [ROOT / "rtl/npu/top/npu_top.sv", ROOT / "rtl/axi_top/npu_axil_reg_if.sv"]
            shells = [folder / "npu_top_ports.sv", folder / "npu_axil_reg_if_ports.sv"]
            for source, destination in zip(child_sources, shells):
                write_interface_shell(source, destination)
            gate_sources = packages + shells + [ROOT / "rtl/axi_top/npu_axil_top.sv",
                                                HERE / "tb_clock_gate_reset.sv"] + models
            tracked_sources = packages + child_sources + [ROOT / "rtl/axi_top/npu_axil_top.sv",
                              HERE / "tb_clock_gate_reset.sv", Path(__file__).resolve()] + models
        hashes = {str(path): sha256(path) for path in tracked_sources}
        if mode == "xilinx":
            binary = folder / "simulation.vvp"
            command = [simulators[mode], "-g2012", "-DXILINX_FPGA", "-s", "tb_clock_gate_reset",
                       "-o", str(binary)] + [str(path) for path in gate_sources]
            run = [vvp, str(binary)]
        else:
            binary = folder / "obj/Vtb_clock_gate_reset"
            command = [simulators[mode], "--binary", "--timing", "--assert", "-sv",
                       "--top-module", "tb_clock_gate_reset", "-Wno-fatal",
                       "--Mdir", str(folder / "obj"), "-j", str(args.jobs),
                       "-I" + str(npu / "ps_compact"), str(config)] + [str(path) for path in sources]
            run = [str(binary)]
        entry = {"mode": mode, "command": command, "source_sha256": hashes,
                 "child_interfaces_only": mode == "xilinx"}
        entry["build_returncode"] = run_command(command, folder / "build.log", 1200)
        entry["sources_unchanged"] = hashes == {str(path): sha256(path) for path in tracked_sources}
        entry["passed"] = False
        if entry["build_returncode"] == 0 and entry["sources_unchanged"]:
            entry["binary_sha256"] = sha256(binary)
            entry["run_returncode"] = run_command(run, folder / "run.log", 60)
            lines = (folder / "run.log").read_text(encoding="utf-8").splitlines()
            entry["observations"] = [line for line in lines if line.startswith("CLOCK_GATE_RESET_PASS")]
            entry["passed"] = entry["run_returncode"] == 0 and bool(entry["observations"])
        report["runs"].append(entry)
        report["passed"] = len(report["runs"]) == len(modes) and all(item["passed"] for item in report["runs"])
        (output / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                             encoding="utf-8")
        print(f"{mode}: {'PASS' if entry['passed'] else 'FAIL'}", flush=True)
        if not entry["passed"]:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
