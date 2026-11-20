#!/usr/bin/env python3
"""比较 IA 与部分和存储包装器的读写、复位和输出保持行为。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "build/regfile_wrappers")
    parser.add_argument("--reference", default="aa2ef9a3")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources = [ROOT / "rtl/common/REGFILE.v", ROOT / "rtl/npu/loaders/ia_buffer_wrapper.sv",
               ROOT / "rtl/npu/buffers/ps_buffer.sv", Path(__file__).with_name("tb_wrapper_equivalence.sv")]
    reference_files = []
    current_ps = out / "ps_buffer_exact_ram_current.sv"
    current_ps.write_text(re.search(r"\bmodule\s+ps_buffer_exact_ram\b.*?\bendmodule",
                                   sources[2].read_text(), re.DOTALL).group(0) + "\n")
    compile_sources = [sources[0], sources[1], current_ps, sources[3]]
    for module, source in (("ia_buffer_wrapper", sources[1]), ("ps_buffer_exact_ram", sources[2])):
        text = subprocess.check_output(["git", "show", f"{args.reference}:{source.relative_to(ROOT)}"],
                                       cwd=ROOT, text=True)
        body = re.search(r"\bmodule\s+" + module + r"\b.*?\bendmodule", text, re.DOTALL).group(0)
        reference = out / f"{module}_ref.sv"
        reference.write_text(re.sub(r"\b" + module + r"\b", module + "_ref", body) + "\n")
        reference_files.append(reference)
    hashes = {str(p.relative_to(ROOT)): digest(p) for p in sources}
    results = []
    for width, depth in ((32, 8), (32, 12), (64, 128), (512, 512)):
        folder = out / f"w{width}_d{depth}"
        folder.mkdir(exist_ok=True)
        command = ["verilator", "--binary", "--timing", "--assert", "-Wno-fatal", "-j", "1",
                   "--top-module", "tb_regfile_wrapper_equivalence", "--Mdir", str(folder / "obj"),
                   f"-GWIDTH={width}", f"-GDEPTH={depth}", *map(str, compile_sources), *map(str, reference_files)]
        with (folder / "build.log").open("w") as log:
            subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        binary = folder / "obj/Vtb_regfile_wrapper_equivalence"
        result = subprocess.run([str(binary)], cwd=ROOT, text=True, capture_output=True)
        (folder / "run.log").write_text(result.stdout + result.stderr)
        match = re.search(r"WRAPPER_EQ_PASS cycles=(\d+) checks=(\d+)", result.stdout)
        if result.returncode or match is None:
            raise RuntimeError(result.stdout + result.stderr)
        results.append(dict(passed=True, width=width, depth=depth, cycles=int(match[1]),
                            output_checks=int(match[2]), binary_sha256=digest(binary)))
        print(json.dumps(results[-1]), flush=True)
    if hashes != {str(p.relative_to(ROOT)): digest(p) for p in sources}:
        raise RuntimeError("Sources changed during verification")
    (out / "summary.json").write_text(json.dumps(dict(passed=True, reference=args.reference,
        source_sha256=hashes, profiles=results), indent=2) + "\n")


if __name__ == "__main__":
    main()
