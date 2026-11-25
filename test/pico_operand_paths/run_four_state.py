#!/usr/bin/env python3
"""检查 CPU 关系比较、补码变换和顺序地址的实际四态 RTL。"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    selected = {
        'rtl/soc/picorv32_npu.v': ['pico_operand_comparison', 'pico_sequential_address'],
        'rtl/soc/picorv32_pcpi_div.v': ['pico_result_negation']}
    sources, modules = {}, []
    for filename, names in selected.items():
        data = (ROOT / filename).read_bytes()
        sources[filename] = data
        for name in names:
            match = re.search(r'\bmodule\s+' + name + r'\b.*?endmodule', data.decode(), re.S)
            if match is None:
                raise RuntimeError(f'缺少算术模块：{name}')
            modules.append(match[0])
    helper = out / 'arithmetic_modules.sv'
    helper.write_text('\n'.join(modules) + '\n')
    bench = Path(__file__).with_name('four_state.sv')
    binary = out / 'simulation.vvp'
    with (out / 'build.log').open('w') as stream:
        subprocess.run(['iverilog', '-g2012', '-s', 'tb', '-o', str(binary),
                        str(helper), str(bench)], stdout=stream,
                       stderr=subprocess.STDOUT, check=True)
    with (out / 'run.log').open('w') as stream:
        subprocess.run(['vvp', str(binary)], stdout=stream,
                       stderr=subprocess.STDOUT, check=True, timeout=180)
    if 'PASS checks=131200' not in (out / 'run.log').read_text():
        raise RuntimeError('四态检查数量不完整')
    if any((ROOT / name).read_bytes() != data for name, data in sources.items()):
        raise RuntimeError('验证期间算术源文件发生变化')
    result = {
        'passed': True, 'samples': 131200, 'output_comparisons': 524800,
        'source_sha256': {name: digest(data) for name, data in sources.items()},
        'bench_sha256': digest(bench.read_bytes()),
        'test_sha256': digest(Path(__file__).read_bytes())}
    (out / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
