#!/usr/bin/env python3
"""使用相同器件和配置综合两项缓冲的参考实现与当前实现。"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("rtl/soc/soc_axi_pingpong_buffer.sv")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", default="2f06471c")
    parser.add_argument("--out", type=Path, default=ROOT / "build/soc_pingpong_synthesis")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference = out / "reference.sv"
    reference.write_bytes(subprocess.check_output(["git", "show", f"{args.reference}:{SOURCE}"], cwd=ROOT))
    cases = {}
    for width in (2, 35, 64, 73):
        for name, source in (("reference", reference), ("current", ROOT / SOURCE)):
            cases[f"{name}{width}"] = dict(top="soc_axi_pingpong_chan",
                options=[f"-GWIDTH={width}", "-D", "SYNTHESIS=1"],
                sources=[str(source)], configuration=dict(WIDTH=width))
    configuration = out / "cases.json"
    configuration.write_text(json.dumps(cases, indent=2) + "\n")
    subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                    "--case-config", str(configuration), "--cases", *cases,
                    "--out", str(out / "synthesis")], cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
