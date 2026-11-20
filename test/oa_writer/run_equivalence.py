#!/usr/bin/env python3
"""比较输出写回控制的全部公开输出，包括暂停和配置重载期间。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("rtl/npu/writeback/oa_writer.sv")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", default="aa2ef9a3")
    parser.add_argument("--out", type=Path, default=ROOT / "build/oa_writer_equivalence")
    parser.add_argument("--profiles", nargs="+", default=["4:32:8", "8:64:8", "16:32:16",
                                                         "16:64:16", "16:64:28", "16:64:32", "32:64:32"])
    parser.add_argument("--scenarios", type=int, default=512)
    parser.add_argument("--cycles", type=int, default=2048)
    parser.add_argument("--verilator", default="verilator")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    original = subprocess.check_output(["git", "show", f"{args.reference}:{SOURCE}"], cwd=ROOT, text=True)
    reference = out / "oa_writer_ref.sv"
    reference.write_text(re.sub(r"\boa_writer\b", "oa_writer_ref", original))
    sources = [ROOT / SOURCE, Path(__file__).with_name("tb_equivalence.sv")]
    hashes = {str(path.relative_to(ROOT)): digest(path) for path in sources}
    reports = []
    for profile in args.profiles:
        size, bus, count = map(int, profile.split(":"))
        folder = out / f"n{size}_b{bus}_c{count}"
        folder.mkdir(exist_ok=True)
        command = [args.verilator, "--binary", "--timing", "--assert", "-Wno-fatal", "-j", "1",
                   "--top-module", "tb_oa_writer_equivalence", "--Mdir", str(folder / "obj"),
                   f"-GVLEN={size}", f"-GBUS_WIDTH={bus}", f"-GCOUNT_WIDTH={count}",
                   f"-GSCENARIOS={args.scenarios}", f"-GCYCLES_PER_SCENARIO={args.cycles}",
                   *map(str, sources), str(reference)]
        with (folder / "compile.log").open("w") as log:
            result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError(f"Compilation failed: {folder / 'compile.log'}")
        binary = folder / "obj/Vtb_oa_writer_equivalence"
        result = subprocess.run([str(binary)], cwd=ROOT, text=True, capture_output=True)
        (folder / "run.log").write_text(result.stdout + result.stderr)
        match = re.search(r"OA_WRITER_EQ_PASS (.*)", result.stdout)
        if result.returncode or match is None:
            raise RuntimeError(result.stdout + result.stderr)
        counters = {key: int(value) for key, value in re.findall(r"(\w+)=(\d+)", match.group(1))}
        reports.append(dict(vlen=size, bus_width=bus, count_width=count, passed=True,
                            binary_sha256=digest(binary), **counters))
        print(json.dumps(reports[-1]), flush=True)
    if hashes != {str(path.relative_to(ROOT)): digest(path) for path in sources}:
        raise RuntimeError("Sources changed during verification")
    (out / "summary.json").write_text(json.dumps(dict(passed=True, reference=args.reference,
        source_sha256=hashes, reference_sha256=hashlib.sha256(original.encode()).hexdigest(),
        profiles=reports), indent=2) + "\n")


if __name__ == "__main__":
    main()
