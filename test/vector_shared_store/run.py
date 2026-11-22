#!/usr/bin/env python3
"""验证 VCE 使用现有 IA/PS RAM 的地址映射、同步读取和错误恢复。"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--verilator", default="verilator")
    parser.add_argument("--profiles", nargs="+", default=[
        f"{size}:{banks}:{fixed}:1"
        for size, banks in ((2048, 7), (2048, 8), (4096, 6), (4096, 9), (8192, 7), (8192, 8))
        for fixed in (0, 1)
    ] + ["2048:7:1:0"])
    parser.add_argument("--cycles", type=int, default=2000)
    parser.add_argument("--jobs", type=int, default=1)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source_root = args.source_root.resolve()
    sources = [source_root / "rtl/npu/buffers/vector_shared_store.sv",
               source_root / "rtl/npu/buffers/ia_ps_shared_ram.sv",
               source_root / "rtl/common/regfile.v",
               ROOT / "test/vector_shared_store/tb_vector_shared_store.sv"]
    tracked = sources + [Path(__file__).resolve()]
    def source_name(path):
        return str(path.relative_to(source_root) if path.is_relative_to(source_root) else path.relative_to(ROOT))
    hashes = {source_name(path): digest(path) for path in tracked}
    summary = {"passed": False, "source_sha256": hashes, "profiles": [],
               "verilator_version": subprocess.check_output([args.verilator, "--version"], text=True).strip()}
    for profile in args.profiles:
        size, banks, fixed, shared_stage = map(int, profile.split(":"))
        folder = out / f"b{size}_n{banks}_f{fixed}_s{shared_stage}"
        folder.mkdir(exist_ok=True)
        command = [args.verilator, "--binary", "--timing", "-j", str(args.jobs),
                   "--top-module", "tb_vector_shared_store", "--Mdir", str(folder / "obj"),
                   "-MAKEFLAGS", "OPT_FAST=-O0 OPT_SLOW=-O0",
                   f"-Gp_bank_bytes={size}", f"-Gp_banks={banks}",
                   f"-Gp_fixed_ps_channels={fixed}", f"-Gp_shared_write_stage={shared_stage}",
                   f"-Gp_cycles={args.cycles}", *map(str, sources)]
        with (folder / "compile.log").open("w") as log:
            result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError(f"编译失败，请查看 {folder / 'compile.log'}")
        binary = folder / "obj/Vtb_vector_shared_store"
        result = subprocess.run([str(binary)], cwd=ROOT, text=True, capture_output=True)
        (folder / "run.log").write_text(result.stdout + result.stderr)
        match = re.search(r"VECTOR_SHARED_STORE_PASS (.*)", result.stdout)
        if result.returncode or not match:
            raise RuntimeError(result.stdout + result.stderr)
        counts = {key: int(value) for key, value in re.findall(r"(\w+)=(\d+)", match[1])}
        report = {"passed": True, "parameters": {"bank_bytes": size, "banks": banks,
                  "fixed_ps_channels": bool(fixed), "shared_write_stage": bool(shared_stage),
                  "random_cycles_per_allocation": args.cycles}, "counts": counts,
                  "compile_command": command, "binary_sha256": digest(binary)}
        summary["profiles"].append(report)
        print(json.dumps({"profile": profile, **counts}), flush=True)
    if hashes != {source_name(path): digest(path) for path in tracked}:
        raise RuntimeError("运行期间源文件发生变化")
    summary["passed"] = True
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({"passed": True, "profiles": len(summary["profiles"])}), flush=True)


if __name__ == "__main__":
    main()
