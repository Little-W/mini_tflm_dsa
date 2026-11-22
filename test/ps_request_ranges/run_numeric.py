#!/usr/bin/env python3
"""使用独立存储模型检查 INT32 帧数据，并逐周期比较公开输出。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'test'))
from rtl_reference import read_rtl_source


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--jobs', type=int, default=1)
    parser.add_argument('--verilator',default='verilator')
    parser.add_argument('--large', action='store_true', help='Fill every data-bank word, including a 256-row frame')
    parser.add_argument('--reference', help='Compare every output cycle against this git revision')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources = [root/'test/ps_raw_store/tb.sv', root/'test/ps_raw_store/main.cpp',
               args.source_root/'rtl/npu/ps_compact/ps_frame_store.sv', root/'rtl/common/regfile.v',
               root/'rtl/common/parallel_prefix_add.sv', root/'rtl/common/add_equal.sv']
    import runpy
    dependency_reader = runpy.run_path(str(root / "scripts/rtl/source_files.py"))
    sources = dependency_reader["with_dependencies"](sources, args.source_root)
    hashes = {str(p): digest(p) for p in sources}
    reference_hash = None
    if args.reference:
        original = read_rtl_source(f'{args.reference}:rtl/npu/ps_compact/ps_frame_store.sv', cwd=root, text=True)
        reference = out/'ps_frame_store_ref.sv'
        reference.write_text(original.replace('ps_frame_store', 'ps_frame_store_ref').replace(
            'ps_raw_address', 'ps_raw_address_ref'))
        reference_hash = digest(reference)
        sources.append(reference)
    command = [args.verilator, '--cc', '--exe', '--build', '--assert', '-Wno-fatal',
               '--top-module', 'ps_raw_store_tb', '--Mdir', str(out/'obj'),
               '-j', str(args.jobs), '--output-split', '12000', '-MAKEFLAGS', 'VK_PCH_I_FAST= VK_PCH_I_SLOW= CFG_CXXFLAGS_PCH=-E', '-CFLAGS', '-std=c++20 -O1 -fsanitize=undefined',
               '-LDFLAGS', '-fsanitize=undefined', *map(str, sources)]
    if args.large:command.append('-GMAX_FRAME_ROWS=256')
    if args.reference:command.append('-DPS_COMPARE_REFERENCE')
    with (out/'compile.log').open('w') as log:
        subprocess.run(command, cwd=root, stdout=log, stderr=subprocess.STDOUT, check=True)
    binary = out/'obj/Vps_raw_store_tb'
    result = subprocess.run([str(binary), *(['large'] if args.large else [])], text=True, capture_output=True, check=True)
    (out/'run.log').write_text(result.stdout+result.stderr)
    assert 'RAW_STORE_PASS' in result.stdout
    assert all(digest(root/p) == h for p, h in hashes.items())
    summary = dict(passed=True, source_sha256=hashes, binary_sha256=digest(binary),
                   reference=args.reference, reference_sha256=reference_hash,
                   compile_command=command, result=result.stdout.strip())
    (out/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    print(result.stdout, end='')


if __name__ == '__main__':
    main()
