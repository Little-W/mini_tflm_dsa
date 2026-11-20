#!/usr/bin/env python3
"""使用官方 LUT6_2 模型证明计算单元全部寄存状态及输出等价。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("rtl/npu/compute/ws_systolic_cell.sv")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "build/weight_mux_formal")
    parser.add_argument("--reference", default="4830c56")
    parser.add_argument("--iverilog", default="iverilog")
    parser.add_argument("--vvp", default="vvp")
    args = parser.parse_args()
    import pyosys
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    original = subprocess.check_output(["git", "show", f"{args.reference}:{SOURCE}"], cwd=ROOT)
    current = (ROOT / SOURCE).read_bytes()
    reference_path, current_path = out / "reference.sv", out / "current.sv"
    reference_path.write_bytes(original)
    current_path.write_bytes(current)
    library = Path(pyosys.__file__).parent / "share/xilinx/cells_sim.v"
    model = re.search(r"^module LUT6_2\b.*?^endmodule", library.read_text(), re.MULTILINE | re.DOTALL)
    if model is None:
        raise RuntimeError("Missing official LUT6_2 model")
    model_path = out / "LUT6_2.sv"
    model_path.write_text(model.group(0) + "\n")
    reports = []
    for data_width, weight_width, sum_width in ((1, 1, 2), (8, 8, 32), (16, 8, 32),
                                               (16, 16, 32), (17, 17, 40)):
        folder = out / f"d{data_width}_w{weight_width}_a{sum_width}"
        folder.mkdir(exist_ok=True)
        script = folder / "prove.ys"
        parameters = f"-GDATA_IN_WIDTH={data_width} -GWEIGHT_WIDTH={weight_width} -GACC_WIDTH={sum_width}"
        script.write_text(
            f"read_slang --top ws_systolic_cell {parameters} {shlex.quote(str(reference_path))}\n"
            "proc\nopt\nrename ws_systolic_cell reference\ndesign -stash reference\n" +
            f"read_slang --top ws_systolic_cell -D SYNTHESIS=1 {parameters} " +
            shlex.quote(str(current_path)) + " " + shlex.quote(str(model_path)) + "\n" +
            "proc\nopt\nrename ws_systolic_cell current\ndesign -stash current\n"
            "design -copy-from reference -as reference reference\n"
            "design -copy-from current -as current current\n"
            "equiv_make reference current cell_equivalence\nhierarchy -top cell_equivalence\n"
            "opt_clean\nequiv_simple -undef -seq 2\nequiv_induct -undef -seq 2\nequiv_status -assert\n")
        with (folder / "prove.log").open("w") as log:
            subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                            "--worker", str(script)], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        text = (folder / "prove.log").read_text()
        found = re.search(r"Of those cells (\d+) are proven and 0 are unproven", text)
        if found is None:
            raise RuntimeError("Missing complete equivalence result")
        reports.append(dict(data_width=data_width, weight_width=weight_width, sum_width=sum_width,
                            proven_bits=int(found[1]), passed=True))
    if current != (ROOT / SOURCE).read_bytes():
        raise RuntimeError("RTL changed during proof")
    reference_named = out / "reference_named.sv"
    reference_named.write_text(original.decode().replace(
        "module ws_systolic_cell #", "module ws_systolic_cell_reference #"))
    testbench = Path(__file__).with_name("tb_weight_mux_four_state.sv")
    simulation = out / "four_state.vvp"
    with (out / "four_state_compile.log").open("w") as log:
        subprocess.run([args.iverilog, "-g2012", "-DSYNTHESIS=1", "-s", "tb_weight_mux",
                        "-o", str(simulation), str(testbench), str(reference_named),
                        str(current_path), str(model_path)], cwd=ROOT,
                       stdout=log, stderr=subprocess.STDOUT, check=True)
    run = subprocess.run([args.vvp, str(simulation)], cwd=ROOT, capture_output=True, text=True, check=True)
    (out / "four_state.log").write_text(run.stdout + run.stderr)
    if "WEIGHT_MUX_FOUR_STATE_PASS cycles=100000 output_checks=200001" not in run.stdout:
        raise RuntimeError("Missing four-state comparison result")
    result = dict(passed=True, reference=args.reference, profiles=reports,
                  four_state_cycles=100000, four_state_output_checks=200001,
                  source_sha256=hashlib.sha256(current).hexdigest(),
                  reference_sha256=hashlib.sha256(original).hexdigest(),
                  model_sha256=hashlib.sha256(model_path.read_bytes()).hexdigest())
    (out / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
