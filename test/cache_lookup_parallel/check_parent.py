#!/usr/bin/env python3
"""比较完整窗口缓存的全部共有状态与公开输出。"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import argparse
import hashlib
import json
import re
import runpy
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
MODULES = (
    'rtl/npu/dma/cache/conv_windowed_cache.sv',
    'rtl/npu/dma/cache/conv_cache_request_path.sv',
)
PROFILES = (
    dict(SETS=2, WAYS=1, LINE_BYTES=8, BUS_WIDTH=32, READ_WIDTH=32, DEMAND_DEPTH=1),
    dict(SETS=2, WAYS=2, LINE_BYTES=16, BUS_WIDTH=32, READ_WIDTH=32, DEMAND_DEPTH=2),
    dict(SETS=4, WAYS=1, LINE_BYTES=32, BUS_WIDTH=64, READ_WIDTH=64, DEMAND_DEPTH=4),
    dict(SETS=16, WAYS=2, LINE_BYTES=128, BUS_WIDTH=64, READ_WIDTH=64, DEMAND_DEPTH=2),
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='d7cb67be')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    resolver = runpy.run_path(str(ROOT / 'scripts/rtl/source_files.py'))['with_dependencies']

    # 所有参照依赖均从同一 Git 提交读取，当前请求通路参与独立比较。
    reference_tree = out / 'reference_tree'
    initial = []
    for relative in MODULES:
        path = reference_tree / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(subprocess.check_output(['git', 'show', args.reference + ':' + relative], cwd=ROOT))
        initial.append(path)
    reference_sources = []
    for path in resolver(initial, ROOT):
        if path.is_relative_to(reference_tree):
            reference_sources.append(path)
            continue
        relative = path.relative_to(ROOT)
        saved = reference_tree / relative
        saved.parent.mkdir(parents=True, exist_ok=True)
        saved.write_bytes(subprocess.check_output(['git', 'show', args.reference + ':' + str(relative)], cwd=ROOT))
        reference_sources.append(saved)
    sources = {
        'reference': reference_sources,
        'current': resolver([ROOT / MODULES[0]], ROOT),
    }
    hashes = {str(path): digest(path) for paths in sources.values() for path in paths}
    cases = []
    modes = (
        ('generic', ['-USYNTHESIS', '-UXILINX_FPGA']),
        ('fpga', ['-DSYNTHESIS=1', '-DXILINX_FPGA=1']),
    )
    for mode, flags in modes:
        for index, parameters in enumerate(PROFILES):
            options = [f'-G{name}={value}' for name, value in parameters.items()]
            commands = []
            for label, paths in sources.items():
                commands += [
                    'read_slang --top conv_windowed_cache ' + shlex.join(flags + options + list(map(str, paths))),
                    'setattr -mod -unset keep_hierarchy', 'setattr -unset keep_hierarchy',
                    'prep -top conv_windowed_cache -flatten', 'memory_map', 'async2sync',
                    'opt -full', f'rename -top {label}', f'design -stash {label}',
                ]
            commands += [
                'design -copy-from reference -as reference reference',
                'design -copy-from current -as current current',
                'equiv_make reference current proof', 'hierarchy -top proof',
                'equiv_struct -icells -fwd t:* t:$reduce_and %d t:$reduce_or %d t:$reduce_bool %d',
                'select *', 'equiv_induct -seq 2', 'equiv_simple -seq 1',
                'opt_clean', 'equiv_status -assert',
            ]
            script = out / f'{mode}_{index}.ys'
            log = out / f'{mode}_{index}.log'
            script.write_text('\n'.join(commands) + '\n')
            cases.append((mode, flags, parameters, script, log))

    def execute(case):
        mode, flags, parameters, script, log = case
        with log.open('w') as stream:
            subprocess.run([sys.executable, ROOT / 'scripts/fpga/open_fpga_synth.py', '--worker', script],
                           stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=600)
        text = log.read_text()
        counts = re.findall(r'Found (\d+) \$equiv cells', text)
        assert counts and 'Equivalence successfully proven!' in text
        result = dict(mode=mode, macro_options=flags, parameters=parameters, bits=int(counts[-1]),
                      passed=True, log_sha256=digest(log))
        print(json.dumps(result), flush=True)
        return result

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(execute, cases))
    assert all(digest(Path(path)) == expected for path, expected in hashes.items())
    report = dict(passed=True, reference_commit=args.reference, source_sha256=hashes,
                  runner_sha256=digest(Path(__file__)), input_constraints=[],
                  parent_outputs_and_state_every_cycle=True, formal=results)
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
