#!/usr/bin/env python3
"""测量同一偏置配置的 FPGA 资源，并检查 ASIC SRAM 的实际容量。"""
from __future__ import annotations

import argparse
from collections import Counter
import fcntl
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/rtl'))
from source_files import with_dependencies
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from netlist_metrics import analyze, register_origins


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='820c2b18')
    parser.add_argument('--group-blocks', type=int, choices=(16, 32), default=16)
    parser.add_argument('--lock-file', type=Path, default=ROOT.parent / 'r21_heavy.lock')
    parser.add_argument('--reuse-fpga-root', type=Path,
                        help='复用源码SHA-256相同的已有FPGA映射目录')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference = subprocess.check_output(['git', 'rev-parse', args.reference], cwd=ROOT, text=True).strip()
    paths = with_dependencies([ROOT / 'rtl/npu/loaders/bias_loader_buffer.sv'], ROOT)
    macro_paths = [ROOT / 'asic/rtl/smic40_sram_1r1w.sv',
                   ROOT / 'test/requant_group_buffer_npu/sram_blackboxes.sv']
    configurations, hashes, snapshots = {}, {}, {}
    options = ['-GSIZE=16', '-GBUS_WIDTH=64', '-GCOUNT_WIDTH=29',
               f'-GGROUP_BLOCKS_MAX={args.group_blocks}', '-Gp_share_load_index=1']
    for label in ('reference', 'current'):
        snapshots[label], hashes[label] = [], {}
        for path in paths + macro_paths:
            relative = path.relative_to(ROOT)
            content = subprocess.check_output(['git', 'show', f'{reference}:{relative}'], cwd=ROOT) \
                if label == 'reference' else path.read_bytes()
            target = out / 'source' / label / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            snapshots[label].append(target)
            hashes[label][str(relative)] = digest(target)
        configurations[label] = dict(
            top='bias_loader_buffer', sources=list(map(str, snapshots[label][:-2])),
            options=['-D', 'SYNTHESIS=1', '-D', 'XILINX_FPGA=1', *options],
            configuration=f'SIZE16, AXI64, COUNT_WIDTH29, two bias banks of {args.group_blocks * 16} INT32 elements')
    case_config = out / 'cases.json'
    case_config.write_text(json.dumps(configurations, indent=2) + '\n')
    rows = []
    for label in ('reference', 'current'):
        fpga = out / 'fpga' / label
        fpga.mkdir(parents=True, exist_ok=True)
        pre_lut = fpga / 'pre_lut.il'
        fpga_mapped = fpga / 'mapped.json'
        fpga_script = fpga / 'synthesis.ys'
        synth = 'synth_xilinx -top bias_loader_buffer -family xc7 -noiopad -noclkbuf -flatten'
        fpga_script.write_text('read_slang --top bias_loader_buffer -D SYNTHESIS=1 -D XILINX_FPGA=1 ' +
                              shlex.join([*options, *map(str, snapshots[label][:-2])]) + '\n' +
                              synth + ' -run begin:map_luts\nwrite_rtlil ' + shlex.quote(str(pre_lut)) + '\n' +
                              synth + ' -run map_luts:\ncheck -assert\nstat -tech xilinx\nwrite_json ' +
                              shlex.quote(str(fpga_mapped)) + '\n')
        reuse = False
        if args.reuse_fpga_root is not None:
            old_root = args.reuse_fpga_root.resolve()
            old_source = old_root.parent / 'source' / label
            old_cases = old_root.parent / 'cases.json'
            same_options = old_cases.exists() and json.loads(old_cases.read_text()).get(label, {}).get('options') == configurations[label]['options']
            reuse = same_options and all((old_source / path.relative_to(ROOT)).exists() and
                        digest(old_source / path.relative_to(ROOT)) == hashes[label][str(path.relative_to(ROOT))]
                        for path in paths) and all((old_root / label / name).exists()
                                                  for name in ('pre_lut.il', 'mapped.json', 'synthesis.log'))
            if reuse:
                for name in ('pre_lut.il', 'mapped.json', 'synthesis.log'):
                    shutil.copyfile(old_root / label / name, fpga / name)
        if not reuse:
            with args.lock_file.open('a+') as lock:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                with (fpga / 'synthesis.log').open('w') as stream:
                    subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                    '--worker', str(fpga_script)], cwd=ROOT, stdout=stream,
                                   stderr=subprocess.STDOUT, check=True, timeout=300)
        module = json.loads(fpga_mapped.read_text())['modules']['bias_loader_buffer']
        for name, origin in register_origins(pre_lut).items():
            if name in module['cells']:
                module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = origin
        metrics = analyze(module)
        metrics_path = fpga / 'metrics.json'
        metrics_path.write_text(json.dumps(metrics, indent=2) + '\n')
        folder = out / label
        folder.mkdir(exist_ok=True)
        mapped, script, log = folder / 'asic_structure.json', folder / 'asic_structure.ys', folder / 'asic_structure.log'
        script.write_text('read_slang --top bias_loader_buffer -D ASIC_SRAM=1 '
                          '--blackboxed-module RAMTP128X16 --blackboxed-module RAMTP1024X16 ' +
                          shlex.join([*options, *map(str, snapshots[label])]) + '\n'
                          'prep -top bias_loader_buffer -flatten\nopt_clean\nwrite_json ' +
                          shlex.quote(str(mapped)) + '\n')
        with args.lock_file.open('a+') as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            with log.open('w') as stream:
                subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                '--worker', str(script)], cwd=ROOT, stdout=stream,
                               stderr=subprocess.STDOUT, check=True, timeout=180)
        cells = json.loads(mapped.read_text())['modules']['bias_loader_buffer']['cells']
        counts = Counter(cell['type'] for cell in cells.values() if cell['type'].startswith('RAMTP'))
        if args.group_blocks == 16:
            expected = {'RAMTP128X16': 16 if label == 'reference' else 8}
        else:
            expected = {'RAMTP1024X16': 8 if label == 'reference' else 4}
        if dict(counts) != expected:
            raise RuntimeError(f'Bias SRAM instance count mismatch: {label}, {dict(counts)}')
        physical_bits = counts['RAMTP128X16'] * 128 * 16 + counts['RAMTP1024X16'] * 1024 * 16
        logical_bits = args.group_blocks * 16 * 64
        rows.append(dict(variant=label, macro_instances=dict(counts), logical_storage_bits=logical_bits,
                         physical_storage_bits=physical_bits, utilization=logical_bits / physical_bits,
                         reused_fpga_mapping=reuse,
                         fpga_resources=metrics['resources'],
                         longest_register_path_cells=metrics['paths']['longest_register_path_cells'],
                         asic_structure_sha256=digest(mapped), fpga_metrics_sha256=digest(metrics_path),
                         fpga_mapped_sha256=digest(out / 'fpga' / label / 'mapped.json')))
    if not all(digest(ROOT / name) == value for name, value in hashes['current'].items()):
        raise RuntimeError('测试期间源文件发生变化')
    result = dict(passed=True, reference_commit=reference,
                  configuration=dict(SIZE=16, BUS_WIDTH=64, COUNT_WIDTH=29,
                                     GROUP_BLOCKS_MAX=args.group_blocks, p_share_load_index=1),
                  source_sha256=hashes, variants=rows, runner_sha256=digest(Path(__file__)),
                  structural_depth_is_not_frequency=True)
    (out / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result['variants']), flush=True)


if __name__ == '__main__':
    main()
