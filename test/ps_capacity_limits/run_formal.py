#!/usr/bin/env python3
"""对容量常量表与原始截断、向上取整、乘法表达式执行完整输入 SAT。"""
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
    parser.add_argument("--bank-counts", type=int, nargs="+", default=[6, 7, 8, 9])
    parser.add_argument("--bank-bytes", type=int, nargs="+", default=[2048, 4096, 8192])
    parser.add_argument("--max-rows", type=int, default=1024)
    parser.add_argument("--frames-width", type=int, default=5)
    parser.add_argument("--worker", type=Path)
    args = parser.parse_args()
    if args.worker:
        from pyosys import libyosys
        libyosys.run_pass("script " + shlex.quote(str(args.worker)))
        return
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources = [ROOT / "rtl/npu/control/ps_capacity_limits.sv", HERE / "reference.sv"]
    summary = {"method": "Yosys combinational SAT against original capacity arithmetic",
               "source_sha256": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                                 for path in sources},
               "max_rows": args.max_rows, "frames_width": args.frames_width,
               "frame_codes": 1 << args.frames_width,
               "row_codes": 1 << args.max_rows.bit_length(),
               "bank_index_domain": "Every index in the original physical array, including zero and reserved entries",
               "slice_tile_codes": 1 << 32, "runs": []}
    for banks in args.bank_counts:
        for bank_bytes in args.bank_bytes:
            folder = out / f"banks{banks}_bytes{bank_bytes}"
            folder.mkdir(exist_ok=True)
            script = folder / "run.ys"
            script.write_text("read_slang --top ps_capacity_formal " +
                              f"-Gp_total_banks={banks} -Gp_bank_bytes={bank_bytes} " +
                              f"-Gp_max_rows={args.max_rows} -Gp_frames_width={args.frames_width} " +
                              " ".join(shlex.quote(str(path)) for path in sources) +
                              "\nprep -top ps_capacity_formal -flatten\nmemory_map\nopt_clean\n" +
                              "chformal -lower\nsat -prove-asserts -verify -show-inputs -show-outputs\n")
            with (folder / "formal.log").open("w") as stream:
                result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--out", str(out),
                                         "--worker", str(script)], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
            log = (folder / "formal.log").read_text()
            passed = result.returncode == 0 and "SAT proof finished - no model found: SUCCESS" in log
            record = {"total_banks": banks, "bank_bytes": bank_bytes, "passed": passed}
            summary["runs"].append(record)
            summary["passed"] = all(item["passed"] for item in summary["runs"])
            (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
            print(json.dumps(record), flush=True)
            if not passed:
                print(log[-12000:])
                raise SystemExit(1)


if __name__ == "__main__":
    main()
