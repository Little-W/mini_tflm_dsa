#!/usr/bin/env python3
"""使用生产计数宽度检查偏置容量、WS/IS 读取、驻留复用与 DMA 范围。"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/rtl'))
from source_files import with_dependencies


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--verilator', default='verilator')
    parser.add_argument('--asic', action='store_true',
                        help='使用 ASIC SRAM 功能模型，检查物理端口同址冲突')
    parser.add_argument('--lock-file', type=Path, default=ROOT.parent / 'r20_heavy.lock')
    parser.add_argument('--profiles', nargs='+', default=[f'{mode}:{bus}:{groups}' for mode in (0, 1) for bus in (32, 64) for groups in (1, 2, 4, 8, 16, 32)])
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    (out / 'summary.json').unlink(missing_ok=True)
    source_root = out / 'source'
    sources = with_dependencies([ROOT / 'rtl/npu/loaders/bias_loader.sv'], ROOT)
    if args.asic:
        sources += [ROOT / 'asic/rtl/smic40_sram_1r1w.sv',
                    ROOT / 'test/asic_regfile/sram_model.sv']
    hashes = {}
    copied = []
    for source in sources:
        relative = source.relative_to(ROOT)
        target = source_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        hashes[str(relative)] = digest(target)
        copied.append(target)
    original_tb = ROOT / 'test/bias_loader_reuse/tb_bias_loader_reuse.sv'
    text = original_tb.read_text().split('\nmodule tb_bias_loader_reuse;')[0]
    text = text.replace('.COUNT_WIDTH(12)', '.COUNT_WIDTH(29)')
    text += """
module tb_bias_vivado150 #(
  parameter integer GROUP_BLOCKS=32, BUS_WIDTH=64, IS_MODE=0
);
  wire finished;
  bias_reuse_case #(.GROUP_BLOCKS(GROUP_BLOCKS), .BUS_WIDTH(BUS_WIDTH), .IS_MODE(IS_MODE)) dut(.finished(finished));
  initial begin
    wait(finished);
    $display("BIAS_NUMERIC_PASS");
    $finish;
  end
  initial begin
    #10000000;
    $fatal(1, "Bias test timeout");
  end
endmodule
"""
    bench = source_root / 'tb_bias_vivado150.sv'
    bench.write_text(text)
    records = []
    for profile in args.profiles:
        mode, bus, groups = map(int, profile.split(':'))
        folder = out / f'mode{mode}_bus{bus}_groups{groups}'
        folder.mkdir(exist_ok=True)
        result_path, log = folder / 'result.json', folder / 'simulation.log'
        configuration = dict(IS_MODE=mode, BUS_WIDTH=bus, GROUP_BLOCKS_MAX=groups, COUNT_WIDTH=29,
                             ASIC_SRAM=args.asic,
                             source_sha256=hashes, testbench_sha256=digest(bench))
        if args.resume and result_path.exists():
            previous = json.loads(result_path.read_text())
            if all(previous.get(k) == v for k, v in configuration.items()) and previous.get('passed') and log.exists() and previous.get('run_log_sha256') == digest(log):
                records.append(previous)
                print(json.dumps({'profile': profile, 'passed': True, 'reused': True, 'scenarios': previous['case_count']}), flush=True)
                continue
        result_path.unlink(missing_ok=True)
        log.unlink(missing_ok=True)
        build = folder / 'build.log'
        obj = folder / 'obj'
        command = [args.verilator, '--binary', '--timing', '--assert', '-Wno-fatal', '-j', '1',
                   '-CFLAGS', '-std=c++20',
                   '-MAKEFLAGS', 'OPT_FAST=-O0 OPT_SLOW=-O0', '--top-module', 'tb_bias_vivado150',
                   '--Mdir', str(obj), f'-GGROUP_BLOCKS={groups}', f'-GBUS_WIDTH={bus}', f'-GIS_MODE={mode}',
                   '-DSYNTHESIS=1', '-DASIC_SRAM=1' if args.asic else '-DXILINX_FPGA=1',
                   *map(str, copied), str(bench)]
        with args.lock_file.open('a+') as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            with build.open('w') as stream:
                subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=600)
            binary = obj / 'Vtb_bias_vivado150'
            with log.open('w') as stream:
                result = subprocess.run([str(binary)], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, timeout=120)
        output = log.read_text()
        cases = [dict((key, int(value)) for key, value in re.findall(r'(\w+)=(\d+)', line))
                 for line in output.splitlines() if line.startswith('BIAS_REUSE_PASS ')]
        storage_access = [dict((key, int(value)) for key, value in re.findall(r'(\w+)=(\d+)', line))
                          for line in output.splitlines() if line.startswith('BIAS_STORAGE_ACCESS_PASS ')]
        passed = result.returncode == 0 and 'BIAS_NUMERIC_PASS' in output
        row = dict(configuration, passed=passed, case_count=len(cases), cases=cases,
                   storage_access=storage_access,
                   command=command, build_log_sha256=digest(build), run_log_sha256=digest(log),
                   binary_sha256=digest(binary))
        result_path.write_text(json.dumps(row, indent=2) + '\n')
        records.append(row)
        print(json.dumps({'profile': profile, 'passed': passed, 'scenarios': len(cases)}), flush=True)
        if not passed:
            raise RuntimeError(str(log))
        shutil.rmtree(obj)
    summary = dict(passed=True, profiles=records, case_count=sum(row['case_count'] for row in records),
                   source_sha256=hashes, testbench_sha256=digest(bench),
                   original_testbench_sha256=digest(original_tb), runner_sha256=digest(Path(__file__)),
                   worktree_matches_snapshot=all(digest(ROOT / name) == value for name, value in hashes.items()))
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')


if __name__ == '__main__':
    main()
