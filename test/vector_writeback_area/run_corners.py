#!/usr/bin/env python3
"""检查写回队列的地址进位、零长度请求和事务等待。"""
import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

from run import ROOT, HERE, SOURCE, digest, run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verilator", default="verilator")
    parser.add_argument("--reference", default="4dee27ffec4dc891daf2681379f8b3fd27fd41f2")
    parser.add_argument("--out", type=Path, default=ROOT / "build/vector_writeback_corners")
    parser.add_argument("--jobs", type=int, default=2)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference_text = subprocess.check_output(["git", "show", f"{args.reference}:{SOURCE}"],
                                             cwd=ROOT, text=True)
    reference = out / "reference.sv"
    reference.write_text(reference_text.replace("module vector_writeback #(",
                                                "module vector_writeback_reference #("))
    harness = out / "miter.sv"
    harness_text = (HERE / "miter.sv").read_text()
    harness_text = harness_text.replace("integer accepted=0, output_beats=0, resets=0;",
                                        "integer accepted=0, output_beats=0, resets=0;\n"
                                        "    integer address_carries=0,zero_requests=0,zero_last_requests=0;\n"
                                        "    integer grant_stalls=0,data_stalls=0,error_responses=0,flush_events=0;")
    harness_text = harness_text.replace("request_address=next_address;",
                                        "if (cycle%5003==4) next_address=32'hffff_fff8;\n"
                                        "            if (cycle%5003>=100 && cycle%5003<132) begin\n"
                                        "                request_valid=1;request_bytes=0;request_byte_output=1;\n"
                                        "                request_coalesce=1;request_last=0;flush=0;\n"
                                        "            end\n"
                                        "            if (cycle%5003>=4950 && cycle%5003<4970) begin\n"
                                        "                request_valid=1;request_bytes=0;request_byte_output=1;\n"
                                        "                request_coalesce=1;request_last=1;flush=0;\n"
                                        "            end\n"
                                        "            request_address=next_address;")
    harness_text = harness_text.replace("accepted=accepted+1;",
                                        "accepted=accepted+1;\n"
                                        "                if (rst_n && ({1'b0,request_address}+33'(request_bytes))>33'h0_ffff_ffff)\n"
                                        "                    address_carries=address_carries+1;\n"
                                        "                if (rst_n && request_bytes==0) begin\n"
                                        "                    zero_requests=zero_requests+1;\n"
                                        "                    if (request_last) zero_last_requests=zero_last_requests+1;\n"
                                        "                end")
    harness_text = harness_text.replace("            if (!rst_n) begin",
                                        "            if (rst_n) begin\n"
                                        "                if (wr_req[0] && !wr_granted) grant_stalls=grant_stalls+1;\n"
                                        "                if (src_wvalid[0] && !src_wready) data_stalls=data_stalls+1;\n"
                                        "                if (done[0] && error[0]) error_responses=error_responses+1;\n"
                                        "                if (flush && busy[0]) flush_events=flush_events+1;\n"
                                        "            end\n"
                                        "            if (!rst_n) begin")
    harness_text = harness_text.replace("        $finish;",
                                        "        if (address_carries==0 || zero_requests==0 || zero_last_requests==0 ||\n"
                                        "            grant_stalls==0 || data_stalls==0 || error_responses==0 || flush_events==0)\n"
                                        "            $fatal(1, \"Required corner case was not exercised\");\n"
                                        "        $display(\"WRITEBACK_CORNERS_PASS carries=%0d zero=%0d zero_last=%0d grant_stalls=%0d data_stalls=%0d errors=%0d flush=%0d\",\n"
                                        "                 address_carries,zero_requests,zero_last_requests,grant_stalls,data_stalls,error_responses,flush_events);\n"
                                        "        $finish;")
    harness.write_text(harness_text)
    hashes = {str(path.relative_to(ROOT)): digest(path)
              for path in [ROOT / SOURCE, HERE / "miter.sv", HERE / "run.py", Path(__file__).resolve()]}
    results = []
    for mode in (0, 1):
        folder = out / f"m{mode}"
        folder.mkdir(exist_ok=True)
        run([args.verilator, "--binary", "--timing", "--assert", "-j", args.jobs,
             "--top-module", "miter", "-Wno-fatal", "-GTILE=16", "-GBUS_WIDTH=64",
             f"-GBYTE_ONLY={mode}", "--Mdir", folder / "obj", harness,
             ROOT / SOURCE, reference], folder / "build.log")
        run([folder / "obj/Vmiter"], folder / "run.log")
        text = (folder / "run.log").read_text()
        match = re.search(r"WRITEBACK_EQUIVALENCE_PASS (.+)", text)
        if not match:
            raise RuntimeError("特殊输入与等待条件的逐周期比较未完成")
        result = {key: int(value) for key, value in
                  (item.split("=") for item in match.group(1).split())}
        corner_match = re.search(r"WRITEBACK_CORNERS_PASS (.+)", text)
        if not corner_match:
            raise RuntimeError("缺少特殊输入与等待条件的测试结果")
        counters = {key: int(value) for key, value in
                    (item.split("=") for item in corner_match.group(1).split())}
        if any(value == 0 for value in counters.values()):
            raise RuntimeError("必要测试条件未发生")
        result.update(passed=True, corners=counters,
                      log_sha256=digest(folder / "run.log"))
        results.append(result)
        print(match.group(0), flush=True)
        print(corner_match.group(0), flush=True)
    if any(digest(ROOT / name) != value for name, value in hashes.items()):
        raise RuntimeError("构建期间源文件发生变化")
    report = dict(passed=True, initial_address="0xfffffff8", reference=args.reference,
                  reference_sha256=hashlib.sha256(reference_text.encode()).hexdigest(),
                  source_sha256=hashes, harness_sha256=digest(harness), runs=results)
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
