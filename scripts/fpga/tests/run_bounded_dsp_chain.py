#!/usr/bin/env python3
"""使用官方原语模型逐周期比较两级 DSP 综合网表与完整 RTL。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mapped', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    import pyosys
    here = Path(__file__).resolve().parent
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    library = Path(pyosys.__file__).parent / 'share/xilinx/cells_sim.v'
    reference = out / 'reference.sv'
    reference.write_text((here / 'bounded_dsp_chain.sv').read_text().replace(
        'module bounded_dsp_chain', 'module bounded_reference', 1))
    sources = [args.mapped.resolve(), reference, here / 'tb_bounded_dsp_chain.sv', library]
    hashes = {str(path): digest(path) for path in sources}
    binary = out / 'simulation.vvp'
    command = ['iverilog', '-g2012', '-s', 'tb_bounded_dsp_chain', '-o', str(binary), *map(str, sources)]
    with (out / 'compile.log').open('w') as log:
        subprocess.run(command, check=True, stdout=log, stderr=subprocess.STDOUT)
    result = subprocess.run(['vvp', str(binary)], check=True, capture_output=True, text=True, timeout=120)
    (out / 'run.log').write_text(result.stdout + result.stderr)
    assert 'BOUNDED_DSP_CHAIN_PASS comparisons=40004' in result.stdout
    assert hashes == {str(path): digest(path) for path in sources}
    report = dict(passed=True, compared_cycles=40004, source_sha256=hashes,
                  binary_sha256=digest(binary), compile_command=command,
                  log_sha256=digest(out / 'run.log'))
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(dict(passed=True, compared_cycles=40004)))


if __name__ == '__main__':
    main()
