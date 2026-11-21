#!/usr/bin/env python3
"""验证 32/64 位写入分页、并发、反压、字节掩码和响应错误。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
RTL = ROOT / 'rtl/npu/dma/axi_write_page_guard.sv'
DRIVER = Path(__file__).with_name('main.cpp')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--verilator', default='verilator-modern')
    parser.add_argument('--rtl-source', type=Path, default=RTL)
    args = parser.parse_args()
    rtl = args.rtl_source.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env['MAKEFLAGS'] = 'OPT_FAST=-O1 OPT_SLOW=-O0 VK_PCH_I_FAST= VK_PCH_I_SLOW= CFG_CXXFLAGS_PCH=-E'
    hashes = {'rtl': digest(rtl), 'driver': digest(DRIVER)}
    report = dict(source_sha256=hashes, configurations=[], passed=False)
    for width in (32, 64):
        for outstanding in (1, 4):
            folder = out / f'data{width}_outstanding{outstanding}'
            folder.mkdir(exist_ok=True)
            command = [args.verilator, '--cc', '--exe', '--build', '--timing', '--assert',
                       '-DNPU_SIM_ASSERT', '-Wall', '-Wno-fatal', '--top-module', 'axi_write_page_guard',
                       '--Mdir', str(folder / 'obj'), '-j', '1', f'-GDATA_W={width}',
                       f'-GWRITE_OUTSTANDING={outstanding}', '-CFLAGS',
                       f'-std=c++20 -DTEST_DATA_W={width} -DTEST_OUTSTANDING={outstanding}',
                       str(rtl), str(DRIVER)]
            with (folder / 'build.log').open('w') as stream:
                subprocess.run(command, cwd=ROOT, env=env, stdout=stream,
                               stderr=subprocess.STDOUT, check=True)
            warnings = [line for line in (folder / 'build.log').read_text().splitlines()
                        if line.startswith('%Warning')]
            reviewed = {'UNUSEDSIGNAL', 'UNUSEDPARAM', 'SYNCASYNCNET'}
            # 单个在途事务时，原有计数范围断言对一位计数器恒成立。
            assertion_line = next(index for index, line in enumerate(rtl.read_text().splitlines(), 1)
                                  if 'assert(direct_outstanding <= ' in line)
            unexpected = [line for line in warnings
                          if line.split(':', 1)[0].removeprefix('%Warning-') not in reviewed
                          and not (outstanding == 1 and line.startswith('%Warning-CMPCONST:')
                                   and f'{rtl}:{assertion_line}:' in line)]
            if unexpected:
                raise RuntimeError(f'Unreviewed lint diagnostics: {unexpected}')
            binary = folder / 'obj/Vaxi_write_page_guard'
            row = dict(data_width=width, outstanding=outstanding, command=command,
                       warnings=warnings, binary_sha256=digest(binary), runs=[])
            for random in (False, True):
                for errors in (False, True):
                    run_command = [str(binary), *(['--random'] if random else []),
                                   *(['--errors'] if errors else [])]
                    log = folder / f'random{int(random)}_errors{int(errors)}.log'
                    with log.open('w') as stream:
                        subprocess.run(run_command, cwd=ROOT, stdout=stream,
                                       stderr=subprocess.STDOUT, check=True, timeout=120)
                    text = log.read_text()
                    if 'WRITE_PAGE_ADDRESS_PASS' not in text:
                        raise RuntimeError('Write page guard protocol result missing')
                    counters = {key: int(value) for key, value in re.findall(r'(\w+)=(\d+)', text)}
                    if counters['commands'] != 256 or counters['max_outstanding'] != outstanding:
                        raise RuntimeError('Complete protocol coverage not established')
                    row['runs'].append(dict(random=random, errors=errors, passed=True,
                                            counters=counters, log_sha256=digest(log)))
                    print(text.strip(), flush=True)
            report['configurations'].append(row)
            for path in binary.parent.iterdir():
                if path.is_file() and path != binary:
                    path.unlink()
    if hashes != {'rtl': digest(rtl), 'driver': digest(DRIVER)}:
        raise RuntimeError('Source changed during verification')
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
