#!/usr/bin/env python3
"""检查公共 regfile 的写入掩码、读使能和同地址读写行为。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
PROFILES = ((1, 1, 1, 1), (1, 128, 1, 7), (32, 64, 8, 1), (32, 16, 32, 1), (40, 33, 8, 3), (16, 8, 1, 2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verilator", default=shutil.which("verilator") or "verilator")
    parser.add_argument("--out", type=Path, default=ROOT / "build/regfile")
    args = parser.parse_args()
    sources = [ROOT / "rtl/common/regfile.v", ROOT / "rtl/common/pseudo_dual_port_ram.v",
               ROOT / "test/regfile/tb_regfile.sv"]
    hashes = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    results = []
    for width, depth, unit, ports in PROFILES:
        out = args.out.resolve() / f"w{width}_d{depth}_u{unit}_r{ports}"
        out.mkdir(parents=True, exist_ok=True)
        command = [args.verilator, "--binary", "--timing", "--assert", "-Wno-fatal",
                   "--top-module", "tb_regfile", f"-GDATA_WIDTH={width}", f"-GDEPTH={depth}",
                   f"-GWRITE_UNIT={unit}", f"-GREAD_PORTS={ports}", "-j", "2",
                   "--Mdir", str(out / "obj"), *map(str, sources)]
        with (out / "compile.log").open("w") as log:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True, cwd=ROOT)
        result = subprocess.run([str(out / "obj/Vtb_regfile")], capture_output=True, text=True, check=True)
        (out / "run.log").write_text(result.stdout + result.stderr)
        line = next(line for line in result.stdout.splitlines() if line.startswith("REGFILE_PASS"))
        fields = {key: int(value) for key, value in re.findall(r"(\w+)=(\d+)", line)}
        results.append(fields)
        print(line, flush=True)
    assert hashes == {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    (args.out.resolve() / "summary.json").write_text(json.dumps({"passed": True, "sources_sha256": hashes,
        "profiles": results}, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
