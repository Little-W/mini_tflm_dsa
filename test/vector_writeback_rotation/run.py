#!/usr/bin/env python3
"""验证向量写回的完整状态、公开周期和实际 FPGA 字节输出。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("rtl/npu/conv/vector_writeback.sv")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference", default="7419df81")
    parser.add_argument("--verilator", default="verilator")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    import pyosys
    library = Path(pyosys.__file__).parent / "share/xilinx/cells_sim.v"
    model = out / "xilinx_models.sv"
    model_text = re.search(r"^module LUT6_2\b.*?^endmodule", library.read_text(), re.M | re.S).group(0)
    model.write_text(re.sub(r"\bspecify\b.*?\bendspecify\b", "", model_text, flags=re.S) + "\n")
    reference = out / "reference.sv"
    reference.write_bytes(subprocess.check_output(["git", "show", f"{args.reference}:{SOURCE}"], cwd=ROOT))
    current = out / "current.sv"
    current.write_bytes((ROOT / SOURCE).read_bytes())
    report = dict(reference_ref=args.reference, source_sha256=digest(current),
                  reference_sha256=digest(reference), primitive_library_sha256=digest(library),
                  primitive_model_sha256=digest(model), inputs_constrained=False, formal=[], numeric=[])
    profiles = [(8, 32, True), (16, 32, True), (16, 64, True), (16, 128, True),
                (32, 64, True), (16, 64, False)]
    for tile, bus_width, fpga in profiles:
        folder = out / f"formal_t{tile}_b{bus_width}_{'fpga' if fpga else 'generic'}"
        folder.mkdir(exist_ok=True)
        commands = []
        define = "-D XILINX_FPGA -D SYNTHESIS -D YOSYS -D VERIFIC" if fpga else "-D ASIC_SYNTHESIS"
        for label, source in (("reference", reference), ("current", current)):
            commands += [f"read_slang --top vector_writeback -GTILE={tile} -GBUS_WIDTH={bus_width} {define} " +
                         " ".join(shlex.quote(str(path)) for path in (source, model)),
                         "prep -top vector_writeback -flatten", "async2sync", "opt_clean",
                         "rename vector_writeback " + label, "design -stash " + label]
        commands += ["design -copy-from reference -as reference reference",
                     "design -copy-from current -as current current",
                     "equiv_make reference current equivalent", "hierarchy -top equivalent",
                     "opt_merge", "equiv_simple -short -seq 1", "opt_clean",
                     "equiv_induct -seq 1", "equiv_status -assert"]
        script, log_path = folder / "run.ys", folder / "formal.log"
        script.write_text("\n".join(commands) + "\n")
        with log_path.open("w") as log:
            subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                            "--worker", str(script)], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        log = log_path.read_text()
        if "Equivalence successfully proven" not in log:
            raise RuntimeError("Incomplete formal comparison")
        match = re.search(r"Of those cells (\d+) are proven and (\d+) are unproven", log)
        item = dict(tile=tile, bus_width=bus_width, fpga=fpga, passed=True,
                    equivalent_bits=int(match.group(1)), log_sha256=digest(log_path))
        report["formal"].append(item)
        print(json.dumps(item), flush=True)
    main_cpp = Path(__file__).with_name("main.cpp")
    for bus_width in (32, 64, 128):
        folder = out / f"sim{bus_width}"
        folder.mkdir(exist_ok=True)
        command = [args.verilator, "--cc", "--exe", "--build", "--assert", "--timing", "-Wno-fatal", "-j", "1",
                   "--top-module", "vector_writeback", "-DXILINX_FPGA", "-DNPU_SIM_ASSERT",
                   "-GTILE=16", f"-GBUS_WIDTH={bus_width}", "--Mdir", str(folder / "obj"),
                   "--output-groups", "0", "--output-split", "12000",
                   "-CFLAGS", f"-std=c++20 -O1 -DTEST_BUS_WIDTH={bus_width} -fsanitize=undefined -fno-sanitize-recover=all",
                   "-LDFLAGS", "-fsanitize=undefined",
                   "-MAKEFLAGS", "OPT_FAST=-O1 OPT_SLOW=-O0 OPT_GLOBAL=-O1 VK_PCH_I_FAST= VK_PCH_I_SLOW= CFG_CXXFLAGS_PCH=-E",
                   str(current), str(model), str(main_cpp)]
        with (folder / "compile.log").open("w") as log:
            subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        binary = folder / "obj/Vvector_writeback"
        run = subprocess.run([str(binary)], cwd=ROOT, capture_output=True, text=True, check=True)
        (folder / "run.log").write_text(run.stdout + run.stderr)
        item = json.loads(run.stdout.strip().splitlines()[-1])
        if not item["passed"]:
            raise RuntimeError("Numeric comparison incomplete")
        item.update(binary_sha256=digest(binary), log_sha256=digest(folder / "run.log"),
                    test_sha256=digest(main_cpp), compile_command=command)
        report["numeric"].append(item)
        print(json.dumps({key: value for key, value in item.items() if key != "compile_command"}), flush=True)
        for path in (folder / "obj").iterdir():
            if path.suffix in (".o", ".gch"):
                path.unlink()
    if report["source_sha256"] != digest(ROOT / SOURCE):
        raise RuntimeError("Source changed during verification")
    report["passed"] = True
    report["equivalent_bits"] = sum(item["equivalent_bits"] for item in report["formal"])
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
