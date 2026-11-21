#!/usr/bin/env python3
"""验证结果写入队列的数据保存、连续地址合并和随机总线停顿。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def run(command, log):
    with log.open("w") as stream:
        result = subprocess.run([str(value) for value in command], cwd=ROOT,
                                stdout=stream, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(log.read_text()[-12000:])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verilator", default="verilator")
    parser.add_argument("--out", type=Path, default=ROOT / "build/vector_writeback")
    parser.add_argument("--jobs", type=int, default=2)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources = [ROOT / "rtl/npu/conv/vector_writeback.sv", HERE / "overlap_observer.sv", HERE / "main.cpp"]
    hashes = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in sources}
    results = []
    for byte_only, width in ((0, 32), (0, 64), (1, 32), (1, 64)):
        folder = out / f"axi{width}_byte_only{byte_only}"
        folder.mkdir(exist_ok=True)
        run([args.verilator, "--cc", "--exe", "--build", "-j", args.jobs,
             "--assert", "--top-module", "vector_writeback", "-Wno-fatal",
             f"-GBUS_WIDTH={width}", f"-Gp_coalesce_bytes_only={byte_only}", "--Mdir", folder / "obj",
             "-CFLAGS", f"-std=c++17 -DTEST_BUS_WIDTH={width}", *sources], folder / "build.log")
        run([folder / "obj/Vvector_writeback"], folder / "run.log")
        text = (folder / "run.log").read_text()
        match = re.search(r"VECTOR_WRITEBACK_PASS (.+)", text)
        if not match:
            raise RuntimeError("缺少完整的测试结果")
        result = {key: int(value) for key, value in
                  (item.split("=") for item in match.group(1).split())}
        result["passed"] = True
        result["byte_only"] = byte_only
        results.append(result)
        print(text.strip(), flush=True)
    if any(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != value
           for name, value in hashes.items()):
        raise RuntimeError("构建期间源文件发生变化")
    (out / "summary.json").write_text(json.dumps({"passed": True, "runs": results,
                                                  "source_sha256": hashes}, indent=2) + "\n")


if __name__ == "__main__":
    main()
