#!/usr/bin/env python3
"""证明浅移位表保留全部存储状态、同步输出和任意读写行为。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

from support import ROOT, RTL, amount_storage

sys.path.insert(0, str(ROOT / "scripts/fpga"))
from open_fpga_synth import run_stage


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference", default="820c2b18")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = (ROOT / RTL).read_text()
    reference = subprocess.check_output(["git", "show", args.reference+":"+str(RTL)], cwd=ROOT, text=True)
    inputs = {}
    for label, source in [("reference", reference), ("current", current)]:
        path = out / (label+".sv")
        path.write_text(amount_storage(source))
        inputs[label] = path
    regfile = out / "regfile.v"
    regfile.write_bytes((ROOT / "rtl/common/regfile.v").read_bytes())
    report = {"passed": False, "reference": args.reference, "inputs_constrained": False,
              "source_sha256": hashlib.sha256(current.encode()).hexdigest(),
              "reference_sha256": hashlib.sha256(reference.encode()).hexdigest(),
              "regfile_sha256": hashlib.sha256(regfile.read_bytes()).hexdigest(), "profiles": []}
    for depth in (1, 2, 3, 7, 63, 128):
        folder = out / f"d{depth}"
        folder.mkdir(exist_ok=True)
        commands = []
        for label, path in inputs.items():
            commands += [f"read_slang --top amount_storage -GBANK_DEPTH={depth} "+shlex.join(map(str, [path,regfile])),
                         "prep -top amount_storage -flatten", "memory_map", "opt -full",
                         "rename -top "+label, "design -stash "+label]
        commands += ["design -copy-from reference -as reference reference",
                     "design -copy-from current -as current current", "equiv_make reference current equivalent",
                     "hierarchy -top equivalent", "equiv_simple -seq 2", "equiv_induct -seq 2", "equiv_status -assert"]
        script, log = folder / "formal.ys", folder / "formal.log"
        script.write_text("\n".join(commands)+"\n")
        run_stage(script, log, dict(os.environ))
        matched = re.search(r"Of those cells (\d+) are proven and (\d+) are unproven", log.read_text())
        if not matched or int(matched[2]):
            raise RuntimeError("浅表等价证明未完成")
        record = {"depth": depth, "passed": True, "equivalent_bits": int(matched[1]),
                  "logical_storage_bits": depth*7, "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest()}
        report["profiles"].append(record)
        print(json.dumps(record), flush=True)
    report["passed"] = True
    (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n")


if __name__ == "__main__":
    main()
