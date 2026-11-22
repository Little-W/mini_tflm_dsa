#!/usr/bin/env python3
"""比较向量算术单元的完整行为及包含未知位的极值选择。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "test"))
from rtl_reference import read_rtl_source


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--reference", default="ef0dc75342997721bdc4110b2841445df962018e")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    relative = "rtl/npu/conv/vector_pe.sv"
    current = out / "current.sv"
    current_paths = [args.source_root / 'rtl/npu/conv' / name for name in
                     ('vector_pe.sv', 'registered_vector_pe.sv', 'vector_reduce_alu.sv')]
    current_hashes = {str(path): digest(path) for path in current_paths}
    current.write_text('\n'.join(path.read_text() for path in current_paths))
    reference = out / "reference.sv"
    reference.write_bytes(read_rtl_source(f"{args.reference}:{relative}", cwd=ROOT))
    common = sorted((ROOT / "rtl/common").glob("*.sv"))
    report = dict(reference=args.reference, source_sha256=digest(current),
                  reference_sha256=digest(reference), input_constraints=None, runs=[])
    cases = [(f"registered_selected{selected}", "registered_vector_pe",
              dict(p_accumulator_preselected=selected))
             for selected in (0, 1)]
    cases += [(f"extended_selected{selected}", "vector_pe",
               dict(ENABLE_EXTENDED_MULTIPLY=1, p_accumulator_preselected=selected))
              for selected in (0, 1)]
    for name, top, parameters in cases:
        commands = []
        for label, path in (("reference", reference), ("current", current)):
            options = [f"-G{k}={v}" for k, v in parameters.items()]
            commands += [" ".join(map(shlex.quote, ["read_slang", "-DASIC_SYNTHESIS", "--top", top,
                           *options, str(path), *map(str, common)])),
                         f"prep -top {top} -flatten", "opt_merge", "opt_clean",
                         f"rename {top} {label}", f"design -stash {label}"]
        commands += ["design -copy-from reference -as reference reference",
                     "design -copy-from current -as current current",
                     "equiv_make reference current equivalent", "hierarchy -top equivalent",
                     "equiv_struct -fwd -icells", "equiv_simple -seq 1", "opt_clean",
                     "equiv_induct -seq 2", "equiv_status -assert"]
        script, log = out / (name + ".ys"), out / (name + ".log")
        script.write_text("\n".join(commands) + "\n")
        with log.open("w") as stream:
            result = subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                                     "--worker", str(script)], stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=180)
        text = log.read_text()
        counts = re.search(r"Of those cells (\d+) are proven and (\d+) are unproven", text)
        passed = result.returncode == 0 and "Equivalence successfully proven" in text
        row = dict(case=name, passed=passed, equivalent_bits=int(counts[1]) if counts else None,
                   log_sha256=digest(log))
        report["runs"].append(row)
        print(json.dumps(row), flush=True)
        if not passed:
            raise RuntimeError(f"Arithmetic comparison did not complete: {log}")
    modules = []
    for label, path in (("reference", reference), ("current", current)):
        text = path.read_text()
        first = re.search(r"module vector_pe\b.*?endmodule", text, re.S)[0]
        modules.append(first.replace("module vector_pe", "module " + label, 1))
    bench = r'''
module tb;
  logic [2:0] op;
  logic signed [15:0] a, b;
  logic signed [31:0] acc;
  wire signed [31:0] reference_result, current_result;
  reference r(op, a, b, acc, reference_result);
  current c(op, a, b, acc, current_result);
  logic [66:0] stimulus, saved;
  logic [31:0] rng = 32'h83bc7325;
  integer checks = 0;
  assign {op, a, b, acc} = stimulus;
  task check;
    #1;
    if (reference_result !== current_result)
      $fatal(1, "Vector arithmetic differs for stimulus %h", stimulus);
    checks++;
  endtask
  initial begin
    for (int trial=0; trial<2048; trial++) begin
      for (int bit_index=0; bit_index<67; bit_index++) begin
        rng=rng^(rng<<13); rng=rng^(rng>>17); rng=rng^(rng<<5);
        stimulus[bit_index]=rng[0];
      end
      check();
      saved=stimulus;
      for (int bit_index=0; bit_index<67; bit_index++) begin
        stimulus=saved; stimulus[bit_index]=1'bx; check();
        stimulus=saved; stimulus[bit_index]=1'bz; check();
      end
    end
    $display("{\"passed\":true,\"checks\":%0d}", checks);
    $finish;
  end
endmodule
'''
    path, binary = out / "four_state.sv", out / "four_state.vvp"
    path.write_text("\n".join(modules) + bench)
    subprocess.run(["iverilog", "-g2012", "-s", "tb", "-o", str(binary), str(path)],
                   check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90)
    run = subprocess.run(["vvp", str(binary)], capture_output=True, text=True, timeout=90)
    (out / "four_state.log").write_text(run.stdout + run.stderr)
    if run.returncode:
        raise RuntimeError(run.stdout + run.stderr)
    report["four_state"] = json.loads(next(line for line in run.stdout.splitlines() if line.startswith("{")))
    report["passed"] = True
    report["source_sha256"] = current_hashes
    report["source_hashes_unchanged"] = all(digest(Path(path)) == value for path, value in current_hashes.items())
    if not report["source_hashes_unchanged"]:
        raise RuntimeError("RTL changed during verification")
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["four_state"]))


if __name__ == "__main__":
    main()
