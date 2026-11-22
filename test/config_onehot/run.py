#!/usr/bin/env python3
"""证明幂次检查的全部输入编码，并测量查找表数量及组合层数。"""
import argparse
import collections
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "rtl/common/onehot_check.sv"


def run_script(script, log):
    with log.open("w") as stream:
        subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                        "--worker", str(script)], cwd=ROOT, stdout=stream,
                       stderr=subprocess.STDOUT, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--widths", type=int, nargs="+",
                        default=[1, 2, 5, 6, 8, 16, 17, 31, 32, 33, 64, 65, 128])
    parser.add_argument("--synthesize", action="store_true")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    harness = out / "formal.sv"
    harness.write_text("""module onehot_formal #(
    parameter int p_width=32,
    parameter bit p_allow_zero=0
) (
    input logic [p_width-1:0] value,
    output logic equivalent
);
    logic [p_width-1:0] decremented;
    logic candidate, reference;
    onehot_check #(.p_width(p_width), .p_allow_zero(p_allow_zero))
        u_candidate (.i_value(value), .o_valid(candidate));
    assign decremented = value - p_width'(1);
    assign reference = ((value & decremented) == '0) && (p_allow_zero || value != '0);
    assign equivalent = candidate == reference;
endmodule
""")
    summary = {
        "passed": False,
        "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        "method": "SAT over every input encoding against arithmetic reference",
        "inputs_constrained": False,
        "runs": [],
    }
    for width in args.widths:
        if width < 1:
            raise ValueError("Width must be positive")
        for allow_zero in (0, 1):
            for configuration, defines in (("generic", ""), ("fpga", "-DXILINX_FPGA=1")):
                label = f"w{width}_zero{allow_zero}_{configuration}"
                folder = out / label
                folder.mkdir(exist_ok=True)
                script = folder / "run.ys"
                script.write_text(
                    f"read_slang --top onehot_formal -Gp_width={width} "
                    f"-Gp_allow_zero={allow_zero} {defines} " +
                    " ".join(shlex.quote(str(p)) for p in (SOURCE, harness)) + "\n"
                    "prep -top onehot_formal -flatten\n"
                    "delete t:$specify2\n"
                    "check -assert\n"
                    "sat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
                log = folder / "formal.log"
                run_script(script, log)
                if "SAT proof finished - no model found: SUCCESS!" not in log.read_text():
                    raise RuntimeError("Missing complete-input proof: " + label)
                record = {"width": width, "allow_zero": bool(allow_zero),
                          "configuration": configuration,
                          "passed": True}
                summary["runs"].append(record)
                print(json.dumps(record), flush=True)
    if args.synthesize:
        sys.path.insert(0, str(ROOT / "scripts/fpga"))
        import open_fpga_synth
        import pyosys
        library = Path(pyosys.__file__).parent / "share/xilinx/cells_sim.v"
        summary["synthesis"] = []
        reference = out / "reference.sv"
        reference.write_text("""module onehot_reference (
    input logic [31:0] i_value,
    output logic o_valid
);
    assign o_valid = i_value != 32'd0 && (i_value & (i_value - 32'd1)) == 32'd0;
endmodule
""")
        for label, top, sources, options in (
            ("reference", "onehot_reference", [reference], ""),
            ("current", "onehot_check", [SOURCE], "-Gp_width=32"),
        ):
            folder = out / ("synth_" + label)
            folder.mkdir(exist_ok=True)
            mapped = folder / "mapped.json"
            script = folder / "run.ys"
            primitive_options, _ = open_fpga_synth.primitive_models(
                folder, [str(p) for p in sources], library.parent)
            script.write_text(f"read_slang --top {top} {options} {primitive_options} " +
                              " ".join(shlex.quote(str(p)) for p in sources) + "\n" +
                              "read_verilog -lib -specify -overwrite +/xilinx/cells_sim.v\n" +
                              f"synth_xilinx -top {top} -family xc7 -noiopad -noclkbuf -flatten\n"
                              "check -assert\nstat -tech xilinx\nwrite_json " + shlex.quote(str(mapped)) + "\n")
            run_script(script, folder / "synthesis.log")
            cells = json.loads(mapped.read_text())["modules"][top]["cells"]
            counts = collections.Counter(c["type"] for c in cells.values())
            record = {
                "label": label, "width": 32,
                "logic_lut_cells": sum(n for k, n in counts.items() if re.fullmatch(r"LUT[1-6](?:_2)?", k)),
                "carry4": counts["CARRY4"],
                "combinational_cells": len(open_fpga_synth.logic_depth(cells)),
                "cell_counts": dict(sorted(counts.items())),
            }
            summary["synthesis"].append(record)
            print(json.dumps(record), flush=True)
    summary["passed"] = True
    if summary["source_sha256"] != hashlib.sha256(SOURCE.read_bytes()).hexdigest():
        raise RuntimeError("Source changed while validation was running")
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    main()
