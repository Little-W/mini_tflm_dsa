#!/usr/bin/env python3
"""验证指数累加、舍入进位、清除和有效位的完整时序关系。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--worker", type=Path)
    args = parser.parse_args()
    if args.worker:
        from pyosys import libyosys
        libyosys.run_pass("script " + shlex.quote(str(args.worker)))
        return
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources = [ROOT / "rtl/npu/conv/vector_softmax_accumulator.sv",
               ROOT / "rtl/common/parallel_prefix_add.sv", HERE / "accumulator_formal.sv"]
    script = out / "run.ys"
    script.write_text(
        "read_verilog -formal -sv -D VERIFIC " +
        " ".join(shlex.quote(str(path)) for path in sources) + "\n"
        "prep -top accumulator_formal -flatten\n"
        "async2sync\n"
        "opt_clean\n"
        "sat -seq 1 -tempinduct -initsteps 3 -maxsteps 6 -set-at 1 rst_n 0 -prove-asserts -verify\n"
    )
    with (out / "formal.log").open("w") as stream:
        result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--out", str(out),
                                 "--worker", str(script)], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
    log = (out / "formal.log").read_text()
    passed = result.returncode == 0 and "Induction step proven" in log
    summary = {
        "passed": passed,
        "method": "Yosys SAT temporal induction over the actual accumulator RTL",
        "data_bits": 20,
        "increment_bits": 1,
        "sum_bits": 32,
        "latency_edges": 2,
        "arbitrary_controls": ["rst_n", "i_clear", "i_vld"],
        "source_sha256": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources},
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    if not passed:
        print(log[-14000:])
        raise SystemExit(1)


if __name__ == "__main__":
    main()
