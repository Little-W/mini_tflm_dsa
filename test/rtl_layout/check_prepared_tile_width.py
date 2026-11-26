#!/usr/bin/env python3
"""检查描述符接口与 packed 字段在不同尺寸参数下的实际展开位宽。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import runpy
import subprocess


ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--verilator', default='verilator')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    resolver = runpy.run_path(str(ROOT / 'scripts/rtl/source_files.py'))
    sources = resolver['with_dependencies']([
        ROOT / 'rtl/npu/conv/conv_im2col_runtime_registers.sv',
        ROOT / 'rtl/npu/conv/conv_descriptor_commit.sv',
    ], ROOT)
    source_inputs = resolver['input_files'](sources, ROOT)
    hashes = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in source_inputs}
    text = ['module prepared_width_check;']
    checks = []
    profiles = []
    for coordinate in (33, 35, 40):
        for size, slot, lanes in ((4, 3, 2), (16, 5, 8), (32, 6, 16)):
            index = len(profiles)
            count = size.bit_length()
            saved = max(4, lanes)
            shift = saved.bit_length() - 1
            text.append(f'conv_im2col_runtime_registers #(.p_size({size}), '
                        f'.p_slot_width({slot}), .p_coord_width({coordinate}), '
                        f'.p_word_shift({shift}), .p_saved_group_lanes({saved})) '
                        f'u_runtime_{index} ();')
            text.append(f'conv_descriptor_commit #(.p_size({size}), '
                        f'.p_slot_w({slot}), .p_lanes({lanes}), .p_line_bytes(128), '
                        f'.p_coord_w({coordinate})) u_commit_{index} ();')
            expected = 458 + 2*coordinate + 3*count + slot + saved - shift
            for signal in (f'u_runtime_{index}.i_committing_tile',
                           f'u_runtime_{index}.prepared_tile',
                           f'u_commit_{index}.i_prepared_tile_packed',
                           f'u_commit_{index}.i_preparing_tile_packed',
                           f'u_commit_{index}.o_committing_tile_packed',
                           f'u_commit_{index}.committing_tile'):
                checks.append(f'if ($bits({signal}) != {expected}) '
                              f'$fatal(1, "Width mismatch: {signal}");')
            profiles.append({'coordinate_width': coordinate, 'size': size,
                             'slot_width': slot, 'lanes': lanes,
                             'prepared_tile_width': expected})
    text += ['initial begin', *checks,
             '$display("PREPARED_TILE_WIDTH_PASS profiles=9 checks=54");',
             '$finish;', 'end', 'endmodule']
    bench = out / 'prepared_width_check.sv'
    bench.write_text('\n'.join(text) + '\n')
    command = [args.verilator, '--binary', '--top-module', 'prepared_width_check',
               '--Mdir', str(out / 'obj_dir'), '-o', str(out / 'simulation'),
               '-Wno-fatal', '-Wno-PINMISSING', '-I' + str(ROOT / 'include'),
               '-MAKEFLAGS', 'OPT_FAST=-O1 OPT_SLOW=-O0 VK_PCH_I_FAST= VK_PCH_I_SLOW= CFG_CXXFLAGS_PCH=-E',
               '-j', '1', *map(str, sources), str(bench)]
    with (out / 'build.log').open('w') as log:
        subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                       check=True, timeout=180)
    result = subprocess.run([str(out / 'simulation')], capture_output=True,
                            text=True, check=True, timeout=30)
    (out / 'run.log').write_text(result.stdout + result.stderr)
    if 'PREPARED_TILE_WIDTH_PASS' not in result.stdout:
        raise RuntimeError('Parameter checks did not complete')
    if any(hashlib.sha256((ROOT / path).read_bytes()).hexdigest() != value
           for path, value in hashes.items()):
        raise RuntimeError('RTL source changed during parameter checks')
    summary = {'passed': True, 'profiles': profiles, 'width_checks': len(checks),
               'source_sha256': hashes}
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(result.stdout.strip())


if __name__ == '__main__':
    main()
