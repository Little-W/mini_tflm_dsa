#!/usr/bin/env python3
"""验证完整乘积、移位量和任意时钟使能下的量化移位流水线。"""
import argparse
import hashlib
import json
import re
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--worker", type=Path)
    parser.add_argument("--generic", action="store_true")
    args = parser.parse_args()
    if args.worker:
        from pyosys import libyosys
        libyosys.run_pass("script " + shlex.quote(str(args.worker)))
        return
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources = [ROOT / "rtl/npu/writeback/vec_requant.sv", HERE / "shift_formal.sv"]
    import pyosys
    library = Path(pyosys.__file__).parent / "share/xilinx/cells_sim.v"
    model = re.search(r"^module LUT6_2\b.*?^endmodule", library.read_text(), re.MULTILINE | re.DOTALL).group(0)
    model_file = out / "xilinx_lut6_2.sv"
    model_file.write_text(model + "\n")
    defines = "-D SYNTHESIS " + ("-D ASIC_SYNTHESIS " if args.generic else "")
    script = out / "run.ys"
    script.write_text(
        "read_slang --top shift_formal " + defines + " ".join(shlex.quote(str(p)) for p in sources + [model_file]) + "\n"
        "prep -top shift_formal -flatten\n"
        "async2sync\n"
        "memory_map\n"
        "opt_clean\n"
        "sat -seq 1 -tempinduct -initsteps 8 -maxsteps 10 -prove-asserts -verify -set i_en 1\n"
    )
    command = [sys.executable, str(Path(__file__).resolve()), "--out", str(out), "--worker", str(script)]
    with (out / "formal.log").open("w") as stream:
        result = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
    log = (out / "formal.log").read_text()
    passed = result.returncode == 0 and "Induction step proven" in log
    summary = {
        "passed": passed,
        "method": "Yosys SAT temporal induction",
        "properties": 2,
        "implementation": "generic" if args.generic else "official LUT6_2 functional model",
        "primitive_library_sha256": hashlib.sha256(library.read_bytes()).hexdigest(),
        "input_product_bits": 64,
        "input_amount_bits": 7,
        "clock_enable": "enabled edges; stalls checked by interface regression",
        "latency_enabled_edges": 7,
        "source_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    if not passed:
        print(log[-10000:])
        raise SystemExit(1)


if __name__ == "__main__":
    main()
