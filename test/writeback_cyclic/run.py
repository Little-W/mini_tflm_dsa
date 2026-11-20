#!/usr/bin/env python3
"""逐周期比较循环分组 FIFO 与原有输出 FIFO。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--bus-width", type=int, choices=(32, 64), required=True)
    parser.add_argument("--banks", type=int, choices=(16, 32), default=16)
    parser.add_argument("--verilator", default="verilator-modern")
    parser.add_argument("--reference-rev", default="b8b34d5")
    parser.add_argument("--cyclic", type=int, choices=(0, 1), default=1)
    parser.add_argument("--fpga", action="store_true")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources = [ROOT / "rtl/common/REGFILE.v", ROOT / "rtl/npu/writeback/vec_s8_to_fifo.sv",
               ROOT / "rtl/npu/writeback/vec_s16_to_fifo.sv"]
    hashes = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    import pyosys
    library = Path(pyosys.__file__).parent / "share/xilinx/cells_sim.v"
    model = out / "lut6_2.sv"
    model_text = re.search(r"^module LUT6_2\b.*?^endmodule", library.read_text(), re.M | re.S)[0]
    model.write_text(re.sub(r"\bspecify\b.*?\bendspecify\b", "", model_text, flags=re.S) + "\n")
    sources.append(model)
    reference_hashes = {}
    for filename in ("vec_s8_to_fifo.sv", "vec_s16_to_fifo.sv"):
        original = subprocess.check_output(["git", "show", args.reference_rev + ":rtl/npu/writeback/" + filename],
                                           cwd=ROOT, text=True)
        reference_hashes[filename] = hashlib.sha256(original.encode()).hexdigest()
        renamed = original.replace("vec_s8_to_fifo", "vec_s8_to_fifo_ref").replace(
            "vec_s16_to_fifo", "vec_s16_to_fifo_ref").replace("vec_s8_fifo_row_ram", "vec_s8_fifo_row_ram_ref").replace(
            "fifo_bank_watermark", "fifo_bank_watermark_ref")
        path = out / filename.replace(".sv", "_ref.sv")
        path.write_text(renamed)
        sources.append(path)
    testbench = (ROOT / "test/writeback_bus/tb_writeback_bus.sv").read_text().replace(
        "vec_s8_to_fifo #(", f"vec_s8_to_fifo #(.p_cyclic_storage(1\'b{args.cyclic}), ")
    testbench = testbench.replace("localparam int BANKS = 16;", f"localparam int BANKS = {args.banks};")
    tb = out / "tb_writeback_cyclic.sv"
    tb.write_text(testbench)
    command = [args.verilator, "--binary", "--timing", "--assert", "-Wno-fatal",
               "--top-module", "tb_writeback_bus", f"-DTB_BUS_WIDTH={args.bus_width}",
               *( ["-DXILINX_FPGA"] if args.fpga else ["-DASIC_SYNTHESIS"]),
               "-DWRITEBACK_COMPARE_REFERENCE", "--Mdir", str(out / "obj"), "-j", "2", *map(str, sources), str(tb)]
    with (out / "build.log").open("w") as stream:
        subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
    result = subprocess.run([str(out / "obj/Vtb_writeback_bus")], cwd=ROOT,
                            capture_output=True, text=True, timeout=120)
    (out / "run.log").write_text(result.stdout + result.stderr)
    match = re.search(r"WRITEBACK_BUS_PASS bus_width=(\d+) cases=(\d+) checked_bytes=(\d+)", result.stdout)
    summary = {"passed": result.returncode == 0 and match is not None,
               "bus_width": args.bus_width, "cyclic_storage": args.cyclic, "reference_rev": args.reference_rev,
               "banks": args.banks,
               "fpga": args.fpga, "primitive_library_sha256": hashlib.sha256(library.read_bytes()).hexdigest(),
               "sources_sha256": hashes, "reference_sha256": reference_hashes}
    if match:
        summary.update(cases=int(match[2]), checked_bytes=int(match[3]))
    summary["sources_unchanged"] = hashes == {
        name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in hashes}
    summary["passed"] &= summary["sources_unchanged"]
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2), flush=True)
    if not summary["passed"]:
        raise RuntimeError(result.stdout + result.stderr)


if __name__ == "__main__":
    main()
