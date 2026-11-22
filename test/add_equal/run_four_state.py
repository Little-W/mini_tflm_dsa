#!/usr/bin/env python3
"""检查逐位比较与进位向量逻辑相等的四态行为。"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
WIDTHS = (1, 2, 4, 8, 16, 28, 32, 33, 64)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = ROOT / "rtl/common/add_equal.sv"
    snapshot = out / source.name
    snapshot.write_bytes(source.read_bytes())
    bench_source = ROOT / "test/add_equal/tb_four_state.sv"
    bench = out / bench_source.name
    bench.write_bytes(bench_source.read_bytes())
    summary = {
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "bench_sha256": hashlib.sha256(bench.read_bytes()).hexdigest(),
        "method": "Four-state case-equality comparison against vector carry consistency",
        "runs": [],
    }
    for width in WIDTHS:
        executable = out / f"width_{width}.vvp"
        build_log, run_log = out / f"width_{width}_build.log", out / f"width_{width}.log"
        with build_log.open("w") as stream:
            subprocess.run([shutil.which("iverilog") or "iverilog", "-g2012", "-Wall", "-DXILINX_FPGA",
                            "-s", "tb_add_equal_four_state", f"-Ptb_add_equal_four_state.p_width={width}",
                            "-o", str(executable), str(snapshot), str(bench)],
                           stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=60)
        with run_log.open("w") as stream:
            subprocess.run([shutil.which("vvp") or "vvp", str(executable)],
                           stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=120)
        output = run_log.read_text()
        if "ADD_EQUAL_FOUR_STATE_PASS" not in output:
            raise RuntimeError(f"Four-state comparison did not complete: {run_log}")
        summary["runs"].append({"width": width, "passed": True,
                                "tests": 4 ** (3*width+1) if width <= 2 else 6000,
                                "log_sha256": hashlib.sha256(run_log.read_bytes()).hexdigest()})
        print(output.splitlines()[0], flush=True)
    summary["passed"] = True
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    assert snapshot.read_bytes() == source.read_bytes()


if __name__ == "__main__":
    main()
