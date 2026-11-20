#!/usr/bin/env python3
"""验证两项 AXI 缓冲的全部输出、寄存状态和四态数据行为。"""
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
SOURCE = Path("rtl/soc/soc_axi_pingpong_buffer.sv")
WIDTHS = (1, 2, 34, 35, 36, 54, 64, 67, 73)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", default="2f06471c")
    parser.add_argument("--out", type=Path, default=ROOT / "build/soc_pingpong")
    parser.add_argument("--iverilog", default="iverilog")
    parser.add_argument("--vvp", default="vvp")
    args = parser.parse_args()
    import pyosys

    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference = read_rtl_source(f"{args.reference}:{SOURCE}", cwd=ROOT)
    current = (ROOT / SOURCE).read_bytes()
    suffix = "module soc_axil_pingpong_buffer"
    # 通道外的 AXI 数据打包、字段宽度及实例连接全部保持一致。
    reference_wrapper = reference.decode().split(suffix, 1)[1].strip()
    current_wrapper = current.decode().split(suffix, 1)[1].removesuffix("`default_nettype wire\n").strip()
    if reference_wrapper != current_wrapper:
        raise RuntimeError("AXI wrapper contents changed")
    paths = {}
    for name, contents in (("reference", reference), ("current", current)):
        paths[name] = out / f"{name}.sv"
        paths[name].write_bytes(contents)
    library = Path(pyosys.__file__).parent / "share/xilinx/cells_sim.v"
    model = re.search(r"^module LUT6_2\b.*?^endmodule", library.read_text(), re.MULTILINE | re.DOTALL)
    if model is None:
        raise RuntimeError("Official LUT6_2 model is unavailable")
    model_path = out / "LUT6_2.sv"
    model_path.write_text(model.group(0) + "\n")
    reports = []
    for width in WIDTHS:
        folder = out / f"width_{width}"
        folder.mkdir(exist_ok=True)
        script = folder / "prove.ys"
        script.write_text(
            f"read_slang --top soc_axi_pingpong_chan -GWIDTH={width} {shlex.quote(str(paths['reference']))}\n"
            "proc\nopt\nrename soc_axi_pingpong_chan reference\ndesign -stash reference\n" +
            f"read_slang --top soc_axi_pingpong_chan -D SYNTHESIS=1 -GWIDTH={width} " +
            shlex.quote(str(paths["current"])) + " " + shlex.quote(str(model_path)) + "\n" +
            "proc\nopt\nrename soc_axi_pingpong_chan current\ndesign -stash current\n"
            "design -copy-from reference -as reference reference\n"
            "design -copy-from current -as current current\n"
            "equiv_make reference current equivalence\nhierarchy -top equivalence\n"
            "opt_clean\nequiv_simple -undef -seq 2\nequiv_induct -undef -seq 2\nequiv_status -assert\n")
        log_path = folder / "prove.log"
        with log_path.open("w") as log:
            subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                            "--worker", str(script)], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        found = re.search(r"Of those cells (\d+) are proven and 0 are unproven", log_path.read_text())
        if found is None:
            raise RuntimeError("Incomplete state and output equivalence")
        reports.append(dict(width=width, proven_bits=int(found[1]), passed=True,
                            formal_log_sha256=hashlib.sha256(log_path.read_bytes()).hexdigest()))

    named = out / "reference_named.sv"
    named.write_text(reference.decode().replace("module soc_axi_pingpong_chan #",
                                                "module soc_axi_pingpong_chan_reference #"))
    # 仿真只需要通道本体，避免重复编译未改变的外围模块。
    named.write_text(named.read_text().split(suffix, 1)[0])
    testbench = Path(__file__).with_name("tb_four_state.sv")
    simulation = out / "four_state.vvp"
    with (out / "four_state_compile.log").open("w") as log:
        subprocess.run([args.iverilog, "-g2012", "-DSYNTHESIS=1", "-s", "tb_soc_pingpong",
                        "-o", str(simulation), str(testbench), str(named), str(paths["current"]),
                        str(model_path)], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    result = subprocess.run([args.vvp, str(simulation)], cwd=ROOT, capture_output=True, text=True, check=True)
    (out / "four_state.log").write_text(result.stdout + result.stderr)
    expected = "SOC_PINGPONG_FOUR_STATE_PASS cycles=100000 widths=9 output_checks=1800009"
    if expected not in result.stdout:
        raise RuntimeError("Incomplete four-state comparison")
    if current != (ROOT / SOURCE).read_bytes():
        raise RuntimeError("RTL changed during verification")
    summary = dict(passed=True, reference=args.reference, profiles=reports,
                   all_public_outputs_compared=True, all_register_states_compared=True,
                   invalid_data_compared=True, axi_wrappers_identical=True,
                   formal_inputs_constrained=False, four_state_cycles=100000,
                   four_state_output_checks=1800009,
                   source_sha256=hashlib.sha256(current).hexdigest(),
                   reference_sha256=hashlib.sha256(reference).hexdigest(),
                   official_lut_model_sha256=hashlib.sha256(model_path.read_bytes()).hexdigest(),
                   testbench_sha256=hashlib.sha256(testbench.read_bytes()).hexdigest())
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
