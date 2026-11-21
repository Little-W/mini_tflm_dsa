#!/usr/bin/env python3
"""证明选择加法在完整输入空间中的定宽算术结果。"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--widths", type=int, nargs="+", default=[1, 8, 16, 17, 32, 48])
    parser.add_argument("--worker", type=Path)
    args = parser.parse_args()
    if args.worker:
        from pyosys import libyosys
        libyosys.run_pass("script " + shlex.quote(str(args.worker)))
        return
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources = [ROOT / "rtl/npu/compute/select_add.sv", HERE / "select_add_formal.sv"]
    summary = {
        "method": "Yosys combinational SAT with unconstrained inputs",
        "latency_cycles": 0,
        "properties_per_width": 3,
        "source_sha256": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in sources},
        "runs": [],
    }
    for width in args.widths:
        folder = out / f"width{width}"
        folder.mkdir(exist_ok=True)
        script = folder / "run.ys"
        script.write_text(
            "read_verilog -formal -sv -D VERIFIC " +
            " ".join(shlex.quote(str(path)) for path in sources) + "\n" +
            f"chparam -set p_width {width} select_add_formal\n" +
            "prep -top select_add_formal -flatten\nchformal -lower\nopt_clean\n" +
            "sat -prove-asserts -verify -show-inputs -show-outputs\n"
        )
        with (folder / "formal.log").open("w") as stream:
            result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--out", str(out),
                                     "--worker", str(script)], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
        log = (folder / "formal.log").read_text()
        passed = result.returncode == 0 and "SAT proof finished - no model found: SUCCESS" in log
        summary["runs"].append({"width": width, "passed": passed, "input_bits": 3 * width + 2})
        summary["passed"] = all(item["passed"] for item in summary["runs"])
        (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps(summary["runs"][-1]), flush=True)
        if not passed:
            print(log[-14000:])
            raise SystemExit(1)


if __name__ == "__main__":
    main()
