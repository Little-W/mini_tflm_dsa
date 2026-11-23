#!/usr/bin/env python3
"""使用官方 FPGA 原语模型比较 IA 加载器所有公开输出的周期行为。"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference-rev", default="7ff66a59")
    parser.add_argument("--verilator", default="verilator")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    verilator = shutil.which(args.verilator)
    if verilator is None:
        raise RuntimeError("Cannot locate Verilator: " + args.verilator)
    wrapper = out / "verilator_generated_cpp"
    # 测试程序保留 -Werror；自动生成代码使用适合 Verilator 布尔运算的编译选项。
    wrapper.write_text(
        "#!" + sys.executable + "\n"
        "import os, shlex, sys\nfrom pathlib import Path\n"
        "arguments = sys.argv[1:]\n"
        "if '-MAKEFLAGS' in arguments:\n"
        "    flags = shlex.split(arguments[arguments.index('-MAKEFLAGS') + 1])\n"
        "    rules = Path(flags[flags.index('-f') + 1])\n"
        "    rules.write_text(rules.read_text() + "
        "'\\n$(VK_OBJS_FAST) $(VK_OBJS_SLOW): override CPPFLAGS += -Wno-bool-operation\\n')\n"
        "os.execv(" + repr(verilator) + ", [" + repr(verilator) + "] + arguments)\n"
    )
    wrapper.chmod(0o755)
    subprocess.run(
        [sys.executable, str(ROOT / "test/ia_request_lut/run_interface.py"),
         "--out", str(out), "--reference-rev", args.reference_rev,
         "--verilator", str(wrapper)], cwd=ROOT, check=True,
    )
    summary = out / "summary.json"
    result = json.loads(summary.read_text())
    result["generated_cpp_flags"] = ["-Wno-bool-operation"]
    summary.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
