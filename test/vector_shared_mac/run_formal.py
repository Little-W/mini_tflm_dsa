#!/usr/bin/env python3
"""逐个操作码证明向量 PE 的完整输入空间与参考实现等价。"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("rtl/npu/conv/vector_pe.sv")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference-rev", default="415a70a")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference = out / "reference.sv"
    reference.write_bytes(subprocess.check_output(
        ["git", "show", f"{args.reference_rev}:{SOURCE}"], cwd=ROOT))
    candidate = out / "candidate.sv"
    candidate.write_bytes((ROOT / SOURCE).read_bytes())
    source_hash = digest(candidate)
    runs = []
    for extended in (0, 1):
        for operation in range(8):
            folder = out / f"extended{extended}_operation{operation}"
            folder.mkdir(exist_ok=True)
            wrapper = folder / "wrapper.sv"
            wrapper.write_text(f"""module vector_mac_formal (
  input logic signed [15:0] a, b,
  input logic signed [31:0] acc,
  output logic signed [31:0] result
);
  vector_pe #(.ENABLE_EXTENDED_MULTIPLY(1'b{extended})) u_pe (
    .op(3'd{operation}), .a(a), .b(b), .acc(acc), .result(result)
  );
endmodule
""")
            commands = []
            for label, source in (("reference", reference), ("candidate", candidate)):
                commands.extend([
                    "read_slang --top vector_mac_formal " +
                    " ".join(shlex.quote(str(path)) for path in (source, wrapper)),
                    "prep -top vector_mac_formal -flatten", "opt -full",
                    "rename -hide w:*",
                    f"rename vector_mac_formal {label}", f"design -stash {label}",
                ])
            commands.extend([
                "design -copy-from reference -as reference reference",
                "design -copy-from candidate -as candidate candidate",
                "equiv_make reference candidate comparison", "hierarchy -top comparison",
                "equiv_simple", "equiv_status -assert",
            ])
            script = folder / "run.ys"
            script.write_text("\n".join(commands) + "\n")
            log = folder / "formal.log"
            with log.open("w") as stream:
                subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                                "--worker", str(script)], cwd=ROOT, stdout=stream,
                               stderr=subprocess.STDOUT, check=True, timeout=120)
            if "Equivalence successfully proven" not in log.read_text():
                raise RuntimeError(f"形式检查未完成：{log}")
            runs.append({"extended_multiply": extended, "operation": operation,
                         "passed": True, "log_sha256": digest(log)})
    if digest(ROOT / SOURCE) != source_hash:
        raise RuntimeError("检查期间 PE 源码发生变化")
    report = {"passed": True, "source_sha256": source_hash,
              "reference_revision": args.reference_rev,
              "reference_sha256": digest(reference),
              "operand_constraints": [], "compared_output_bits": 32, "runs": runs}
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"passed": True, "profiles": len(runs)}))


if __name__ == "__main__":
    main()
