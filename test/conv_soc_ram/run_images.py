#!/usr/bin/env python3
"""Verify 32-bit firmware images in AXI32 and AXI64 production RAM."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'build/soc_ram_images')
    parser.add_argument('--verilator', default='verilator')
    parser.add_argument('--tclsh', default='tclsh')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    firmware = out / 'firmware.mem'
    overlay = out / 'overlay.mem'
    expected = out / 'expected.mem'
    firmware.write_text('/* firmware\n header */ @0\n0102_0304 22222222\n'
                        '33333333 88888888 44444444 // five words\n@f\nffffffff\n')
    overlay.write_text('55555555 66666666 /* base word 5 */\n'
                       '@1\naabbccdd\n@3\n0\n@1f\nfedcba98\n')
    expected.write_text('@0\n01020304 aabbccdd 33333333 0 44444444 '
                        '55555555 66666666 cafebabe\n@f\nffffffff\n@1f\nfedcba98\n')
    source = ROOT / 'rtl/soc/soc_axi_ram.sv'
    helper = ROOT / 'fpga/vivado/tflm_ai_dsa_soc/scripts/cpu_memory.tcl'
    sources = [source, helper, HERE/'tb_soc_ram_image.sv', Path(__file__).resolve()]
    before = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    converter = out/'convert.tcl'
    converter.write_text('source [lindex $argv 0]\n'
                         'puts [cpu_memory::write_images {*}[lrange $argv 1 end]]\n')
    runs = []
    for width, synthesis in ((32, False), (64, False), (32, True), (64, True)):
        build = out / (f'axi{width}' + ('_synthesis' if synthesis else ''))
        build.mkdir(exist_ok=True)
        command = [args.verilator, '--binary', '--timing', '--assert', '-Wno-fatal',
                   '--top-module', 'tb_soc_ram_image', f'-GDW={width}', '--Mdir',
                   str(build / 'obj'), '-j', '2', str(source), str(HERE / 'tb_soc_ram_image.sv')]
        if synthesis:
            native = build/'native.mem'
            conversion = subprocess.run([args.tclsh, str(converter), str(helper), str(expected),
                str(build/'cpu32.mem'), str(native), '32', str(width)], capture_output=True, text=True, check=True)
            (build/'conversion.log').write_text(conversion.stdout + conversion.stderr)
            command += ['-DSYNTHESIS', f'-GMEM_WORD_WIDTH={width}', f'-GMEM_PATH="{native}"']
        with (build / 'build.log').open('w') as log:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=120)
        command = [str(build / 'obj/Vtb_soc_ram_image'), f'+SOC_CPU_MEM={firmware}',
                   f'+SOC_DATA_MEM={overlay}', '+SOC_DATA_MEM_BASE_WORD=5',
                   f'+EXPECTED_IMAGE={expected}']
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        (build / 'run.log').write_text(result.stdout + result.stderr)
        passed = result.returncode == 0 and 'SOC_RAM_IMAGE_PASS' in result.stdout
        runs.append(dict(data_bits=width, synthesis_initialization=synthesis, passed=passed, command=command))
        print(f'AXI{width} memory images synthesis={synthesis}: {"PASS" if passed else "FAIL"}', flush=True)
    unchanged = all(hashlib.sha256((ROOT/path).read_bytes()).hexdigest() == value
                    for path, value in before.items())
    report = dict(passed=unchanged and all(row['passed'] for row in runs),
                  sources_unchanged=unchanged, source_sha256=before, runs=runs)
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
