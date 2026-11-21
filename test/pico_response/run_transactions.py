#!/usr/bin/env python3
"""验证原生 CPU 请求与 AXI 响应的事务、数值和逐周期关系。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROFILES = [f"{address}:{data}:{registered}" for registered in (1, 0)
                    for address in (32, 40) for data in (32, 64)]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command: list[str], log: Path) -> None:
    with log.open("w", encoding="utf-8") as stream:
        subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--source", type=Path, default=ROOT / "rtl/soc/pico_native_to_axi.sv")
    parser.add_argument("--profiles", nargs="+", default=DEFAULT_PROFILES,
                        help="地址宽度:数据宽度:REGISTER_RESPONSE；默认运行八种组合")
    parser.add_argument("--keep-objects", action="store_true", help="保留可重新生成的 C++ 编译中间文件")
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    testbench = Path(__file__).with_name("tb_transactions.sv")
    profiles = []
    for item in args.profiles:
        values = tuple(int(value) for value in item.split(":"))
        if len(values) != 3 or values[0] not in (32, 40) or values[1] not in (32, 64) or values[2] not in (0, 1):
            parser.error(f"不支持的参数组合：{item}")
        if values in profiles:
            parser.error(f"重复的参数组合：{item}")
        profiles.append(values)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    inputs = out / "inputs"
    inputs.mkdir()
    source_copy = inputs / source.name
    testbench_copy = inputs / testbench.name
    shutil.copyfile(source, source_copy)
    shutil.copyfile(testbench, testbench_copy)
    result = {
        "passed": False,
        "source": str(source), "source_sha256": sha256(source_copy),
        "testbench_sha256": sha256(testbench_copy),
        "verilator": subprocess.check_output(["verilator", "--version"], text=True).strip(),
        "compiler": subprocess.check_output(["g++", "--version"], text=True).splitlines()[0],
        "profiles": [],
    }
    (out / "inputs.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    for address, data, registered in profiles:
        directory = out / f"a{address}_d{data}_r{registered}"
        directory.mkdir()
        objects = directory / "obj"
        command = [
            "verilator", "--binary", "--timing", "--assert", "-j", "1", "-Wno-fatal",
            "--top-module", "tb_transactions", "--Mdir", str(objects),
            f"-GADDR_WIDTH={address}", f"-GDATA_WIDTH={data}", f"-GREGISTER_RESPONSE={registered}",
            "-CFLAGS", "-std=c++20 -O1 -fsanitize=undefined -fno-sanitize-recover=all",
            "-LDFLAGS", "-fsanitize=undefined", "-MAKEFLAGS", "CXX=g++ OPT_FAST=-O1 OPT_SLOW=-O0 OPT_GLOBAL=-O0",
            str(source_copy), str(testbench_copy),
        ]
        (directory / "command.json").write_text(json.dumps(command, indent=2) + "\n")
        build_log = directory / "build.log"
        run(command, build_log)
        # 检查每个编译单元均启用未定义行为检查，包含生成的仿真调度代码。
        compiler_lines = [line for line in build_log.read_text().splitlines()
                          if re.search(r"(?:^|\s)(?:g\+\+|c\+\+)\s", line) and " -c " in line]
        if not compiler_lines or any("-fsanitize=undefined" not in line or
                                     "-fno-sanitize-recover=all" not in line for line in compiler_lines):
            raise RuntimeError(f"编译单元的检查选项不完整：{build_log}")
        binary = objects / "Vtb_transactions"
        run_log = directory / "run.log"
        run([str(binary)], run_log)
        records = [json.loads(line.removeprefix("TRANSACTIONS_PASS "))
                   for line in run_log.read_text().splitlines() if line.startswith("TRANSACTIONS_PASS ")]
        if len(records) != 1 or not records[0].get("passed"):
            raise RuntimeError(f"事务验证缺少完成结果：{run_log}")
        record = records[0]
        if (record["address_width"], record["data_width"], record["registered_response"]) != (address, data, registered):
            raise RuntimeError("仿真参数与请求参数不一致")
        record.update(binary_sha256=sha256(binary), sanitized_compile_units=len(compiler_lines),
                      source_sha256=result["source_sha256"], testbench_sha256=result["testbench_sha256"])
        (directory / "summary.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
        result["profiles"].append(record)
        print(json.dumps(record, ensure_ascii=False), flush=True)
        if not args.keep_objects:
            for generated in objects.iterdir():
                if generated.suffix in (".o", ".gch"):
                    generated.unlink()
    result["passed"] = len(result["profiles"]) == len(profiles)
    result["source_unchanged"] = sha256(source) == result["source_sha256"]
    result["totals"] = {key: sum(profile[key] for profile in result["profiles"])
                        for key in ("cycles", "started", "completed", "reads", "writes", "aborted",
                                    "resets", "checked_read_bytes", "ar_stability_checks",
                                    "aw_stability_checks", "w_stability_checks")}
    (out / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"passed": result["passed"], "summary": str(out / "summary.json")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
