#!/usr/bin/env python3
"""Run self-checking AXI/control RTL benches and retain every lint diagnostic."""
import argparse
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT=ROOT.parents[1]/'build/conv_frontend'
COMMON = [
    'rtl/conv_im2col_pkg.sv',  'rtl/conv_sdp_ram.sv', 'rtl/conv_next_use_predictor.sv',
    'rtl/conv_axi_span_reader.sv', 'rtl/conv_read_cache.sv', 'rtl/conv_im2col_frontend.sv',
]
RTL = ROOT.parents[1] / 'rtl/npu/conv'
COMMON = [str((RTL.parent / 'dma/cache' / Path(name).name if Path(name).name in {'conv_read_cache.sv', 'conv_sdp_ram.sv', 'conv_next_use_predictor.sv'} else RTL / Path(name).name)) for name in COMMON]
import runpy
COMMON = [str(p) for p in runpy.run_path(str(ROOT.parents[1] / "test/monitors/sources.py"))["with_observers"](COMMON)]
REVIEWED = {'UNUSEDSIGNAL', 'UNUSEDPARAM', 'BLKSEQ', 'PROCASSINIT', 'SYNCASYNCNET'}


def run(test):
    top = {'span': 'tb_conv_axi_span_reader', 'control': 'tb_conv_control'}[test]
    simulator = shutil.which('verilator')
    log = OUTPUT / f'rtl_{test}.log'
    status_path = OUTPUT / f'rtl_{test}_status.json'
    status = {'scope': f'standalone {test} RTL', 'status': 'NOT_RUN', 'log': str(log)}
    if not simulator:
        status['reason'] = 'Verilator unavailable'
        status_path.write_text(json.dumps(status, indent=2))
        return status
    build = OUTPUT / 'objects' / test
    build.mkdir(exist_ok=True, parents=True)
    files = [str(RTL / 'conv_axi_span_reader.sv')] if test == 'span' else COMMON
    command = [simulator, '--binary', '--timing', '--assert', '-Wall', '-Wno-fatal',
               '-DCONV_ASSERT','-DNPU_SIM_ASSERT', '--top-module', top, '--Mdir', str(build), '-j', '2']
    command += files + [f'tests/{top}.sv']
    status.update(command=command, simulator=simulator)
    try:
        with log.open('w') as stream:
            subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
            subprocess.run([str(build / f'V{top}')], cwd=ROOT, stdout=stream,
                           stderr=subprocess.STDOUT, check=True, timeout=120)
        output = log.read_text()
        warnings = [line for line in output.splitlines() if line.startswith('%Warning')]
        status['warnings'] = warnings
        unexpected = [line for line in warnings
                      if line.split(':', 1)[0].removeprefix('%Warning-') not in REVIEWED
]
        if unexpected:
            raise RuntimeError(f'unreviewed lint diagnostics: {unexpected}')
        marker = f'RTL_{test.upper()}_PASS'
        if marker not in output:
            raise RuntimeError(f'{marker} absent')
        status.update(status='PASS', summary=next(line for line in output.splitlines() if marker in line))
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        status.update(status='FAIL', reason=str(exc))
    status_path.write_text(json.dumps(status, indent=2))
    return status


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--test', choices=['span', 'control', 'all'], default='all')
    args = parser.parse_args()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    results = [run(test) for test in (['span', 'control'] if args.test == 'all' else [args.test])]
    print(json.dumps(results, indent=2))
    return 0 if all(result['status'] == 'PASS' for result in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
