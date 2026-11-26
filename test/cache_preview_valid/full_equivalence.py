#!/usr/bin/env python3
"""证明缓存可匹配状态与所有输出的逐周期等价性，包含生产预读参数。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
NAME_MARKER = '# restore-request-path-scope-names'


def worker(script):
    from pyosys import libyosys as yosys
    design = yosys.Design()
    renamed = []
    for command in script.read_text().splitlines():
        if command == NAME_MARKER:
            module = design.top_module()
            names = {name.str() for name in module.wires_.keys()}
            prefix = '\\g_window.u_window.u_request_path.'
            for name, wire in list(module.wires_.items()):
                old = name.str()
                if not old.startswith(prefix):
                    continue
                new = '\\g_window.u_window.' + old.removeprefix(prefix)
                if new in names:
                    continue
                # 只恢复移动前的信号名称；引脚连接、位宽、状态与证明范围保持不变。
                module.rename(wire, new)
                names.add(new)
                renamed.append({'from': old, 'to': new, 'width': wire.width})
        elif command.strip() and not command.lstrip().startswith('#'):
            yosys.run_pass(command, design)
    script.with_suffix('.names.json').write_text(json.dumps(renamed, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference-root', type=Path)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--worker', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--profiles', nargs='+', default=[
        '2:1:16:1:32:32:0:1', '16:2:128:1:64:128:1:1',
        '16:2:128:2:64:128:1:0', '4:1:32:4:64:32:0:0'])
    args = parser.parse_args()
    if args.worker:
        worker(args.worker)
        return
    if args.reference_root is None or args.out is None:
        parser.error('--reference-root and --out are required')
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    resolver = runpy.run_path(str(ROOT / 'scripts/rtl/source_files.py'))
    roots = {'reference': args.reference_root.resolve(), 'current': ROOT}
    sources = {label: resolver['with_dependencies'](
        [root / 'rtl/npu/dma/cache/conv_read_cache.sv'], root)
        for label, root in roots.items()}
    paths = [path for label, files in sources.items()
             for path in resolver['input_files'](files, roots[label])]
    paths.append(Path(__file__).resolve())
    hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    names = ['SETS', 'WAYS', 'LINE_BYTES', 'DEMAND_DEPTH', 'BUS_WIDTH', 'READ_WIDTH',
             'p_defer_retire_shift', 'p_preview_request']
    results = []
    for profile in args.profiles:
        params = dict(zip(names, map(int, profile.split(':')), strict=True))
        commands = []
        for label in roots:
            options = ' '.join(f'-G{key}={value}' for key, value in params.items())
            commands += [
                f'read_slang -D SYNTHESIS=1 -D XILINX_FPGA=1 '
                f'-I {shlex.quote(str(roots[label] / "include"))} '
                f'--top conv_read_cache {options} ' + shlex.join(map(str, sources[label])),
                'prep -top conv_read_cache -flatten', 'memory_map', 'async2sync', 'opt_clean',
            ]
            if label == 'current':
                commands.append(NAME_MARKER)
            commands += [f'rename conv_read_cache {label}', f'design -stash {label}']
        commands += [
            'design -copy-from reference -as reference reference',
            'design -copy-from current -as current current',
            'equiv_make reference current equivalent', 'hierarchy -top equivalent',
            'equiv_simple -seq 1', 'opt_clean', 'equiv_induct -seq 4', 'equiv_status -assert',
        ]
        stem = profile.replace(':', '_')
        script, log = out / (stem + '.ys'), out / (stem + '.log')
        script.write_text('\n'.join(commands) + '\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable, str(Path(__file__).resolve()), '--worker', str(script)],
                           cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=600)
        match = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', log.read_text())
        assert match and int(match[2]) == 0, log
        name_map = json.loads(script.with_suffix('.names.json').read_text())
        row = {'parameters': params, 'passed': True, 'equivalent_bits': int(match[1]),
               'unproven_bits': int(match[2]), 'restored_scope_names': len(name_map),
               'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest()}
        results.append(row)
        print(json.dumps(row), flush=True)
    assert hashes == {path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in hashes}
    result = {
        'passed': True, 'inputs_constrained': False,
        'scope': '所有可匹配状态与输出及新增逻辑的实际消费者；未排除读端口或内部信号',
        'name_mapping': '仅恢复请求读取子模块中移动信号的原层次名称，保持所有连接和状态',
        'reference_commit': subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'], cwd=args.reference_root, text=True).strip(),
        'source_sha256': hashes, 'profiles': results,
    }
    (out / 'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
