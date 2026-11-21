#!/usr/bin/env python3
"""验证八通道 IA 在全部列起点、紧凑格式和宽格式下的有效写命令。"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SOURCES = ('rtl/npu/loaders/ia_loader_cache_mgr.sv', 'rtl/npu/compute/select_add.sv',
           'rtl/common/regfile.v', 'rtl/common/pseudo_dual_port_ram.v',
           'test/ia_shared/receive_write_tb.sv')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--fpga', action='store_true')
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources, hashes = [], {}
    for relative in SOURCES:
        source = (ROOT if relative.startswith('test/') else root) / relative
        target = out / 'sources' / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        sources.append(target)
        hashes[relative] = hashlib.sha256(source.read_bytes()).hexdigest()
    command = [shutil.which('verilator') or 'verilator', '--binary', '--timing', '--assert',
               '-DNPU_SIM_ASSERT', '-Wno-fatal', '--top-module', 'receive_write_tb',
               '--Mdir', str(out / 'obj'), '-j', '2', '--output-groups', '0',
               '-CFLAGS', '-std=c++20 -O1', '-MAKEFLAGS',
               'OPT_FAST=-O1 OPT_SLOW=-O0 VK_PCH_I_FAST= VK_PCH_I_SLOW= CFG_CXXFLAGS_PCH=-E',
               *(['-DXILINX_FPGA=1'] if args.fpga else []), *map(str, sources)]
    with (out / 'build.log').open('w') as stream:
        subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, check=True)
    result = subprocess.run([str(out / 'obj/Vreceive_write_tb')], capture_output=True, text=True)
    (out / 'run.log').write_text(result.stdout + result.stderr)
    passed = result.returncode == 0 and 'PASS: 65536 exhaustive byte/offset pairs and 20000 random write cycles' in result.stdout
    if not passed:
        raise RuntimeError('IA receive write comparison did not complete: ' + str(out / 'run.log'))
    report = {'passed': True, 'source_sha256': hashes, 'xilinx_fpga': args.fpga,
              'input_lanes': 8, 'column_positions': 16, 'exhaustive_byte_offset_pairs': 65536,
              'random_write_cycles': 20000, 'idle_command_cycles_checked': True, 'inactive_addresses_and_masks_held': True}
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    for path in (out / 'obj').iterdir():
        if path.suffix in ('.o', '.gch'):
            path.unlink()
    print('IA_RECEIVE_WRITE_PASS', out / 'summary.json', flush=True)


if __name__ == '__main__':
    main()
