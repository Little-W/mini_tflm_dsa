#!/usr/bin/env python3
"""严格比较命令准备资格与完整末拍比较的四态结果。"""
from pathlib import Path
import argparse
import json
import re
import subprocess
from support import ROOT, HERE, RTL, HELPER, PROFILES, digest, arithmetic_unit, reference_root


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference-root', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = args.source_root.resolve()
    reference = args.reference_root.resolve() if args.reference_root else reference_root(out / 'reference', current)
    roots = {'reference': reference, 'current': current}
    sources, hashes = [], {}
    for label, root in roots.items():
        source, helper = root / RTL, root / HELPER
        helper_name = 'parallel_prefix_add_' + label
        unit = re.sub(r'\bparallel_prefix_add\b', helper_name, arithmetic_unit(source, label))
        unit += re.sub(r'\bparallel_prefix_add\b', helper_name, helper.read_text())
        target = out / (label + '.sv')
        target.write_text(unit)
        sources.append(target)
        hashes[label] = {str(RTL): digest(source), str(HELPER): digest(helper)}
    bench = HERE / 'tb_four_state.sv'
    binary, compile_log, run_log = out / 'simulation', out / 'compile.log', out / 'run.log'
    with compile_log.open('w') as stream:
        subprocess.run(['iverilog', '-g2012', '-s', 'tb', '-o', str(binary),
                        *map(str, sources), str(bench)], stdout=stream,
                       stderr=subprocess.STDOUT, check=True, timeout=120)
    with run_log.open('w') as stream:
        subprocess.run(['vvp', str(binary)], stdout=stream, stderr=subprocess.STDOUT,
                       check=True, timeout=240)
    match = re.search(r'REQUANT_COMMAND_ARITHMETIC_PASS samples=(\d+) checks=(\d+) unknown_inputs=(\d+) unknown_results=(\d+)',
                      run_log.read_text())
    if match is None:
        raise RuntimeError('四态比较没有完成：' + str(run_log))
    for label, root in roots.items():
        if hashes[label] != {str(RTL): digest(root / RTL), str(HELPER): digest(root / HELPER)}:
            raise RuntimeError('验证期间源码发生变化')
    results = dict(zip(('samples', 'comparisons', 'unknown_inputs', 'unknown_results'), map(int, match.groups())))
    if results['comparisons'] != results['samples'] * len(PROFILES):
        raise RuntimeError('测试配置数与比较次数不同')
    report = {'passed': True, 'strict_four_state': True, 'source_sha256': hashes,
              'profiles': [{'vlen': v, 'reg_width': w} for v, w in PROFILES], **results,
              'bench_sha256': digest(bench), 'log_sha256': digest(run_log)}
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(results))


if __name__ == '__main__':
    main()
