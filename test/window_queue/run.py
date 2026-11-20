#!/usr/bin/env python3
"""检查不同深度窗口队列的逐周期发送、随机停顿和故障恢复。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verilator", default="verilator")
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--out", type=Path, default=ROOT / "build/window_queue")
    args = parser.parse_args()
    out = args.out.resolve()
    sources = [ROOT / "rtl/common/regfile.v", ROOT / "rtl/npu/dma/conv_window_queue.sv",
               Path(__file__).with_name("main.cpp")]
    hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    cases = []
    for depth, lanes in ((2, 4), (3, 16), (4, 16), (7, 16)):
        folder = out / f"depth{depth}_lanes{lanes}"
        folder.mkdir(parents=True, exist_ok=True)
        command = [args.verilator, "--cc", "--exe", "--build", "--assert", "-Wno-fatal",
                   "--top-module", "conv_window_queue", f"-GDEPTH={depth}",
                   f"-GWINDOW_LANES={lanes}", "--Mdir", str(folder / "obj"),
                   "-j", str(args.jobs), "-CFLAGS", f"-std=c++20 -O1 -DTEST_DEPTH={depth} -DTEST_LANES={lanes}",
                   *map(str, sources)]
        with (folder / "compile.log").open("w") as log:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
        result = subprocess.run([str(folder / "obj/Vconv_window_queue")], capture_output=True, text=True)
        (folder / "run.log").write_text(result.stdout + result.stderr)
        print(result.stdout + result.stderr, end="", flush=True)
        result.check_returncode()
        if result.stdout.count("WINDOW_QUEUE_PASS") != 2:
            raise RuntimeError("窗口队列测试结果不完整")
        cases.append(dict(depth=depth, lanes=lanes, passed=True, results=result.stdout.splitlines(),
                          command=command))
    if hashes != {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}:
        raise RuntimeError("测试期间源码发生变化")
    (out / "summary.json").write_text(json.dumps(dict(passed=True, source_sha256=hashes,
                                                     cases=cases), indent=2) + "\n")


if __name__ == "__main__":
    main()
