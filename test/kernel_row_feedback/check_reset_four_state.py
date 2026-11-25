#!/usr/bin/env python3
"""在完整加载器比较中检查异步复位的零、一、未知和高阻状态。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    prepared, out = args.prepared.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    report = json.loads((prepared / "summary.json").read_text())
    if not report["passed"]:
        raise RuntimeError("完整四态比较尚未完成")
    for name, expected in report["source_sha256"].items():
        if digest(Path(name)) != expected:
            raise RuntimeError("源文件与准备结果不同：" + name)
    original_bench = prepared / "tb_loader_four_state.sv"
    bench = original_bench.read_text()
    replacements = (
        (r"sample<\d+", "sample<4000"),
        (r"rst_n = sample % 31 != 0;", ""),
        (r"known_positions < \d+", "known_positions < 100"),
        (r"      tick\(\);\n    end", """      // 数据和其他控制先稳定，再触发异步复位事件。
      #1;
      case (sample % 17)
        0: rst_n = 1'b0;
        1: rst_n = 1'bx;
        2: rst_n = 1'bz;
        default: rst_n = 1'b1;
      endcase
      tick();
    end"""),
    )
    for pattern, replacement in replacements:
        bench, count = re.subn(pattern, replacement, bench)
        if count != 1:
            raise RuntimeError("完整四态测试结构未匹配：" + pattern)
    target = out / "tb_reset_four_state.sv"
    target.write_text(bench)
    command = list(report["compile_command"])
    command[command.index("-o") + 1] = str(out / "compare.vvp")
    command = [str(target) if item == str(original_bench) else item for item in command]
    compiled_sources = [Path(item) for item in command if Path(item).suffix in (".sv", ".v")]
    before = {str(path): digest(path) for path in compiled_sources}
    with (out / "compile.log").open("w") as stream:
        subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, check=True)
    result = subprocess.run(["vvp", str(out / "compare.vvp")], text=True,
                            capture_output=True, timeout=180, check=True)
    (out / "run.log").write_text(result.stdout + result.stderr)
    match = re.search(r"KERNEL_LOADER_FOUR_STATE_PASS cycles=(\d+) outputs=(\d+) known_positions=(\d+)",
                      result.stdout)
    if match is None or int(match[1]) != 4004 or int(match[2]) != report["compared_outputs"]:
        raise RuntimeError("异步复位四态比较未完整通过")
    if before != {str(path): digest(path) for path in compiled_sources}:
        raise RuntimeError("验证期间源文件发生变化")
    summary = dict(passed=True, cycles=int(match[1]), compared_outputs=int(match[2]),
                   known_positions=int(match[3]), parameters=report["parameters"],
                   source_sha256=before, prepared_summary_sha256=digest(prepared / "summary.json"),
                   reset_states=["0", "1", "X", "Z"], compile_command=command)
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({key: summary[key] for key in ("passed", "cycles", "compared_outputs", "known_positions")}))


if __name__ == "__main__":
    main()
