#!/usr/bin/env python3
"""Check the production Conv data RAM's logical synchronous 1R1W inference."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCE = ROOT / "rtl/npu/conv/conv_sdp_ram.sv"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yosys", default="yosys")
    parser.add_argument("--out", type=Path, default=ROOT / 'build/conv_ram_inference')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    status = {
        "scope": "generic Yosys memory inference; not device mapping, full-NPU synthesis, timing or power",
        "status": "FAIL",
        "source_sha256": {str(SOURCE.relative_to(ROOT)): hashlib.sha256(SOURCE.read_bytes()).hexdigest()},
    }
    log = out / "yosys.log"
    netlist = out / "ram.json"
    try:
        executable = shutil.which(args.yosys)
        if executable is None:
            raise RuntimeError(f"Yosys executable not found: {args.yosys}")
        status["version"] = subprocess.check_output([executable, "-V"], text=True).strip()
        # Paths are quoted for Yosys's own command parser, never passed to a shell.
        quote = lambda path: '"' + str(path).replace('\\', '\\\\').replace('"', '\\"') + '"'
        script = (
            f"read_verilog -sv {quote(SOURCE)}; hierarchy -top conv_sdp_ram; "
            "proc; opt; memory_dff; memory_share; memory_collect; stat; "
            f"write_json {quote(netlist)}"
        )
        command = [executable, "-Q", "-T", "-p", script]
        status["command"] = command
        with log.open("w") as stream:
            subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=120)
        cells = json.loads(netlist.read_text())["modules"]["conv_sdp_ram"]["cells"]
        memories = [cell for cell in cells.values() if cell["type"] == "$mem_v2"]
        if len(memories) != 1:
            raise RuntimeError(f"Expected one inferred memory, found {len(memories)}")
        memory = memories[0]
        expected = {"SIZE": 1024, "WIDTH": 32, "ABITS": 10,
                    "RD_PORTS": 1, "WR_PORTS": 1,
                    "RD_CLK_ENABLE": 1, "WR_CLK_ENABLE": 1,
                    "RD_CLK_POLARITY": 1, "WR_CLK_POLARITY": 1}
        observed = {key: int(memory["parameters"][key], 2) for key in expected}
        status["memory"] = observed
        if observed != expected:
            raise RuntimeError(f"Unexpected inferred memory parameters: {observed}")
        enables = memory["connections"]["WR_EN"]
        byte_enables = [enables[i:i + 8] for i in range(0, 32, 8)]
        if len(enables) != 32 or any(len(set(group)) != 1 for group in byte_enables):
            raise RuntimeError("Write enable does not preserve eight-bit byte lanes")
        if len({group[0] for group in byte_enables}) != 4:
            raise RuntimeError("Expected four independent write-byte enables")
        status["independent_write_byte_enables"] = 4
        status["status"] = "PASS"
    except (OSError, RuntimeError, KeyError, subprocess.SubprocessError) as error:
        status["reason"] = str(error)
    (out / "status.json").write_text(json.dumps(status, indent=2) + "\n")
    print(json.dumps(status, indent=2))
    return 0 if status["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
