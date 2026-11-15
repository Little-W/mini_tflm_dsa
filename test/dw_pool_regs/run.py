#!/usr/bin/env python3
"""Verify DW/pooling AXI-Lite registers, byte writes and task exclusion."""
import argparse
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verilator', default='verilator')
    parser.add_argument('--out', type=Path, default=ROOT / 'build/dw_pool_regs')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    cmd = [args.verilator, '--binary', '--timing', '--assert', '-Wno-fatal',
           '--top-module', 'tb_dw_pool_regs', '--Mdir', str(out / 'obj'),
           '-j', '2', str(ROOT / 'rtl/npu/conv/00_conv_im2col_pkg.sv'),
           str(ROOT / 'rtl/axi_top/npu_axil_reg_if.sv'),
           str(ROOT / 'test/dw_pool_regs/tb_dw_pool_regs.sv')]
    with (out / 'build.log').open('w') as stream:
        build = subprocess.run(cmd, stdout=stream, stderr=subprocess.STDOUT)
    if build.returncode:
        print((out / 'build.log').read_text()[-8000:])
        return build.returncode
    run = subprocess.run([str(out / 'obj/Vtb_dw_pool_regs')],
                         text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (out / 'run.log').write_text(run.stdout)
    passed = run.returncode == 0 and 'DW_POOL_REGS_PASS' in run.stdout
    (out / 'summary.json').write_text(json.dumps({
        'passed': passed, 'returncode': run.returncode,
        'build_command': cmd, 'result': run.stdout.strip()}, indent=2) + '\n')
    print(run.stdout)
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
