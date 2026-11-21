#!/usr/bin/env python3
"""检查完整模宽计数边界在二值、未知值和高阻值输入下的结果。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[2]
WIDTHS = (1, 2, 5, 8, 16, 17, 29, 32, 33, 47, 48, 65)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources = [ROOT / name for name in (
        'rtl/npu/loaders/kernel_loader_ctrl.sv',
        'rtl/common/add_equal.sv', 'rtl/common/unsigned_compare.sv',
        'test/kernel_control_depth/tb_four_state.sv')]
    hashes = {str(path.relative_to(ROOT)): digest(path) for path in sources}
    module = re.search(r'^module kernel_count_next_reaches\b.*?^endmodule',
                       sources[0].read_text(), re.M | re.S)
    if module is None:
        raise RuntimeError('找不到生产计数边界模块')
    candidate = out / 'kernel_count_next_reaches.sv'
    candidate.write_text(module.group(0) + '\n')
    copies = []
    for source in sources[1:]:
        target = out / source.name
        target.write_bytes(source.read_bytes())
        copies.append(target)
    runs = []
    for mode in ('ASIC_SYNTHESIS', 'XILINX_FPGA'):
        for width in WIDTHS:
            stem = f'{mode.lower()}_{width}'
            executable = out / (stem + '.vvp')
            command = ['iverilog', '-g2012', '-D' + mode, '-s', 'tb_count_boundary',
                       f'-Ptb_count_boundary.p_width={width}', '-o', str(executable),
                       str(candidate), *map(str, copies)]
            for args, suffix in ((command, '_build.log'),
                                 (['vvp', str(executable)], '_run.log')):
                with (out / (stem + suffix)).open('w') as stream:
                    subprocess.run(args, stdout=stream, stderr=subprocess.STDOUT,
                                   check=True, timeout=120)
            log = out / (stem + '_run.log')
            match = re.search(r'COUNT_BOUNDARY_PASS width=(\d+) checks=(\d+)', log.read_text())
            if match is None or int(match[1]) != width:
                raise RuntimeError(f'计数边界检查未完成：{log}')
            runs.append({'mode': mode, 'width': width, 'checks': int(match[2]),
                         'passed': True, 'log_sha256': digest(log)})
    if hashes != {str(path.relative_to(ROOT)): digest(path) for path in sources}:
        raise RuntimeError('检查期间源文件发生变化')
    report = {'passed': True, 'strict_four_state': True, 'source_sha256': hashes,
              'runs': runs, 'checks': sum(row['checks'] for row in runs)}
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'passed': True, 'profiles': len(runs), 'checks': report['checks']}))


if __name__ == '__main__':
    main()
