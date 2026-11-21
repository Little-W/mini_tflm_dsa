#!/usr/bin/env python3
"""证明 Softmax 完整接口在两种乘法延迟及两种算术配置下保持等价。"""

import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("rtl/npu/conv/vector_softmax.sv")
COMMON = Path("rtl/common/parallel_prefix_add.sv")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-rev", default="415a70a")
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    source_root = args.source_root.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference = out / "reference.sv"
    reference.write_bytes(subprocess.check_output(
        ["git", "show", f"{args.reference_rev}:{SOURCE}"], cwd=ROOT))
    candidate = out / "candidate.sv"
    candidate.write_bytes((source_root / SOURCE).read_bytes())
    common = out / "parallel_prefix_add.sv"
    common.write_bytes((source_root / COMMON).read_bytes())
    source_hashes = {str(SOURCE): digest(candidate), str(COMMON): digest(common)}
    profiles = []
    for mode, define in (("fpga", "XILINX_FPGA"), ("generic", "ASIC_SYNTHESIS")):
        for latency in (0, 2):
            folder = out / f"{mode}_latency{latency}"
            folder.mkdir(exist_ok=True)
            commands = []
            for label, source in (("reference", reference), ("candidate", candidate)):
                commands += [
                    f"read_slang -D {define}=1 --top vector_softmax -GMULTIPLIER_LATENCY={latency} " +
                    " ".join(shlex.quote(str(path)) for path in (source, common)),
                    "prep -top vector_softmax -flatten", "async2sync", "opt -full",
                    f"rename vector_softmax {label}", f"design -stash {label}",
                ]
            commands += [
                "design -copy-from reference -as reference reference",
                "design -copy-from candidate -as candidate candidate",
                "equiv_make reference candidate comparison", "hierarchy -top comparison",
                "equiv_simple -seq 2", "opt_clean", "equiv_induct -seq 3", "equiv_status -assert",
            ]
            script, log = folder / "run.ys", folder / "formal.log"
            script.write_text("\n".join(commands) + "\n")
            with log.open("w") as stream:
                subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                                "--worker", str(script)], cwd=ROOT, stdout=stream,
                               stderr=subprocess.STDOUT, check=True, timeout=180)
            if "Equivalence successfully proven" not in log.read_text():
                raise RuntimeError(f"形式检查未完成：{log}")
            profiles.append({"mode": mode, "multiplier_latency": latency, "passed": True,
                             "script_sha256": digest(script), "log_sha256": digest(log)})
    if source_hashes != {name: digest(source_root / name) for name in source_hashes}:
        raise RuntimeError("检查期间 Softmax 源码或公共加法器发生变化")
    report = {"passed": True, "reference_revision": args.reference_rev,
              "reference_sha256": digest(reference), "source_sha256": source_hashes,
              "inputs_constrained": False, "all_public_outputs_compared": True,
              "profiles": profiles}
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"passed": True, "profiles": len(profiles)}))


if __name__ == "__main__":
    main()
