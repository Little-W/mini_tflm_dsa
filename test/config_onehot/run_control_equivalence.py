#!/usr/bin/env python3
"""比较幂次检查接入后预测器和调度器的完整状态与输出。"""
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
CASES = {
    "predictor": ("conv_next_use_predictor", "rtl/npu/dma/cache/conv_next_use_predictor.sv", []),
    "scheduler_single": ("ps_window_scheduler", "rtl/npu/control/ps_window_scheduler.sv",
                         ["-GSIZE=4", "-GFRAME_COUNT=1", "-GMAX_REUSE_TILES=0"]),
    "scheduler_bounded": ("ps_window_scheduler", "rtl/npu/control/ps_window_scheduler.sv",
                          ["-GSIZE=16", "-GFRAME_COUNT=16", "-GMAX_REUSE_TILES=32"]),
    "scheduler_unbounded": ("ps_window_scheduler", "rtl/npu/control/ps_window_scheduler.sv",
                            ["-GSIZE=16", "-GFRAME_COUNT=4", "-GMAX_REUSE_TILES=0"]),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference-ref", default="4df62f2")
    parser.add_argument("--cases", nargs="+", choices=tuple(CASES), default=list(CASES))
    args = parser.parse_args()
    import pyosys
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    library = Path(pyosys.__file__).parent / "share/xilinx/cells_sim.v"
    model = out / "xilinx_lut_models.sv"
    model.write_text("\n".join(re.search(r"^module " + name + r"\b.*?^endmodule",
        library.read_text(), re.M | re.S).group(0) for name in ("LUT6", "LUT6_2")) + "\n")
    common = [ROOT / "rtl/npu/conv/conv_im2col_pkg.sv", ROOT / "rtl/common/onehot_check.sv", model]
    summary = {"reference_ref": args.reference_ref,
               "method": "complete-state SAT and temporal induction with official LUT primitives",
               "inputs_constrained": False, "runs": [],
               "source_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in common[:-1]},
               "primitive_library_sha256": hashlib.sha256(library.read_bytes()).hexdigest()}
    for label in args.cases:
        top, name, options = CASES[label]
        folder = out / label
        folder.mkdir(exist_ok=True)
        commands = []
        for variant in ("reference", "current"):
            source = (read_rtl_source(args.reference_ref + ":" + name, cwd=ROOT)
                      if variant == "reference" else (ROOT / name).read_bytes())
            path = folder / (variant + ".sv")
            path.write_bytes(source)
            commands += [f"read_slang --top {top} -D XILINX_FPGA " + " ".join(options) + " " +
                         " ".join(shlex.quote(str(p)) for p in [*common, path]),
                         f"prep -top {top} -flatten", "delete t:$specify2", "memory_map", "async2sync",
                         "opt_clean", f"rename {top} {variant}", f"design -stash {variant}"]
        commands += ["design -copy-from reference -as reference reference",
                     "design -copy-from current -as current current",
                     "equiv_make reference current equivalent", "hierarchy -top equivalent",
                     "equiv_simple -seq 1", "opt_clean", "equiv_induct -seq 2", "equiv_status -assert"]
        script = folder / "run.ys"
        script.write_text("\n".join(commands) + "\n")
        log = folder / "formal.log"
        with log.open("w") as stream:
            result = subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                                     "--worker", str(script)], stdout=stream, stderr=subprocess.STDOUT)
        text = log.read_text()
        proven = re.search(r"Of those cells (\d+) are proven and (\d+) are unproven", text)
        record = {"case": label, "top": top, "options": options,
                  "passed": result.returncode == 0 and "Equivalence successfully proven" in text,
                  "equivalent_bits": int(proven[1]) if proven else None,
                  "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest()}
        summary["source_sha256"][name] = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        summary["runs"].append(record)
        summary["passed"] = all(r["passed"] for r in summary["runs"])
        (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps(record), flush=True)
        if not record["passed"]:
            raise RuntimeError(text[-10000:])


if __name__ == "__main__":
    main()
