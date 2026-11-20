#!/usr/bin/env python3
"""在完整 NPU 中验证实际 FPGA 偏置加法原语与 WS/IS 量化输入连接。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--verilator", default="verilator")
    parser.add_argument("--sizes", type=int, nargs="+", default=[4])
    parser.add_argument("--jobs", type=int, default=2)
    args = parser.parse_args()
    import pyosys
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    library = Path(pyosys.__file__).parent / "share/xilinx/cells_sim.v"
    models = []
    for name in ("LUT6_2", "DSP48E1", "FDRE", "CARRY4"):
        models.append(re.search(r"^module " + name + r"\b.*?^endmodule", library.read_text(),
                                re.MULTILINE | re.DOTALL).group(0))
    model_file = out / "xilinx_primitives.sv"
    model_file.write_text("\n\n".join(models) + "\n")
    verilator = shutil.which(args.verilator)
    if not verilator:
        raise RuntimeError("Cannot locate Verilator: " + args.verilator)
    wrapper = out / "verilator_xilinx"
    wrapper.write_text("#!/bin/sh\nexec " + shlex.quote(verilator) +
                       " -DXILINX_FPGA " + shlex.quote(str(model_file)) + ' "$@"\n')
    wrapper.chmod(0o755)
    command = [sys.executable, str(ROOT / "test/conv_regression/run.py"),
               "--root", str(ROOT), "--out", str(out / "integration"),
               "--verilator", str(wrapper), "--jobs", str(args.jobs),
               "--sizes", *map(str, args.sizes)]
    with (out / "integration.log").open("w") as stream:
        result = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
    summary_file = out / "integration/summary.json"
    integration = json.loads(summary_file.read_text()) if summary_file.is_file() else {}
    summary = {
        "passed": result.returncode == 0 and integration.get("passed", False),
        "returncode": result.returncode,
        "sizes": args.sizes,
        "cases": len(integration.get("cases", [])),
        "command": command,
        "primitive_library_sha256": hashlib.sha256(library.read_bytes()).hexdigest(),
        "integration_summary": str(summary_file),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    if not summary["passed"]:
        print((out / "integration.log").read_text()[-12000:])
        raise SystemExit(1)


if __name__ == "__main__":
    main()
