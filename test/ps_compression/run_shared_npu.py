#!/usr/bin/env python3
"""Verify configurable IA/PS banks through the complete GEMM/im2col datapath."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "test/conv_npu"))
import run as npu


def configure(directory, *, banks, r, w, control=0):
    path = directory / "config.mem"
    words = [int(value, 16) for value in path.read_text().split()]
    rows, cols = (words[5], words[3]) if words[8] else (words[3], words[5])
    row_tiles, col_tiles = (rows + 15) // 16, (cols + 15) // 16
    row_groups, col_groups = (row_tiles + r - 1) // r, (col_tiles + w - 1) // w
    words[6], words[7] = r, w
    words[30] = row_groups | (col_groups << 16)
    words[31] = ((row_tiles - 1) % r + 1) | (((col_tiles - 1) % w + 1) << 16)
    words[61], words[62] = control, banks
    path.write_text("".join(f"{value:08x}\n" for value in words))
    metadata = json.loads((directory / "case.json").read_text())
    metadata["shared_memory"] = dict(total_bytes=14336, bank_bytes=2048,
        ia_banks=banks, ps_banks=7-banks, r=r, w=w, ps_control=control)
    (directory / "case.json").write_text(json.dumps(metadata, indent=2) + "\n")
    return directory


def zero_operands(directory):
    words = [int(value, 16) for value in (directory / "config.mem").read_text().split()]
    image = npu.load_sparse(directory / "init.mem")
    for address, count in ((words[14], words[3]*words[4]),
                           (words[15], words[5]*words[4]),
                           (words[16], words[5]*4)):
        image[address:address+count] = bytes(count)
    golden = bytearray(image)
    for row in range(words[3]):
        address = words[17] + row * words[20]
        golden[address:address+words[5]] = bytes([words[23] & 255]) * words[5]
    npu.sparse_mem(directory / "init.mem", image)
    npu.sparse_mem(directory / "golden.mem", golden)
    npu.accumulator_mem(directory / "acc.mem", [0] * (words[3]*words[5]))


def generate(out):
    out.mkdir(parents=True, exist_ok=True)
    cases = []
    reference = npu.make_reference(out)

    def gemm(name, mode, banks, r, w, *, control=0, red=35, s16=False,
             out16=False, stream_rows=None, stream_cols=None, error=0):
        sr = 16*r + 5 if stream_rows is None else stream_rows
        sc = 16*w + 3 if stream_cols is None else stream_cols
        rows, cols = (sc, sr) if mode else (sr, sc)
        directory = npu.precision_task(out, 16, name=name, rows=rows,
            reduction=red, columns=cols, dataflow=mode, lhs_s16=s16,
            output_s16=out16, expected_error=error)
        cases.append(configure(directory, banks=banks, r=r, w=w, control=control))
        return directory

    for mode in (0, 1):
        flow = "is" if mode else "ws"
        for banks, r, w, control in ((1,4,2,1), (1,4,4,0),
                                    (2,8,1,1), (2,8,3,6),
                                    (2,8,5,10), (2,8,3,7),
                                    (4,8,1,0), (4,16,5,6),
                                    (4,16,7,10)):
            gemm(f"s8_{flow}_b{banks}_r{r}_w{w}_c{control}",
                 mode, banks, r, w, control=control)
        for banks, r in ((1,4), (2,8), (4,16)):
            gemm(f"single_k_{flow}_b{banks}", mode, banks, r, 4,
                 red=16, control=1)
        gemm(f"single_k_large_directory_{flow}", mode, 4, 16, 16,
             red=16, control=1, stream_rows=261, stream_cols=259)
        directory = gemm(f"directory_pressure_{flow}", mode, 4, 8, 16,
            control=14, stream_rows=128, stream_cols=256)
        zero_operands(directory)

    gemm("s16_ws_b2", 0, 2, 4, 2, s16=True, control=1)
    gemm("s16_is_b1", 1, 1, 4, 2, s16=True, control=1)
    gemm("s16_is_b2_r8", 1, 2, 8, 3, s16=True, control=7)
    gemm("s16_output_b2", 0, 2, 4, 2, s16=True, out16=True, control=1)
    gemm("s16_single_k_b4", 0, 4, 8, 4, s16=True, red=16, control=1)
    gemm("s16_is_single_k_b4", 1, 4, 16, 4, s16=True, red=16, control=1)

    for mode in (0, 1):
        for banks, r, w, control in ((1,4,4,0), (2,8,3,6), (4,16,3,6)):
            directory = npu.task(out, 16, reference,
                name=f"conv_{mode}_b{banks}_r{r}", h=19, w=19, c=3,
                kh=3, kw=3, co=67, ph=1, pw=1, dataflow=mode,
                requested_r=2, requested_w=2, seed=9937)
            cases.append(configure(directory, banks=banks, r=r, w=w, control=control))

    for name, banks, mode, s16, control in (
            ("invalid_ia_count",3,0,False,0),
            ("invalid_wide_ia_bandwidth",1,0,True,1),
            ("invalid_raw_ps_bandwidth",4,0,False,1),
            ("invalid_s16_ps_bandwidth",4,1,True,0)):
        gemm(name, mode, banks, 2, 2, s16=s16, control=control, error=1)
        gemm(name+"_recovery",0,1,4,2,control=1)
    return cases


def validated_binary(directory):
    manifest = json.loads((directory / "build.json").read_text())
    binary = directory / "obj/Vtb_conv_npu"
    if (manifest["returncode"] or manifest["pool_bytes"] != 12288 or
            not manifest["ps_compress"] or manifest["force_raw"]):
        raise RuntimeError("Expected the 14 KiB shared-memory simulator")
    for relative, expected in manifest["source_sha256"].items():
        if hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() != expected:
            raise RuntimeError(f"Simulator source changed: {relative}")
    if hashlib.sha256(binary.read_bytes()).hexdigest() != manifest["binary_sha256"]:
        raise RuntimeError("Simulator executable differs from its build manifest")
    return binary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "build/shared_npu")
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--generate-only", action="store_true")
    parser.add_argument("--verilator", default="verilator")
    parser.add_argument("--bus-width", type=int, choices=(32, 64))
    args = parser.parse_args()
    args.bus_width = npu.axi_data_width(args.bus_width)
    out = args.out.resolve()
    cases = generate(out / "cases")
    if args.generate_only:
        print(f"Generated {len(cases)} shared-memory cases")
        return 0
    binary = (validated_binary(out / "sim") if args.skip_build else
        npu.build(out / "sim",16,args.verilator,args.jobs,
                  ps_compress=True,pool_bytes=12288,bus_width=args.bus_width,
                  shared_bank_bytes=2048,shared_bank_count=7))
    if json.loads((out / "sim/build.json").read_text()).get("bus_width", 32) != args.bus_width:
        raise RuntimeError("Simulator AXI data width differs from the requested configuration")
    result = npu.run_suite(binary,out,"shared_allocation",cases,False)
    measurements = result["measurements"]
    pressure_checked = result["passed"] and all(
        measurements[index]["pressure_events"] > 0
        for index,directory in enumerate(cases)
        if directory.name.startswith("directory_pressure"))
    summary = dict(passed=result["passed"] and pressure_checked,
        expected_cases=len(cases), completed_cases=len(measurements),
        total_bytes=14336,bank_bytes=2048,physical_banks=7,bus_width=args.bus_width,
        int32_checks=sum(value["int32_checks"] for value in measurements),
        simulator_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
        suite=result,cases=[dict(name=directory.name,measurements=measurement)
                           for directory,measurement in zip(cases,measurements)])
    (out / "summary.json").write_text(json.dumps(summary,indent=2)+"\n")
    if not summary["passed"]:
        return 1
    print("SHARED_NPU_PASS", summary["completed_cases"], summary["int32_checks"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
