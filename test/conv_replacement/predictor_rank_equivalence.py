#!/usr/bin/env python3
"""证明预测器候选选择改写后的完整寄存状态和公开输出。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("rtl/npu/dma/cache/conv_next_use_predictor.sv")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", default="2f06471c")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    original = read_rtl_source(f"{args.reference}:{SOURCE}", cwd=ROOT)
    current = (ROOT / SOURCE).read_bytes()
    reference = out / "reference.sv"
    snapshot = out / "current.sv"
    reference.write_bytes(original)
    snapshot.write_bytes(current)
    package = shlex.quote(str(ROOT / "rtl/npu/conv/conv_im2col_pkg.sv"))
    helper = shlex.quote(str(ROOT / "rtl/common/onehot_check.sv"))
    script = out / "prove.ys"
    script.write_text(
        f"read_slang --top conv_next_use_predictor {package} {helper} {shlex.quote(str(reference))}\n"
        "proc\nasync2sync\nopt\nrename conv_next_use_predictor reference\ndesign -stash reference\n"
        f"read_slang --top conv_next_use_predictor {package} {helper} {shlex.quote(str(snapshot))}\n"
        "proc\nasync2sync\nopt\nrename conv_next_use_predictor current\ndesign -stash current\n"
        "design -copy-from reference -as reference reference\n"
        "design -copy-from current -as current current\n"
        "equiv_make reference current equivalence\nhierarchy -top equivalence\n"
        "opt_clean\nequiv_simple -undef -seq 2\nequiv_induct -undef -seq 2\nequiv_status -assert\n")
    log_path = out / "prove.log"
    with log_path.open("w") as log:
        subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                        "--worker", str(script)], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    found = re.search(r"Of those cells (\d+) are proven and 0 are unproven", log_path.read_text())
    if found is None:
        raise RuntimeError("Incomplete state and output equivalence")
    if current != (ROOT / SOURCE).read_bytes():
        raise RuntimeError("RTL changed during equivalence")
    summary = dict(passed=True, reference=args.reference, proven_bits=int(found[1]),
                   all_public_outputs_compared=True, formal_inputs_constrained=False,
                   source_sha256=hashlib.sha256(current).hexdigest(),
                   reference_sha256=hashlib.sha256(original).hexdigest(),
                   proof_log_sha256=hashlib.sha256(log_path.read_bytes()).hexdigest())
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
