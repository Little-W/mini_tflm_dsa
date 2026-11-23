#!/usr/bin/env python3
"""在实际偏置装载协议下比较全部控制输出和有效数据的存储实现。"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/rtl'))
from source_files import with_dependencies


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='820c2b18')
    parser.add_argument('--lock-file', type=Path, default=ROOT.parent / 'r21_heavy.lock')
    parser.add_argument('--profiles', nargs='+', default=[f'{mode}:{bus}:{groups}'
                        for groups in (16, 32) for mode in (0, 1) for bus in (32, 64)])
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    (out / 'summary.json').unlink(missing_ok=True)
    reference_commit = subprocess.check_output(['git', 'rev-parse', args.reference], cwd=ROOT, text=True).strip()
    paths = with_dependencies([ROOT / 'rtl/npu/loaders/bias_loader.sv'], ROOT)
    current_paths = paths + [ROOT / 'asic/rtl/smic40_sram_1r1w.sv',
                             ROOT / 'test/asic_regfile/sram_model.sv']
    hashes = {'current': {}, 'reference': {}}
    snapshots = []
    reference_sources = {}
    for path in current_paths:
        relative = path.relative_to(ROOT)
        target = out / 'source/current' / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
        hashes['current'][str(relative)] = digest(target)
        snapshots.append(target)
    for path in paths:
        relative = path.relative_to(ROOT)
        content = subprocess.check_output(['git', 'show', f'{reference_commit}:{relative}'], cwd=ROOT, text=True)
        target = out / 'source/reference' / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        hashes['reference'][str(relative)] = digest(target)
        reference_sources[relative] = content
    modules = set().union(*(set(re.findall(r'\bmodule\s+(\w+)', source))
                            for source in reference_sources.values()))
    for relative, content in reference_sources.items():
        for name in sorted(modules, key=len, reverse=True):
            content = re.sub(r'\b' + re.escape(name) + r'\b', 'reference_' + name, content)
        target = out / 'compiled_reference' / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('`undef ASIC_SRAM\n' + content + '\n`define ASIC_SRAM\n')
        snapshots.append(target)

    bench_source = ROOT / 'test/bias_loader_reuse/tb_bias_loader_reuse.sv'
    bench_text = bench_source.read_text().split('\nmodule tb_bias_loader_reuse;')[0]
    bench_text = bench_text.replace('.COUNT_WIDTH(12)', '.COUNT_WIDTH(29)')
    start = bench_text.index('  bias_loader #(')
    end = bench_text.index('.ext_dma_wr_use_16bits(1\'b0));', start) + len('.ext_dma_wr_use_16bits(1\'b0));')
    reference_instance = bench_text[start:end].replace('bias_loader #(', 'reference_bias_loader #(').replace(
        ') dut (', ') reference (')
    for name in ('req', 'valid', 'group_valid', 'dma_start', 'dma_base', 'dma_rows',
                 'dma_len', 'dma_slot', 'data', 'scalar'):
        reference_instance = reference_instance.replace('(' + name + ')', '(reference_' + name + ')')
    observer = '''
  wire reference_req, reference_valid, reference_group_valid, reference_dma_start;
  wire [31:0] reference_dma_base, reference_dma_rows;
  wire [7:0] reference_dma_len;
  wire reference_dma_slot;
  wire signed [31:0] reference_data [SIZE], reference_scalar;
  integer protocol_control_checks = 0, protocol_scalar_checks = 0, protocol_vector_checks = 0;
'''
    observer += reference_instance + '''
  always @(posedge clk) begin
    #1;
    if (rst_n && !init_cfg) begin
      assert ({req, valid, group_valid, dma_start, dma_base, dma_rows, dma_len, dma_slot} ===
              {reference_req, reference_valid, reference_group_valid, reference_dma_start,
               reference_dma_base, reference_dma_rows, reference_dma_len, reference_dma_slot})
        else $fatal(1, "Bias protocol control differs from reference");
      protocol_control_checks++;
      if (IS_MODE && scalar_context_valid) begin
        assert (scalar === reference_scalar)
          else $fatal(1, "Bias executing scalar differs from reference cycle=%0d", cycle);
        protocol_scalar_checks++;
      end
      if (!IS_MODE && valid) begin
        for (integer lane = 0; lane < SIZE; lane++) begin
          assert (data[lane] === reference_data[lane])
            else $fatal(1, "Bias valid vector differs from reference cycle=%0d lane=%0d", cycle, lane);
          protocol_vector_checks++;
        end
      end
    end
  end
'''
    bench_text = bench_text[:end] + observer + bench_text[end:]
    bench_text = bench_text.replace('    finished = 1;', '''
    $display("BIAS_PROTOCOL_PASS controls=%0d scalar_values=%0d vector_values=%0d",
             protocol_control_checks, protocol_scalar_checks, protocol_vector_checks);
    finished = 1;''')
    bench_text += '''
module tb_bias_protocol #(parameter integer GROUP_BLOCKS=32, BUS_WIDTH=64, IS_MODE=0);
  wire finished;
  bias_reuse_case #(.GROUP_BLOCKS(GROUP_BLOCKS), .BUS_WIDTH(BUS_WIDTH), .IS_MODE(IS_MODE)) dut(.finished(finished));
  initial begin
    wait(finished);
    $finish;
  end
  initial begin
    #10000000;
    $fatal(1, "Bias protocol timeout");
  end
endmodule
'''
    bench = out / 'tb_protocol.sv'
    bench.write_text(bench_text)
    rows = []
    for profile in args.profiles:
        mode, bus, groups = map(int, profile.split(':'))
        folder = out / f'mode{mode}_bus{bus}_groups{groups}'
        folder.mkdir(exist_ok=True)
        command = ['verilator', '--binary', '--timing', '--assert', '-Wno-fatal', '-j', '1',
                   '-CFLAGS', '-std=c++20', '-MAKEFLAGS', 'OPT_FAST=-O0 OPT_SLOW=-O0',
                   '--top-module', 'tb_bias_protocol', '--Mdir', str(folder / 'obj'),
                   '-DSYNTHESIS=1', '-DASIC_SRAM=1', f'-GIS_MODE={mode}', f'-GBUS_WIDTH={bus}',
                   f'-GGROUP_BLOCKS={groups}', *map(str, snapshots), str(bench)]
        with args.lock_file.open('a+') as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            with (folder / 'build.log').open('w') as stream:
                subprocess.run(command, check=True, stdout=stream, stderr=subprocess.STDOUT, timeout=600)
            run = subprocess.run([str(folder / 'obj/Vtb_bias_protocol')], capture_output=True, text=True, timeout=120)
        log = folder / 'run.log'
        log.write_text(run.stdout + run.stderr)
        match = re.search(r'^BIAS_PROTOCOL_PASS (.+)$', run.stdout, re.M)
        if run.returncode or not match:
            raise RuntimeError(str(log))
        values = {key: int(value) for key, value in re.findall(r'(\w+)=(\d+)', match.group(1))}
        access = re.search(r'^BIAS_STORAGE_ACCESS_PASS (.+)$', run.stdout, re.M)
        rows.append(dict(passed=True, IS_MODE=mode, BUS_WIDTH=bus, GROUP_BLOCKS_MAX=groups,
                         comparisons=values, command=command,
                         storage_access={key: int(value) for key, value in re.findall(r'(\w+)=(\d+)', access.group(1))},
                         build_log_sha256=digest(folder / 'build.log'), run_log_sha256=digest(log)))
        print(json.dumps(rows[-1]['comparisons'] | dict(profile=profile, passed=True)), flush=True)
    if not all(digest(ROOT / name) == value for name, value in hashes['current'].items()):
        raise RuntimeError('测试期间源文件发生变化')
    result = dict(passed=True, reference_commit=reference_commit, source_sha256=hashes,
                  runner_sha256=digest(Path(__file__)), testbench_sha256=digest(bench),
                  original_testbench_sha256=digest(bench_source), profiles=rows)
    (out / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    main()
