#!/usr/bin/env python3
"""验证量化整行缓冲的 SRAM 功能模型与通用存储分支逐周期一致。"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command, log, cwd):
    with log.open("w") as stream:
        result = subprocess.run(command, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(log.read_text()[-8000:])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--verilator", default="verilator-modern")
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--keep-objects", action="store_true")
    args = parser.parse_args()
    source_root = args.source_root.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources = [
        source_root / "rtl/npu/writeback/requant_group_buffer.sv",
        source_root / "rtl/common/regfile.v",
        source_root / "asic/rtl/smic40_sram_1r1w.sv",
        ROOT / "test/requant_group_buffer_memory/sram_functional.sv",
        ROOT / "test/requant_group_buffer_memory/tb_memory.sv",
        ROOT / "test/monitors/requant_group_buffer_observer.sv",
        Path(__file__).resolve(),
    ]
    hashes = {str(path): sha(path) for path in sources}
    # 两个分支来自同一份控制 RTL，参考实例只选择通用同步读存储。
    reference = out / "requant_group_buffer_reference.sv"
    text = sources[0].read_text()
    declaration = "module requant_group_buffer #("
    if text.count(declaration) != 1:
        raise RuntimeError("Unexpected buffer module declaration")
    text = text.replace(declaration, "module requant_group_buffer_reference #(")
    reference.write_text("`undef ASIC_SRAM\n" + text + "\n`define ASIC_SRAM\n")
    # 通用参考实例使用相同的五项断言，分别检查两条实际存储路径。
    reference_observer = out / "requant_group_buffer_reference_observer.sv"
    reference_observer.write_text(sources[5].read_text().replace(
        "requant_group_buffer", "requant_group_buffer_reference"))
    objects = out / "obj"
    command = [
        args.verilator, "--binary", "--timing", "--assert", "-Wno-fatal", "--sv",
        "-DASIC_SRAM", "--top-module", "tb_requant_group_buffer_memory",
        "--Mdir", str(objects), "-j", str(args.jobs), "-O1",
        *map(str, sources[:-1]), str(reference), str(reference_observer),
    ]
    run(command, out / "compile.log", source_root)
    binary = out / "simulation"
    shutil.copy2(objects / "Vtb_requant_group_buffer_memory", binary)
    run([str(binary)], out / "simulation.log", out)
    simulation = (out / "simulation.log").read_text()
    profiles = [json.loads(line.removeprefix("RESULT ")) for line in simulation.splitlines()
                if line.startswith("RESULT ")]
    if len(profiles) != 10 or "PASS complete SRAM row comparison" not in simulation:
        raise RuntimeError("Simulation coverage is incomplete")
    if hashes != {str(path): sha(path) for path in sources}:
        raise RuntimeError("Source files changed during verification")
    default = next(profile for profile in profiles if profile["rows"] == 512)
    summary = {
        "passed": True,
        "model": "完整状态同步 SRAM 功能模型；同地址并发读写终止仿真",
        "reference": "同一控制 RTL 的通用 regfile 分支",
        "foundry_model_used": False,
        "source_sha256": hashes,
        "reference_sha256": sha(reference),
        "reference_observer_sha256": sha(reference_observer),
        "binary_sha256": sha(binary),
        "verilator_version": subprocess.check_output([args.verilator, "--version"], text=True).strip(),
        "compile_command": command,
        "profiles": sorted(profiles, key=lambda item: item["rows"]),
        "default_logical_storage_bits": default["logical_bits"],
        "default_sram_instances": 132,
        "default_physical_storage_bits": 132 * 128 * 16,
        "default_physical_storage_bytes": 132 * 128 * 16 // 8,
        "total_row_reads": sum(profile["reads"] for profile in profiles),
        "compared_consumed_bits": sum(profile["reads"] * (profile["lanes"] * 32 + 1)
                                      for profile in profiles),
        "full_storage_zero_and_one_checks": True,
        "coverage": ["全部数据位和完成标志", "满容量预留与背压", "读写并发", "地址回绕",
                     "跨宏深度边界", "非二的整数次幂深度", "暂停保持", "中途清空", "中途复位"],
    }
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    if not args.keep_objects:
        shutil.rmtree(objects)
    print(json.dumps({"passed": True, "profiles": len(profiles),
                      "compared_consumed_bits": summary["compared_consumed_bits"],
                      "default_logical_storage_bits": default["logical_bits"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
