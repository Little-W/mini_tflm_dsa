#!/usr/bin/env python3
"""Real soc_axi_ram regression: narrow lanes, queues, errors and full-word throughput."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--first-read-latencies',type=int,nargs='+',default=[1,2,3,8,17])
    parser.add_argument('--baseline-commit', help='Run the unmodified RAM from this commit and retain its expected failure')
    parser.add_argument('--out',type=Path,default=ROOT/'build/conv_soc_ram')
    args = parser.parse_args()
    sim = shutil.which('verilator')
    if not sim:
        raise SystemExit('Verilator is required; no model substitutes for this test')
    results = args.out.resolve()
    results.mkdir(parents=True, exist_ok=True)
    report = {'scope': 'SoC AXI memory protocol', 'simulator': subprocess.check_output([sim, '--version'], text=True).strip(), 'runs': []}
    stem = 'baseline' if args.baseline_commit else 'modified'
    configurations = [(1031, 4)] if args.baseline_commit else [(1031, 4), (1024, 1), (1031, 3)]
    all_pass = True
    with tempfile.TemporaryDirectory(prefix='conv_soc_ram_', dir=os.environ.get('TMPDIR', '/tmp')) as temporary:
        temporary = Path(temporary)
        source = ROOT / 'test/models/soc_axi_ram.sv'
        if args.baseline_commit:
            source = temporary / 'soc_axi_ram.sv'
            source.write_bytes(subprocess.check_output(['git', 'show', f'{args.baseline_commit}:test/models/soc_axi_ram.sv'], cwd=ROOT))
            report['baseline_commit'] = args.baseline_commit
        for dw, dp, outstanding, latency in [(dw, dp, outstanding, latency) for dw in (32,64) for dp,outstanding in configurations for latency in (args.first_read_latencies if (dp,outstanding)==(1031,4) else [8])]:
            build = temporary / f'dw{dw}_dp{dp}_o{outstanding}_l{latency}'
            build.mkdir()
            log = results / f'{stem}_dw{dw}_dp{dp}_o{outstanding}_l{latency}_build.log'
            command = [sim, '--binary', '--timing', '--assert', '-Wall', '-Wno-fatal',
                       '--top-module', 'tb_soc_axi_ram_narrow', f'-GFIRST_LATENCY={latency}', f'-GDW={dw}', f'-GDP={dp}', f'-GOUTSTANDING={outstanding}',
                       '--Mdir', str(build), '-j', '2', str(source), str(HERE / 'tb_soc_axi_ram_narrow.sv')]
            with log.open('w') as stream:
                built = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
            if built.returncode:
                report['runs'].append({'first_read_latency':latency,'data_bits':dw,'dp': dp, 'outstanding': outstanding, 'status': 'BUILD_FAIL', 'log': log.name})
                all_pass = False
                continue
            warnings = [line for line in log.read_text().splitlines() if line.startswith('%Warning')]
            reviewed = {'BLKSEQ', 'PROCASSINIT', 'UNUSEDSIGNAL', 'UNUSEDPARAM', 'SYNCASYNCNET'}
            unexpected = [line for line in warnings
                          if line.split(':', 1)[0].removeprefix('%Warning-') not in reviewed]
            if unexpected:
                report['runs'].append({'first_read_latency':latency,'data_bits':dw,'dp': dp, 'outstanding': outstanding, 'status': 'LINT_FAIL', 'warnings': unexpected})
                all_pass = False
                continue
            for no_random in ([1] if args.baseline_commit else [1, 0]):
                log = results / f'{stem}_dw{dw}_dp{dp}_o{outstanding}_l{latency}_random{1-no_random}.log'
                command = [str(build / 'Vtb_soc_axi_ram_narrow'), f'+NO_RANDOM={no_random}']
                if not no_random:
                    command += ['+RAM_RAND_LAT=1', '+RAM_CMD_MAX_LAT=7', '+RAM_RSP_MAX_LAT=9', '+RAM_W_MAX_LAT=3']
                with log.open('w') as stream:
                    ran = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, timeout=60)
                output = log.read_text()
                passed = ran.returncode == 0 and 'SOC_RAM_NARROW_PASS' in output
                all_pass &= passed
                report['runs'].append({'first_read_latency':latency,'data_bits':dw,'dp': dp, 'outstanding': outstanding, 'random': not no_random,
                                       'status': 'PASS' if passed else 'FAIL', 'log': log.name,
                                       'warnings': warnings,
                                       'summary': next((line for line in output.splitlines() if 'SOC_RAM_NARROW_PASS' in line), output[-1000:])})
                print(f'{stem} DW={dw} latency={latency} DP={dp} outstanding={outstanding} random={1-no_random}: {"PASS" if passed else "FAIL"}', flush=True)
    (results / f'{stem}_status.json').write_text(json.dumps(report, indent=2))
    return 0 if all_pass else 1


if __name__ == '__main__':
    raise SystemExit(main())
