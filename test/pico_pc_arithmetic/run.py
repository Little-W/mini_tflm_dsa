#!/usr/bin/env python3
"""验证 PC 地址算术的完整 CPU 行为，并测量生产配置的资源和组合深度。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
UPSTREAM_COMMIT = "ef203c2b0a3fb793280f5114941416c425c5b461"
UPSTREAM_SOURCE_SHA256 = "0836050971b3c6cdd28ac3b1e5719a67fb645161912bef1e472e63995ceb0622"
PARAMETERS = {
    "ENABLE_COUNTERS": 1, "ENABLE_COUNTERS64": 0, "ENABLE_REGS_16_31": 1,
    "ENABLE_REGS_DUALPORT": 1, "TWO_STAGE_SHIFT": 1, "BARREL_SHIFTER": 0,
    "COMPRESSED_ISA": 0, "CATCH_MISALIGN": 1, "CATCH_ILLINSN": 1,
    "ENABLE_MUL": 1, "ENABLE_FAST_MUL": 0, "ENABLE_DIV": 1, "ENABLE_IRQ": 0,
    "PROGADDR_RESET": 0, "STACKADDR": 262144, "TWO_CYCLE_ALU": 0, "TWO_CYCLE_COMPARE": 0,
}
PROFILES = [
    PARAMETERS,
    PARAMETERS | {"COMPRESSED_ISA": 1, "ENABLE_IRQ": 1, "ENABLE_COUNTERS64": 1},
    PARAMETERS | {"TWO_CYCLE_ALU": 1, "TWO_CYCLE_COMPARE": 1},
    PARAMETERS | {"ENABLE_REGS_DUALPORT": 0, "ENABLE_REGS_16_31": 0,
                  "ENABLE_MUL": 0, "ENABLE_DIV": 0, "ENABLE_COUNTERS": 0},
]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run(command: list[str], log: Path, timeout: int = 900) -> str:
    save_json(log.with_suffix(".command.json"), command)
    with log.open("w", encoding="utf-8") as stream:
        subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                       check=True, timeout=timeout)
    return log.read_text()


def formal(out: Path, sources: dict[str, Path]) -> dict:
    out.mkdir()
    results = []
    for profile, parameters in enumerate(PROFILES):
        commands = []
        options = " ".join(f"-G{name}={value}" for name, value in parameters.items())
        for label, source in sources.items():
            commands += [
                "read_slang -D SYNTHESIS=1 -D XILINX_FPGA=1 --top picorv32 " +
                options + " " + shlex.quote(str(source)),
                "prep -top picorv32 -flatten", "memory_map", "async2sync", "opt_clean",
                f"rename picorv32 {label}", f"design -stash {label}",
            ]
        commands += [
            "design -copy-from reference -as reference reference",
            "design -copy-from current -as current current",
            "equiv_make reference current equivalent", "hierarchy -top equivalent",
            "equiv_simple -seq 1", "opt_clean", "equiv_induct -seq 2", "equiv_status -assert",
        ]
        script = out / f"profile{profile}.ys"
        script.write_text("\n".join(commands) + "\n")
        log = out / f"profile{profile}.log"
        text = run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                    "--worker", str(script)], log)
        match = re.search(r"Of those cells (\d+) are proven and (\d+) are unproven", text)
        if match is None or int(match[2]) != 0:
            raise RuntimeError(f"CPU 状态等价检查未完成：{log}")
        result = {"passed": True, "profile": profile, "parameters": parameters,
                  "equivalent_bits": int(match[1]), "log_sha256": digest(log)}
        results.append(result)
        print(json.dumps({"formal": result}, ensure_ascii=False), flush=True)
    report = {"passed": True, "profiles": results, "input_constraints": []}
    save_json(out / "summary.json", report)
    return report


def make_program(out: Path) -> dict:
    """生成明确的 RV32I 指令，无需外部交叉编译器。"""
    words: list[int] = []

    def emit(word: int) -> None:
        words.append(word & 0xffffffff)

    def immediate(opcode: int, rd: int, rs1: int, value: int, function: int = 0) -> None:
        if not -2048 <= value <= 2047:
            raise ValueError("I 类指令立即数越界")
        emit(((value & 4095) << 20) | (rs1 << 15) | (function << 12) | (rd << 7) | opcode)

    def store(rs1: int, rs2: int, value: int) -> None:
        emit(((value & 0xfe0) << 20) | (rs2 << 20) | (rs1 << 15) |
             (2 << 12) | ((value & 31) << 7) | 0x23)

    def branch(rs1: int, rs2: int, target: int, function: int) -> None:
        offset = target - len(words) * 4
        if offset % 2 or not -4096 <= offset < 4096:
            raise ValueError("分支目标越界")
        emit(((offset >> 12 & 1) << 31) | ((offset >> 5 & 63) << 25) |
             (rs2 << 20) | (rs1 << 15) | (function << 12) |
             ((offset >> 1 & 15) << 8) | ((offset >> 11 & 1) << 7) | 0x63)

    def jump(rd: int, target: int) -> None:
        offset = target - len(words) * 4
        if offset % 2 or not -(1 << 20) <= offset < (1 << 20):
            raise ValueError("跳转目标越界")
        emit(((offset >> 20 & 1) << 31) | ((offset >> 1 & 1023) << 21) |
             ((offset >> 11 & 1) << 20) | ((offset >> 12 & 255) << 12) | (rd << 7) | 0x6f)

    emit((1 << 12) | (31 << 7) | 0x37)  # x31 指向数值结果存储区。
    immediate(0x13, 1, 0, 0)
    immediate(0x13, 2, 0, 1)
    immediate(0x13, 3, 0, 101)
    loop = len(words) * 4
    emit((2 << 20) | (1 << 15) | (1 << 7) | 0x33)
    jump(4, 0x1800)
    immediate(0x13, 2, 2, 1)
    branch(2, 3, loop, 4)
    store(31, 1, 0)
    immediate(0x13, 5, 0, -1)
    branch(5, 0, 48, 6)
    branch(5, 2, 52, 7)
    emit(0x00100073)
    emit((6 << 7) | 0x17)  # AUIPC 保存当前位置。
    immediate(0x13, 6, 6, 17)
    immediate(0x67, 7, 6, 0)  # JALR 检查目标地址最低位清零。
    emit(0x00100073)
    immediate(0x03, 8, 31, 0, 2)
    branch(1, 8, 48, 1)
    immediate(0x13, 10, 0, 0x55)
    store(31, 10, 4)
    emit(0x00100073)
    while len(words) * 4 < 0x1800:
        emit(0x00000013)
    emit((2 << 20) | (1 << 15) | (4 << 12) | (10 << 7) | 0x33)
    immediate(0x67, 0, 4, 0)
    program = out / "program.hex"
    program.write_text("".join(f"{word:08x}\n" for word in words))
    report = {"words": len(words), "loops": 100, "expected_sum": 5050,
              "expected_marker": 85, "subroutine_offset": 0x1800,
              "sha256": digest(program)}
    save_json(out / "program.json", report)
    return report


def execution(out: Path, sources: dict[str, Path], testbench: Path) -> dict:
    out.mkdir()
    program = make_program(out)
    # 每个上游模块独立更名，使两颗 CPU 分别使用各自的乘除法实现。
    text = sources["reference"].read_text()
    module_names = set(re.findall(r"\bmodule\s+(\w+)", text))
    pattern = re.compile(r"\b(?:" + "|".join(re.escape(name) for name in sorted(module_names)) + r")\b")
    renamed = out / "reference_cpu.v"
    renamed.write_text(pattern.sub(lambda match: match[0] + "_reference", text))
    results = []
    for address in (0, 0xfffff000):
        name = f"reset_{address:08x}"
        binary = out / (name + ".vvp")
        run(["iverilog", "-g2012", "-s", "tb_execution", f"-Ptb_execution.RESET_ADDR=32'h{address:08x}",
             "-o", str(binary), str(renamed), str(sources["current"]), str(testbench)],
            out / (name + "_build.log"), timeout=120)
        log = out / (name + ".log")
        output = run(["vvp", str(binary), f"+firmware={out / 'program.hex'}",
                      f"+firmware_words={program['words']}"], log, timeout=120)
        records = [json.loads(line.removeprefix("CPU_EXECUTION_PASS "))
                   for line in output.splitlines() if line.startswith("CPU_EXECUTION_PASS ")]
        if len(records) != 1 or not records[0].get("passed") or records[0]["reset_address"] != address:
            raise RuntimeError(f"CPU 指令执行未完成：{log}")
        result = records[0] | {"binary_sha256": digest(binary), "log_sha256": digest(log)}
        results.append(result)
        print(json.dumps({"execution": result}, ensure_ascii=False), flush=True)
    report = {"passed": True, "strict_four_state": True, "program": program, "profiles": results,
              "reference_modules_renamed": sorted(module_names), "testbench_sha256": digest(testbench)}
    save_json(out / "summary.json", report)
    return report


def measure(out: Path, source_root: Path, sources: dict[str, Path]) -> dict:
    out.mkdir()
    cases = {label: {
        "top": "picorv32", "parameters": PARAMETERS,
        "options": ["-D", "SYNTHESIS=1", "-D", "XILINX_FPGA=1"] +
                   [f"-G{name}={value}" for name, value in PARAMETERS.items()],
        "sources": [str(source.relative_to(source_root))],
        "configuration": "生产配置的完整 PicoRV32 CPU",
    } for label, source in sources.items()}
    config = out / "cases.json"
    save_json(config, cases)
    run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
         "--source-root", str(source_root), "--case-config", str(config),
         "--cases", "reference", "current", "--out", str(out / "synthesis"),
         "--wide-alu-dsp-budget", "740", "--rtl-dsp-attributes", "--max-register-path-cells", "10"],
        out / "synthesis.log", timeout=1800)
    report = {"passed": False, "maximum_register_path_cells": 10, "cases": {}}
    for label in cases:
        directory = out / "synthesis" / label
        path = directory / "metrics.json"
        metrics = json.loads(path.read_text())
        if not metrics["paths"]["graph_complete"]:
            raise RuntimeError(f"{label} 的寄存器路径连接图不完整")
        report["cases"][label] = {
            "resources": metrics["resources"], "graph_complete": True,
            "longest_register_path_cells": metrics["paths"]["longest_register_path_cells"],
            "metrics_sha256": digest(path), "manifest_sha256": digest(directory / "manifest.json"),
        }
    if report["cases"]["current"]["longest_register_path_cells"] > 10:
        raise RuntimeError("项目 CPU 的最长寄存器组合路径超过 10 级")
    report["passed"] = True
    save_json(out / "summary.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--reference-source", type=Path, default=ROOT / "picorv32/picorv32.v")
    parser.add_argument("--candidate-source", type=Path, default=ROOT / "rtl/soc/picorv32_npu.v")
    parser.add_argument("--stages", choices=("formal", "execution", "measure"), nargs="+",
                        default=["formal", "execution", "measure"])
    args = parser.parse_args()
    if len(set(args.stages)) != len(args.stages):
        parser.error("检查阶段存在重复项目")
    originals = {"reference": args.reference_source.resolve(strict=True),
                 "current": args.candidate_source.resolve(strict=True)}
    if digest(originals["reference"]) != UPSTREAM_SOURCE_SHA256:
        raise RuntimeError(f"参考源文件与固定上游提交 {UPSTREAM_COMMIT} 的 SHA256 不一致")
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    inputs = out / "inputs"
    (inputs / "include").mkdir(parents=True)
    sources = {}
    for label, source in originals.items():
        destination = inputs / label / "picorv32.v"
        destination.parent.mkdir()
        shutil.copyfile(source, destination)
        sources[label] = destination
    testbench = inputs / "tb_execution.sv"
    shutil.copyfile(Path(__file__).with_name("tb_execution.sv"), testbench)
    report = {"passed": False, "upstream_commit": UPSTREAM_COMMIT,
              "reference_sha256_verified": True,
              "source_sha256": {label: digest(path) for label, path in sources.items()},
              "source_paths": {label: str(path) for label, path in originals.items()},
              "requested_stages": args.stages, "stages": {}}
    save_json(out / "inputs.json", report)
    for stage in args.stages:
        if stage == "formal":
            result = formal(out / stage, sources)
        elif stage == "execution":
            result = execution(out / stage, sources, testbench)
        else:
            result = measure(out / stage, inputs, sources)
        report["stages"][stage] = result
        save_json(out / "summary.json", report)
    report["source_unchanged"] = all(digest(path) == report["source_sha256"][label]
                                      for label, path in originals.items())
    report["passed"] = True
    save_json(out / "summary.json", report)
    print(json.dumps({"passed": True, "summary": str(out / "summary.json")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
