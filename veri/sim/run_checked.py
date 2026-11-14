#!/usr/bin/env python3
"""Run a simulation and require its success message and a clean exit."""

import argparse
from pathlib import Path
import re
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--pass", dest="success")
    parser.add_argument("--uvm", action="store_true")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("a simulation command is required")
    if not args.uvm and not args.success:
        parser.error("--pass or --uvm is required")
    lines = []
    with args.log.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, errors="replace", bufsize=1)
        for line in process.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            log.write(line)
            log.flush()
            lines.append(line)
        status = process.wait()
    output = "".join(lines)
    if args.uvm:
        counts = {
            kind: re.findall(r"^" + kind + r"\s*:\s*(\d+)\s*$", output, re.MULTILINE)
            for kind in ("UVM_ERROR", "UVM_FATAL")
        }
        failed = any(not values or int(values[-1]) != 0 for values in counts.values())
        failed |= bool(re.search(r"^UVM_(?:ERROR|FATAL)\s+[^:]", output, re.MULTILINE))
    else:
        failed = args.success not in output or any(
            token in output for token in ("FAIL", "FATAL", "[TB] ERROR", "TIMEOUT")
        )
    if status or failed:
        print(f"Simulation failed; see {args.log}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
