#!/usr/bin/env python3
"""证明写回器的全部公开输出和非阻塞赋值状态逐周期等价。"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("rtl/npu/writeback/oa_writer.sv")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "test"))
from scripts.rtl.source_files import input_files, with_dependencies
from rtl_reference import read_rtl_source


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def state_targets(source):
    return sorted(set(re.findall(r"\b(\w+)\s*(?:\[[^\]\n]+\])?\s*<=", source)))


def observed(source, name, registers):
    source = re.sub(r"\boa_writer\b", name, source)
    source, count = re.subn(r"output\s+logic\s+oa_calc_over\s*\n",
                            "output logic oa_calc_over,\n    output logic [8191:0] formal_state\n",
                            source, count=1)
    if count != 1:
        raise ValueError("Expected the complete public oa_writer interface")
    return source.replace("endmodule", "    assign formal_state = {" + ", ".join(registers) + "};\nendmodule", 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rtl", type=Path, default=ROOT / SOURCE)
    parser.add_argument("--reference", default="7ff66a59")
    parser.add_argument("--reference-rtl", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--synthesis", action="store_true")
    parser.add_argument("--profiles", nargs="+", default=[
        "4:32:4", "8:64:6", "16:32:7", "16:64:8", "16:64:16", "16:64:29",
        "16:64:32", "32:64:32", "4:32:4:4", "8:64:8:8", "8:64:9:9"])
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = args.rtl.read_text()
    reference = args.reference_rtl.read_text() if args.reference_rtl else \
        read_rtl_source(f"{args.reference}:{SOURCE}", cwd=ROOT, text=True)
    registers = state_targets(reference)
    if registers != state_targets(current):
        raise ValueError("The two modules must preserve the same complete register set")
    dependencies = with_dependencies([args.rtl.resolve()], ROOT)
    tracked = input_files(dependencies, ROOT)
    hashes = {str(path): digest(path) for path in tracked}
    for name, source in (("gold", reference), ("gate", current)):
        (out / f"{name}.sv").write_text(observed(source, name, registers))
    rows = []
    for profile in args.profiles:
        values = list(map(int, profile.split(":")))
        lanes, bus, count = values[:3]
        width = values[3] if len(values) > 3 else 32
        enabled = values[4] if len(values) > 4 else 1
        label = f"n{lanes}_b{bus}_c{count}_r{width}_is{enabled}"
        parameters = f"-GVLEN={lanes} -GBUS_WIDTH={bus} -GCOUNT_WIDTH={count} -GREG_WIDTH={width} -GENABLE_IS_MODE={enabled}"
        if args.synthesis:
            parameters += " -D SYNTHESIS=1"
        commands = []
        for name in ("gold", "gate"):
            sources = [out / f"{name}.sv", *dependencies[1:]]
            commands.extend([f"read_slang --top {name} {parameters} " + " ".join(shlex.quote(str(path)) for path in sources),
                             f"prep -top {name} -flatten"])
            if name == "gold":
                commands.append("design -stash gold")
        commands.extend(["design -copy-from gold -as gold gold", "equiv_make gold gate equiv",
                         "hierarchy -top equiv", "equiv_simple", "equiv_induct -seq 2", "equiv_status -assert"])
        script, log = out / f"{label}.ys", out / f"{label}.log"
        script.write_text("\n".join(commands) + "\n")
        with log.open("w") as stream:
            subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"), "--worker", str(script)],
                           cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=180)
        text = log.read_text()
        if "Equivalence successfully proven!" not in text:
            raise ValueError("Incomplete equivalence proof: " + str(log))
        matches = re.findall(r"Found (\d+) \$equiv cells in equiv", text)
        rows.append(dict(passed=True, vlen=lanes, bus_width=bus, count_width=count, register_width=width,
                         enable_is_mode=enabled, proved_points=int(matches[-1]), log_sha256=digest(log)))
        print(json.dumps(rows[-1]), flush=True)
    if hashes != {str(path): digest(path) for path in tracked}:
        raise ValueError("RTL inputs changed during proof")
    report = dict(passed=True, reference=args.reference if not args.reference_rtl else None,
                  source_sha256=hashes, reference_sha256=hashlib.sha256(reference.encode()).hexdigest(),
                  all_public_outputs_compared_each_cycle=True, all_state_registers=registers,
                  input_value_constraints=[], handshake_constraints=[], synthesis_define=args.synthesis,
                  profiles=rows)
    (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
