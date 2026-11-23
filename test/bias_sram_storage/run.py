#!/usr/bin/env python3
"""检查实际偏置缓冲与 SRAM 功能模型的逐周期四态行为。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'scripts/rtl'))
from source_files import with_dependencies


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def icarus_source(text: str) -> str:
    return text.replace('parameter int unsigned', 'parameter integer').replace(
        'localparam int unsigned', 'localparam integer')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--profiles', nargs='+', default=['32:16', '64:16', '32:32', '64:32', '32:3', '64:3'])
    parser.add_argument('--cycles', type=int, default=32768)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    (out / 'summary.json').unlink(missing_ok=True)
    rtl_path = ROOT / 'rtl/npu/loaders/bias_loader_buffer.sv'
    sources = with_dependencies([rtl_path], ROOT)
    sources += [ROOT / 'asic/rtl/smic40_sram_1r1w.sv',
                ROOT / 'test/asic_regfile/sram_model.sv', HERE / 'tb_storage.sv']
    sources = list(dict.fromkeys(sources))
    inputs, compiled, hashes = [], [], {}
    for source in sources:
        relative = source.relative_to(ROOT)
        saved = out / 'source' / relative
        saved.parent.mkdir(parents=True, exist_ok=True)
        saved.write_bytes(source.read_bytes())
        hashes[str(relative)] = digest(saved)
        inputs.append(saved)
        target = out / 'compiled' / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(icarus_source(saved.read_text()))
        compiled.append(target)

    # 同一个缓冲区连接行为级存储，比较完整公开输出和 SRAM 实现的周期行为。
    regfile = next(path for path in inputs if path.name == 'regfile.v')
    buffer = next(path for path in inputs if path.name == 'bias_loader_buffer.sv')
    reference = out / 'compiled/reference.sv'
    reference.write_text('`undef ASIC_SRAM\n' + icarus_source(re.sub(
        r'\bregfile\b', 'regfile_reference', regfile.read_text())) +
        '\n`define ASIC_SRAM\n' + icarus_source(re.sub(
            r'\bregfile\b', 'regfile_reference', re.sub(
                r'\bbias_loader_buffer\b', 'bias_loader_buffer_reference', buffer.read_text()))))
    compiled.append(reference)

    results = []
    for profile in args.profiles:
        bus, groups = map(int, profile.split(':'))
        folder = out / f'bus{bus}_groups{groups}'
        folder.mkdir(exist_ok=True)
        binary = folder / 'simulation.vvp'
        command = ['iverilog', '-g2012', '-DASIC_SRAM', '-s', 'tb_bias_sram_storage',
                   f'-Ptb_bias_sram_storage.p_bus_width={bus}',
                   f'-Ptb_bias_sram_storage.p_group_blocks={groups}',
                   f'-Ptb_bias_sram_storage.p_cycles={args.cycles}', '-o', str(binary),
                   *map(str, compiled)]
        with (folder / 'build.log').open('w') as stream:
            subprocess.run(command, check=True, stdout=stream, stderr=subprocess.STDOUT, timeout=120)
        run = subprocess.run(['vvp', str(binary)], capture_output=True, text=True, timeout=180)
        log = folder / 'run.log'
        log.write_text(run.stdout + run.stderr)
        match = re.search(r'^BIAS_STORAGE_PASS (.+)$', run.stdout, re.M)
        if run.returncode or not match:
            raise RuntimeError(str(log))
        row = {key: int(value) for key, value in re.findall(r'(\w+)=(\d+)', match.group(1))}
        row.update(passed=True, BUS_WIDTH=bus, GROUP_BLOCKS_MAX=groups,
                   command=command, build_log_sha256=digest(folder / 'build.log'),
                   run_log_sha256=digest(log))
        results.append(row)
        (folder / 'result.json').write_text(json.dumps(row, indent=2) + '\n')
        print(json.dumps({key: row[key] for key in ('passed', 'BUS_WIDTH', 'GROUP_BLOCKS_MAX',
                                                    'cycles', 'comparisons')}), flush=True)
    unchanged = all(digest(ROOT / name) == value for name, value in hashes.items())
    if not unchanged:
        raise RuntimeError('测试期间源文件发生变化')
    summary = dict(passed=True, source_sha256=hashes, profiles=results,
                   compiled_sha256={str(path.relative_to(out)): digest(path) for path in compiled},
                   runner_sha256=digest(Path(__file__)), source_unchanged=unchanged,
                   all_public_outputs_compared_each_cycle=True,
                   four_state_comparison=True, macro_collision_assertions=True,
                   cycles=sum(row['cycles'] for row in results),
                   comparisons=sum(row['comparisons'] for row in results))
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')


if __name__ == '__main__':
    main()
