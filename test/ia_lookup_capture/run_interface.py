#!/usr/bin/env python3
"""以预取数值任务逐周期比较 IA 加载器的全部公开输出。"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'test'))
from rtl_reference import shared_ia_parameters
SOURCE = Path('rtl/npu/loaders/ia_loader.sv')


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    source, reference = args.source_root.resolve(), args.reference_root.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    spec = importlib.util.spec_from_file_location('ia_public_ports', ROOT / 'test/ia_timing/run_interface.py')
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    current = (source / SOURCE).read_text()
    ports = helper.port_declarations(current)
    parameters = re.findall(r'\bparameter\s+(?:int\s+unsigned|bit)\s+(\w+)\s*=',
                            current[:current.index(') (')])
    reference_header = (reference / SOURCE).read_text()
    parameters = shared_ia_parameters({name: name for name in parameters}, reference_header)
    outputs = [name for direction, _, name, _ in ports if direction == 'output']
    extra = ['\n    // 相同输入同时驱动两个完整模块，每个周期检查所有公开输出。']
    extra += [f'    {kind} reference_{name} {array};'
              for direction, kind, name, array in ports if direction == 'output']
    extra += ['    ia_loader_reference #(',
              ',\n'.join(f'        .{name}({value})' for name, value in parameters.items()),
              '    ) u_reference (',
              ',\n'.join(f'        .{name}({"reference_" if direction == "output" else ""}{name})'
                          for direction, _, name, _ in ports),
              '    );', '    always_ff @(posedge clk) begin', '        if (rst_n) begin']
    extra += [f'            assert ({name} === reference_{name}) else $fatal(1, "IA output differs: {name}");'
              for name in outputs]
    extra += ['        end', '    end', '']
    checked = out / 'source'
    shutil.copytree(source / 'rtl', checked / 'rtl', dirs_exist_ok=True)
    if (source / 'include').is_dir():
        shutil.copytree(source / 'include', checked / 'include', dirs_exist_ok=True)
    (checked / SOURCE).write_text(current.replace('\nendmodule', '\n'.join(extra) + '\nendmodule', 1))
    reference_rtl = out / 'ia_loader_reference.sv'
    reference_sources = [reference / 'rtl/npu/loaders' / (name + '.sv') for name in
                         ('ia_loader', 'ia_loader_ctrl', 'ia_loader_cache_mgr',
                          'ia_ordered_coordinate_equal', 'ia_ordered_coordinate_same')
                         if (reference / 'rtl/npu/loaders' / (name + '.sv')).is_file()]
    reference_text = '\n'.join(path.read_text() for path in reference_sources)
    for name in re.findall(r'^\s*module\s+(\w+)', reference_text, flags=re.M):
        replacement = 'ia_loader_reference' if name == 'ia_loader' else 'reference_' + name
        reference_text = re.sub(r'\b' + name + r'\b', replacement, reference_text)
    reference_rtl.write_text(reference_text)
    verilator = shutil.which('verilator')
    if verilator is None:
        raise RuntimeError('无法找到 Verilator')
    wrapper = out / 'verilator_compare'
    wrapper.write_text('#!' + sys.executable + '\nimport os, sys\n' +
                       'arguments = sys.argv[1:]\n' +
                       "if '--getenv' not in arguments and '--version' not in arguments:\n" +
                       '    arguments += [' + repr(str(reference_rtl)) + ']\n' +
                       'os.execv(' + repr(verilator) + ', [' + repr(verilator) +
                       '] + arguments)\n')
    wrapper.chmod(0o755)
    command = [sys.executable, str(ROOT / 'test/ia_request_stage/run_prefetch.py'),
               '--source-root', str(checked), '--out', str(out / 'numeric'),
               '--verilator', str(wrapper), '--ordered-job', '--fpga']
    with (out / 'comparison.log').open('w') as stream:
        subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
    numeric = json.loads((out / 'numeric/summary.json').read_text())
    if not numeric['passed']:
        raise RuntimeError('IA 数值比较未完成')
    report = {'passed': True, 'compared_outputs': outputs,
              'source_sha256': digest(source / SOURCE), 'reference_sha256': digest(reference / SOURCE),
              'reference_dependencies_sha256': {str(path.relative_to(reference)): digest(path)
                                                for path in reference_sources},
              'checked_rtl_sha256': digest(checked / SOURCE),
              'numeric': numeric, 'command': command}
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'passed': True, 'compared_outputs': len(outputs), 'runs': numeric['runs']}, indent=2))


if __name__ == '__main__':
    main()
