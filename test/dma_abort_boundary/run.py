#!/usr/bin/env python3
"""执行并发读错误、写握手、中止排空和连续恢复的真实 DMA 测试。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--verilator', default='verilator')
    parser.add_argument('--jobs', type=int, default=2)
    args = parser.parse_args()
    source = args.source_root.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    packages = [source / 'rtl/npu/conv/conv_im2col_pkg.sv', source / 'rtl/npu/conv/vector_engine_pkg.sv']
    paths = packages + [path for path in sorted((source / 'rtl/npu/conv').rglob('*.sv')) if path not in packages]
    paths += sorted((source / 'rtl/npu/dma').rglob('*.sv'))
    paths += sorted((source / 'rtl/common').glob('*.sv'))
    paths += [source / 'rtl/common/regfile.v', source / 'rtl/common/pseudo_dual_port_ram.v',
              HERE / 'top.sv', HERE / 'main.cpp']
    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()
    hashes = {str(path): digest(path) for path in paths}
    commands = [
        [args.verilator, '--cc', '--exe', '--timing', '--assert', '-DNPU_SIM_ASSERT',
         '-Wno-fatal', '-Wno-PINMISSING', '--top-module', 'dma_abort_top',
         '--Mdir', str(out / 'obj'), '-CFLAGS', '-std=c++20', *map(str, paths)],
        ['make', '-C', str(out / 'obj'), '-f', 'Vdma_abort_top.mk', '-j', str(args.jobs),
         'OPT_FAST=-O1', 'OPT_SLOW=-O0', 'VK_PCH_I_FAST=', 'VK_PCH_I_SLOW=', 'CFG_CXXFLAGS_PCH=-E'],
        [str(out / 'obj/Vdma_abort_top')]]
    for command, filename in zip(commands, ('generate.log', 'compile.log', 'run.log')):
        with (out / filename).open('w') as stream:
            result = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError((out / filename).read_text()[-8000:])
    if hashes != {str(path): digest(path) for path in paths}:
        raise RuntimeError('RTL changed while verifying DMA transactions')
    log = (out / 'run.log').read_text()
    if 'DMA_ABORT_BOUNDARY_PASS cases=16' not in log:
        raise RuntimeError(log)
    (out / 'summary.json').write_text(json.dumps({
        'passed': True, 'source_sha256': hashes, 'cases': 16,
        'binary_sha256': digest(out / 'obj/Vdma_abort_top'),
        'results': log.splitlines(), 'commands': commands
    }, ensure_ascii=False, indent=2) + '\n')
    print(log, end='')


if __name__ == '__main__':
    main()
