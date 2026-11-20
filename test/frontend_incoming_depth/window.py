#!/usr/bin/env python3
"""运行实际 FPGA 窗口模型，并比较固定参考的事务结果和逐周期记录。"""
import argparse
import hashlib
import json
from pathlib import Path
import runpy
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = "rtl/npu/conv/conv_im2col_frontend.sv"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proof", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--verilator", default="verilator-modern")
    parser.add_argument("--reference-model", type=Path)
    args = parser.parse_args()
    proof = json.loads(args.proof.read_text())
    if not proof["passed"] or digest(ROOT / SOURCE) != proof["source_sha256"]:
        raise RuntimeError("The window model must use the proved source")
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference = None
    if args.reference_model:
        reference = json.loads((args.reference_model / "summary.json").read_text())
        if not reference["passed"] or not reference["fpga"]:
            raise RuntimeError("A completed FPGA reference is required")
        for path, expected in reference["source_sha256"].items():
            if digest(Path(path)) != expected:
                raise RuntimeError("Reference source changed: " + path)
        matched = [value for path, value in reference["source_sha256"].items() if path.endswith("/" + SOURCE)]
        if matched != [proof["reference_sha256"]]:
            raise RuntimeError("The reference frontend differs from the fixed revision")
    runner = runpy.run_path(str(ROOT / "test/window_dma/run.py"))
    command = runner["command"]

    def checked_command(arguments, log):
        command(arguments, log)
        executable = Path(arguments[0])
        if executable.name == "Vwindow_dma_top":
            # 每个模型运行后保留程序和日志，释放可重新生成的编译对象。
            for pattern in ("*.o", "*.a", "*.gch"):
                for path in executable.parent.glob(pattern):
                    path.unlink()

    runner["main"].__globals__["command"] = checked_command
    sys.argv = [str(ROOT / "test/window_dma/run.py"), "--out", str(out), "--fpga",
                "--verilator", args.verilator, "--jobs", "1"]
    if reference is None:
        sys.argv += ["--reference-ref", proof["reference_commit"]]
    runner["main"]()
    report = json.loads((out / "summary.json").read_text())
    if reference is not None:
        if (out / "resident_stream.csv").read_bytes() != (args.reference_model / "resident_stream.csv").read_bytes():
            raise RuntimeError("Resident stream cycle records differ")
        rtl = lambda item: {path.rsplit("/rtl/", 1)[1]: value for path, value in item["source_sha256"].items() if "/rtl/" in path}
        actual, expected = rtl(report), rtl(reference)
        if actual.keys() != expected.keys() or {path for path in actual if actual[path] != expected[path]} != {SOURCE.removeprefix("rtl/")}:
            raise RuntimeError("The window models differ in additional RTL")
        report.update(reference=reference, reference_ref=proof["reference_commit"],
            resident_stream_cycle_equivalent=True, reference_model=str(args.reference_model.resolve()),
            reference_model_sha256=digest(args.reference_model / "summary.json"))
    if report["tests"] != report["reference"]["tests"]:
        raise RuntimeError("Window transaction and error statistics differ")
    if digest(ROOT / SOURCE) != proof["source_sha256"]:
        raise RuntimeError("Frontend source changed during the window comparison")
    report.update(frontend_source_sha256=proof["source_sha256"],
        reference_frontend_sha256=proof["reference_sha256"],
        arithmetic_proof_sha256=digest(args.proof), transaction_statistics_equivalent=True)
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
