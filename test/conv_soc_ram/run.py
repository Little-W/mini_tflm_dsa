#!/usr/bin/env python3
"""Real soc_axi_ram regression: narrow lanes, queues, errors and full-word throughput."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import tempfile
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--verilator', default='verilator')
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--first-read-latencies',type=int,nargs='+',default=[1,2,3,8,17])
    parser.add_argument('--baseline-commit', help='Run the unmodified RAM from this commit and retain its expected failure')
    parser.add_argument('--rtl-source', type=Path, default=ROOT/'test/models/soc_axi_ram.sv')
    parser.add_argument('--synthesis', action='store_true', help='验证 SYNTHESIS 条件下的 RTL 分支')
    parser.add_argument('--out',type=Path,default=ROOT/'build/conv_soc_ram')
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error('--jobs must be positive')
    sim = shutil.which(args.verilator)
    if not sim:
        raise SystemExit('Verilator is required; no model substitutes for this test')
    results = args.out.resolve()
    results.mkdir(parents=True, exist_ok=True)
    report = {'scope': 'SoC AXI memory protocol', 'simulator': subprocess.check_output([sim, '--version'], text=True).strip(),
              'defines': ['SYNTHESIS=1'] if args.synthesis else [], 'runs': []}
    stem = 'baseline' if args.baseline_commit else 'modified'
    configurations = [(1031, 4)] if args.baseline_commit else [(1031, 4), (1024, 1), (1031, 3)]
    all_pass = True
    with tempfile.TemporaryDirectory(prefix='conv_soc_ram_', dir=os.environ.get('TMPDIR', '/tmp')) as temporary:
        temporary = Path(temporary)
        source = args.rtl_source.resolve()
        if args.baseline_commit:
            source = temporary / 'soc_axi_ram.sv'
            source.write_bytes(read_rtl_source(f'{args.baseline_commit}:test/models/soc_axi_ram.sv', cwd=ROOT))
            report['baseline_commit'] = args.baseline_commit
        # 每个配置使用独立临时编译目录，两种等待模式完成后释放中间文件。
        report['source_sha256'] = hashlib.sha256(source.read_bytes()).hexdigest()
        report['source_file'] = str(args.rtl_source.resolve())
        report['testbench_sha256'] = hashlib.sha256((HERE / 'tb_soc_axi_ram_narrow.sv').read_bytes()).hexdigest()
        report['compile_jobs'] = args.jobs
        snapshot = results / 'source'
        snapshot.mkdir(exist_ok=True)
        resolver = runpy.run_path(str(ROOT / 'scripts/rtl/source_files.py'))
        sources = resolver['with_dependencies']([source], ROOT)
        compile_sources = []
        report['source_snapshot_sha256'] = {}
        for dependency in sources:
            relative = dependency.relative_to(ROOT) if dependency.is_relative_to(ROOT) else Path(dependency.name)
            saved = snapshot / relative
            saved.parent.mkdir(parents=True, exist_ok=True)
            saved.write_bytes(dependency.read_bytes())
            compile_sources.append(saved)
            report['source_snapshot_sha256'][str(relative)] = hashlib.sha256(saved.read_bytes()).hexdigest()
        for dw, dp, outstanding, latency in [(dw, dp, outstanding, latency) for dw in (32,64) for dp,outstanding in configurations for latency in (args.first_read_latencies if (dp,outstanding)==(1031,4) else [8])]:
            with tempfile.TemporaryDirectory(prefix=f'dw{dw}_dp{dp}_o{outstanding}_l{latency}_', dir=temporary) as build_name:
                build = Path(build_name)
                log = results / f'{stem}_dw{dw}_dp{dp}_o{outstanding}_l{latency}_build.log'
                command = [sim, '--binary', '--timing', '--assert', '-Wall', '-Wno-fatal',
                           '--top-module', 'tb_soc_axi_ram_narrow', f'-GFIRST_LATENCY={latency}', f'-GDW={dw}', f'-GDP={dp}', f'-GOUTSTANDING={outstanding}',
                           '--Mdir', str(build), '-j', str(args.jobs), *map(str, compile_sources),
                           str(HERE / 'tb_soc_axi_ram_narrow.sv')]
                if args.synthesis:
                    command.append('-DSYNTHESIS=1')
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
    report['passed'] = all_pass
    (results / f'{stem}_status.json').write_text(json.dumps(report, indent=2))
    return 0 if all_pass else 1


if __name__ == '__main__':
    raise SystemExit(main())
