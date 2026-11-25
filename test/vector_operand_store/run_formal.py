#!/usr/bin/env python3
"""展开操作数存储及其依赖，在不同参数下检查状态和输出等价。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("rtl/npu/conv/vector_engine_operand_store.sv")
PROFILES = {
    "production": (16, 64, 8, 8, 1, 0),
    "private": (16, 32, 8, 4, 0, 0),
    "tile8": (8, 64, 4, 8, 1, 0),
    "shared_quant": (16, 64, 16, 16, 1, 1),
}
PARAMETERS = ("p_tile", "p_bus_width", "p_pe_count", "p_window_lanes",
              "p_shared_storage_enable", "p_shared_quant_enable")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference", default="5adaa4c9")
    parser.add_argument("--profiles", nargs="+", choices=PROFILES, default=list(PROFILES))
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    revision = subprocess.check_output(["git", "rev-parse", args.reference + "^{commit}"],
                                       cwd=ROOT, text=True).strip()
    reference = out / "operand_reference.sv"
    reference.write_bytes(subprocess.check_output(["git", "show", f"{revision}:{SOURCE}"], cwd=ROOT))
    packages = [ROOT / "rtl/npu/conv" / name for name in
                ("conv_im2col_pkg.sv", "vector_engine_pkg.sv", "vector_engine_control_pkg.sv")]
    resolve = runpy.run_path(str(ROOT / "scripts/rtl/source_files.py"))["with_dependencies"]
    designs = {"reference": resolve(packages + [reference], ROOT),
               "candidate": resolve(packages + [ROOT / SOURCE], ROOT)}
    sources = set(path for files in designs.values() for path in files)
    hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    results = []
    for profile in args.profiles:
        folder = out / profile
        folder.mkdir(exist_ok=True)
        parameters = dict(zip(PARAMETERS, PROFILES[profile]))
        options = " ".join(f"-G{name}={value}" for name, value in parameters.items())
        commands = []
        for label, files in designs.items():
            commands += [
                "read_slang --top vector_engine_operand_store -DSYNTHESIS=1 -DXILINX_FPGA=1 " +
                options + " " + " ".join(map(str, files)),
                "setattr -mod -unset keep_hierarchy",
                "prep -top vector_engine_operand_store -flatten",
                "memory_map", "async2sync", "opt_clean",
                f"rename vector_engine_operand_store {label}",
                f"design -stash {label}",
            ]
        commands += [
            "design -copy-from reference -as reference reference",
            "design -copy-from candidate -as candidate candidate",
            "equiv_make reference candidate comparison",
            "hierarchy -top comparison",
            "equiv_simple -seq 2",
            "equiv_induct -seq 2",
            "equiv_status -assert",
        ]
        script = folder / "run.ys"
        script.write_text("\n".join(commands) + "\n")
        log_path = folder / "formal.log"
        with log_path.open("w") as log:
            subprocess.run(["python", str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                            "--worker", str(script)], stdout=log, stderr=subprocess.STDOUT,
                           check=True, timeout=args.timeout)
        matches = re.findall(r"Of those cells (\d+) are proven and (\d+) are unproven", log_path.read_text())
        if not matches or int(matches[-1][1]):
            raise RuntimeError(f"形式检查未完成：{profile}")
        result = dict(profile=profile, parameters=parameters, passed=True,
                      proven_bits=int(matches[-1][0]), unproven_bits=int(matches[-1][1]),
                      script_sha256=hashlib.sha256(script.read_bytes()).hexdigest())
        results.append(result)
        print(json.dumps(result), flush=True)
    if hashes != {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}:
        raise RuntimeError("检查期间 RTL 源文件发生变化")
    (out / "summary.json").write_text(json.dumps(dict(reference_revision=revision,
        source_sha256=hashes, profiles=results), indent=2) + "\n")


if __name__ == "__main__":
    main()
