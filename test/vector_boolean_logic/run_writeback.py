#!/usr/bin/env python3
"""用独立字节参考检查向量写回、背压保持及响应处理。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--verilator", default="verilator")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = ROOT / "rtl/npu/conv/vector_writeback.sv"
    reference = ROOT / "test/vector_writeback_rotation/main.cpp"
    report = {"source_sha256": digest(source), "test_sha256": digest(reference), "runs": []}
    for width in (32, 64, 128):
        folder = out / f"bus{width}"
        folder.mkdir(exist_ok=True)
        command = [args.verilator, "--cc", "--exe", "--build", "--assert", "--timing", "-Wno-fatal", "-j", "1",
                   "--top-module", "vector_writeback", "-DNPU_SIM_ASSERT", "-GTILE=16", f"-GBUS_WIDTH={width}",
                   "--Mdir", str(folder / "obj"), "--output-groups", "0", "--output-split", "12000",
                   "-CFLAGS", f"-std=c++20 -O1 -DTEST_BUS_WIDTH={width} -fsanitize=undefined -fno-sanitize-recover=all",
                   "-LDFLAGS", "-fsanitize=undefined",
                   "-MAKEFLAGS", "OPT_FAST=-O1 OPT_SLOW=-O0 OPT_GLOBAL=-O1 VK_PCH_I_FAST= VK_PCH_I_SLOW= CFG_CXXFLAGS_PCH=-E",
                   str(source), str(reference)]
        with (folder / "compile.log").open("w") as stream:
            subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
        binary = folder / "obj/Vvector_writeback"
        result = subprocess.run([str(binary)], cwd=ROOT, capture_output=True, text=True, check=True)
        (folder / "run.log").write_text(result.stdout + result.stderr)
        item = json.loads(result.stdout.strip().splitlines()[-1])
        if not item["passed"]:
            raise RuntimeError(f"字节结果检查未通过：{width}")
        item.update(binary_sha256=digest(binary), log_sha256=digest(folder / "run.log"))
        report["runs"].append(item)
        print(json.dumps(item), flush=True)
        for path in (folder / "obj").iterdir():
            if path.suffix in (".o", ".gch"):
                path.unlink()
    if report["source_sha256"] != digest(source):
        raise RuntimeError("验证期间源码发生变化")
    report["passed"] = True
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
