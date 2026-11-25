#!/usr/bin/env python3
"""证明完整坐标模块在不同参数下的状态和公开输出逐周期一致。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
SOURCE = "rtl/npu/conv/conv_im2col_geometry.sv"
PROFILES = (
    dict(p_size=4, p_slot_w=2, p_lanes=1, p_line_bytes=16,
         p_register_descriptor=0, p_register_cache_request=0),
    dict(p_size=16, p_slot_w=5, p_lanes=8, p_line_bytes=128,
         p_register_descriptor=0, p_register_cache_request=1),
    dict(p_size=16, p_slot_w=5, p_lanes=16, p_line_bytes=128,
         p_register_descriptor=0, p_register_cache_request=1),
    dict(p_size=16, p_slot_w=5, p_lanes=8, p_line_bytes=128,
         p_register_descriptor=1, p_register_cache_request=1),
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(folder, name, commands):
    script, log = folder / (name + ".ys"), folder / (name + ".log")
    script.write_text("\n".join(commands) + "\n")
    with log.open("w") as stream:
        subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                        "--worker", str(script)], stdout=stream,
                       stderr=subprocess.STDOUT, check=True, timeout=900)
    return dict(script_sha256=digest(script), log_sha256=digest(log))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    revision = subprocess.check_output(["git", "rev-parse", args.reference + "^{commit}"],
                                       cwd=ROOT, text=True).strip()
    resolve = runpy.run_path(str(ROOT / "scripts/rtl/source_files.py"))["with_dependencies"]
    files = resolve([ROOT / "rtl/npu/conv/conv_im2col_pkg.sv",
                     ROOT / "rtl/npu/conv/conv_im2col_frontend_pkg.sv", ROOT / SOURCE], ROOT)
    files.append(ROOT / "include/conv_im2col_prepared_tile.svh")
    hashes, snapshots = {}, {}
    for label in ("reference", "current"):
        hashes[label], snapshots[label] = {}, []
        for original in files:
            relative = original.relative_to(ROOT)
            data = (subprocess.check_output(["git", "show", f"{revision}:{relative}"], cwd=ROOT)
                    if label == "reference" else original.read_bytes())
            path = out / "sources" / label / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            hashes[label][str(relative)] = hashlib.sha256(data).hexdigest()
            if path.suffix != ".svh":
                snapshots[label].append(path)
    records = []
    for index, parameters in enumerate(PROFILES):
        folder = out / f"profile_{index}"
        folder.mkdir(exist_ok=True)
        excluded = set()
        for label in ("reference", "current"):
            options = " ".join(f"-G{name}={value}" for name, value in parameters.items())
            commands = [
                f"read_slang --top conv_im2col_geometry -DSYNTHESIS=1 -DXILINX_FPGA=1 {options} "
                + "-I " + shlex.quote(str(out / "sources" / label / "include")) + " "
                + shlex.join(map(str, snapshots[label])),
                "setattr -mod -unset keep_hierarchy", "setattr -unset keep_hierarchy",
                "prep -top conv_im2col_geometry -flatten", "memory_map", "opt -full",
                f"rename -top {label}",
                "write_json " + shlex.quote(str(folder / (label + "_state.json"))),
                "async2sync", "opt -full", "check -assert",
                "write_rtlil " + shlex.quote(str(folder / (label + ".il"))),
            ]
            run(folder, label, commands)
            module = json.loads((folder / (label + "_state.json")).read_text())["modules"][label]
            registered = set()
            for cell in module["cells"].values():
                if re.fullmatch(r"\$(?:[a-z]*dff[a-z]*|[a-z]*latch[a-z]*|ff)", cell["type"]):
                    registered.update(bit for bit in cell["connections"].get("Q", [])
                                      if isinstance(bit, int))
            excluded.update(module["cells"])
            for name, wire in module["netnames"].items():
                if name in module["ports"]:
                    continue
                bits = {bit for bit in wire["bits"] if isinstance(bit, int)}
                if not bits or not bits <= registered:
                    excluded.add(name)
        blacklist = folder / "combinational_names.txt"
        blacklist.write_text("\n".join(sorted(excluded)) + "\n")
        proof = run(folder, "proof", [
            "read_rtlil " + shlex.quote(str(folder / "reference.il")),
            "read_rtlil " + shlex.quote(str(folder / "current.il")),
            "equiv_make -blacklist " + shlex.quote(str(blacklist)) + " reference current equivalent",
            "hierarchy -top equivalent", "opt_merge", "equiv_struct -fwd -icells",
            "equiv_simple -short -seq 1", "opt_clean",
            "equiv_induct -seq 8", "equiv_status -assert",
        ])
        match = re.search(r"Of those cells (\d+) are proven and (\d+) are unproven",
                          (folder / "proof.log").read_text())
        if match is None or int(match[2]):
            raise RuntimeError(str(folder / "proof.log"))
        record = dict(parameters=parameters, passed=True, equivalent_bits=int(match[1]),
                      unbounded_equivalence=True, proof=proof)
        records.append(record)
        print(json.dumps(record), flush=True)
    unchanged = hashes["current"] == {str(path.relative_to(ROOT)): digest(path) for path in files}
    if not unchanged:
        raise RuntimeError("验证期间 RTL 源文件发生变化")
    report = dict(passed=True, reference_commit=revision, external_input_assumptions=[],
                  internal_correspondence="真实寄存器输出和公开端口",
                  source_sha256=hashes, sources_unchanged=unchanged, profiles=records)
    (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
