#!/usr/bin/env python3
"""检查 INT32 向量加法的进位、流水有效信号、清空和无效周期保持。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources = [root / 'test/registered_vector_add/tb.sv',
               root / 'rtl/npu/compute/registered_vector_add.sv']
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    hashes = {str(path.relative_to(root)): digest(path) for path in sources}
    simulation_sources = []
    for source in sources:
        prepared = out / source.name
        prepared.write_text(source.read_text().replace(
            'parameter int unsigned', 'parameter integer').replace(
            'localparam int unsigned', 'localparam integer'))
        simulation_sources.append(prepared)
    binary = out / 'test.vvp'
    command = ['iverilog', '-g2012', '-s', 'tb_registered_vector_add',
               '-o', str(binary), *map(str, simulation_sources)]
    result = subprocess.run(command, capture_output=True, text=True, cwd=root)
    (out / 'compile.log').write_text(result.stdout + result.stderr)
    result.check_returncode()
    result = subprocess.run(['vvp', str(binary)], capture_output=True, text=True,
                            cwd=root, timeout=180)
    (out / 'run.log').write_text(result.stdout + result.stderr)
    result.check_returncode()
    if 'VECTOR_ADD_PASS' not in result.stdout:
        raise RuntimeError('Missing completion record')
    if any(digest(root / name) != value for name, value in hashes.items()):
        raise RuntimeError('Compilation inputs changed during the run')
    summary = dict(passed=True, source_sha256=hashes, compile_command=command,
                   result=result.stdout.strip())
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(result.stdout, end='')


if __name__ == '__main__':
    main()
