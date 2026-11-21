#!/usr/bin/env python3
"""检查生产 FIFO 的数值、背压稳定性及全部公开输出的逐周期行为。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

from run_formal import ROOT, SOURCE, read_rtl_source


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--reference", default="cedf4ed33661a53c8194eca1d484cdc2279d7549")
    parser.add_argument("--reference-file", type=Path)
    parser.add_argument("--bus-width", type=int, choices=(32,64), required=True)
    parser.add_argument("--banks", type=int, choices=(8,16,32,64), default=32)
    parser.add_argument("--cyclic", type=int, choices=(0,1), default=1)
    parser.add_argument("--precomputed-watermark", type=int, choices=(0,1), default=1)
    parser.add_argument("--generic", action="store_true")
    parser.add_argument("--verilator", default="verilator")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source_path = args.source_root / SOURCE
    current = source_path.read_text()
    reference = (args.reference_file.read_text() if args.reference_file else
                 read_rtl_source(f"{args.reference}:{SOURCE}", cwd=ROOT, text=True))
    dependencies = [ROOT / "rtl/common/regfile.v", ROOT / "rtl/common/parallel_prefix_add.sv",
                    ROOT / "rtl/npu/writeback/vec_s16_to_fifo.sv"]
    sources = []
    for path in dependencies:
        target = out / path.name
        shutil.copy2(path, target)
        sources.append(target)
    for label, text in (("current", current), ("reference", reference)):
        if label == "reference":
            text = text.replace("vec_s8_to_fifo", "vec_s8_to_fifo_ref").replace(
                "vec_s8_fifo_row_ram", "vec_s8_fifo_row_ram_ref").replace(
                "fifo_bank_watermark", "fifo_bank_watermark_ref")
        target = out / f"{label}.sv"
        target.write_text(text)
        sources.append(target)
    s16_reference = out / "vec_s16_to_fifo_ref.sv"
    s16_reference.write_text((out / "vec_s16_to_fifo.sv").read_text().replace(
        "vec_s16_to_fifo", "vec_s16_to_fifo_ref").replace("fifo_bank_watermark", "fifo_bank_watermark_ref"))
    sources.append(s16_reference)
    original_bench = ROOT / "test/writeback_bus/tb_writeback_bus.sv"
    text = original_bench.read_text().replace("localparam int BANKS = 16;", f"localparam int BANKS = {args.banks};")
    parameters = (f".p_cyclic_storage(1'b{args.cyclic}), "
                  f".p_precomputed_watermark(1'b{args.precomputed_watermark}), ")
    for name in ("vec_s8_to_fifo", "vec_s8_to_fifo_ref"):
        text = text.replace(name + " #(", name + " #(" + parameters)
    text = text.replace(".reserve_banks(32'd1),", ".reserve_banks(32'd1), .i_ready_bank_threshold(32'(BANKS-1)),")
    text = text.replace("    int tests = 0;", """    integer compared_cycles=0;
    always @(posedge clk) if(rst_n) compared_cycles<=compared_cycles+1;
    final $display("FIFO_READ_CYCLE_PASS compared_cycles=%0d",compared_cycles);
    int tests = 0;""")
    bench = out / "tb.sv"
    bench.write_text(text)
    hashes = {str(path):digest(path) for path in [*sources, bench]}
    command = [args.verilator, "--binary", "--timing", "--assert", "-Wno-fatal",
               "--top-module", "tb_writeback_bus", f"-DTB_BUS_WIDTH={args.bus_width}",
               "-DASIC_SYNTHESIS" if args.generic else "-DXILINX_FPGA",
               "-DWRITEBACK_COMPARE_REFERENCE", "--Mdir", str(out / "obj"), "-j", "1",
               *map(str, sources), str(bench)]
    with (out / "build.log").open("w") as stream:
        subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
    executable = out / "obj/Vtb_writeback_bus"
    result = subprocess.run([str(executable)], cwd=ROOT, capture_output=True, text=True, timeout=180)
    log = out / "run.log"
    log.write_text(result.stdout + result.stderr)
    result.check_returncode()
    numerical = re.search(r"WRITEBACK_BUS_PASS bus_width=(\d+) cases=(\d+) checked_bytes=(\d+)", result.stdout)
    cycles = re.search(r"FIFO_READ_CYCLE_PASS compared_cycles=(\d+)", result.stdout)
    if numerical is None or cycles is None:
        raise RuntimeError("FIFO 数值与逐周期比较未完成")
    if hashes != {str(path):digest(path) for path in [*sources,bench]} or current != source_path.read_text():
        raise RuntimeError("验证期间源码发生变化")
    report = dict(passed=True, bus_width=args.bus_width, banks=args.banks, cyclic=args.cyclic,
                  precomputed_watermark=args.precomputed_watermark, fpga=not args.generic,
                  cases=int(numerical[2]), checked_bytes=int(numerical[3]), compared_cycles=int(cycles[1]),
                  cycle_difference=0, source_sha256=hashlib.sha256(current.encode()).hexdigest(),
                  reference_sha256=hashlib.sha256(reference.encode()).hexdigest(),
                  sources_sha256=hashes, original_testbench_sha256=digest(original_bench),
                  log_sha256=digest(log), executable_sha256=digest(executable))
    (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
