#!/usr/bin/env python3
"""使用固定生产 RTL 检查 IA 请求寄存、命令描述符和完整 NPU 数值。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tool-root', type=Path, default=ROOT)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--verilator', default='verilator')
    parser.add_argument('--jobs', type=int, default=1)
    parser.add_argument('--collect-existing', action='store_true')
    args = parser.parse_args()
    tool_root, source_root, out = (path.resolve() for path in
                                   (args.tool_root, args.source_root, args.out))
    out.mkdir(parents=True, exist_ok=True)
    top = source_root / 'rtl/npu/top/npu_top.sv'
    if not re.search(r'\.p_register_dma_request\s*\(\s*1\s*\x27b1\s*\)', top.read_text()):
        raise RuntimeError('Production IA request register must be enabled in npu_top')
    observer = HERE / 'request_observer.sv'
    observer_hash = digest(observer)
    if not args.collect_existing:
        executable = shutil.which(args.verilator)
        if executable is None:
            raise RuntimeError('Cannot find Verilator: ' + args.verilator)
        wrapper = out / 'verilator_request_stage'
        wrapper.write_text('#!' + sys.executable + '\nimport os,sys\ncommand=' +
                           repr([executable, str(observer)]) + '+sys.argv[1:]\n'
                           'os.execv(command[0],command)\n')
        wrapper.chmod(0o755)
        command = [sys.executable, str(tool_root / 'test/fpga_integration/run.py'),
                   '--source-root', str(source_root), '--out', str(out),
                   '--verilator', str(wrapper), '--jobs', str(args.jobs)]
        with (out / 'request_stage_run.log').open('w') as stream:
            result = subprocess.run(command, cwd=tool_root, stdout=stream,
                                    stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError('NPU regression failed: ' + str(out / 'request_stage_run.log'))
    report = json.loads((out / 'summary.json').read_text())
    npu = json.loads((out / 'npu/summary.json').read_text())
    build = json.loads((out / 'npu/s16/build.json').read_text())
    if not report['passed'] or not npu['passed'] or not build['sources_unchanged_during_build']:
        raise RuntimeError('Incomplete production NPU result')
    for name, expected in build['source_sha256'].items():
        path = (source_root if name.startswith('rtl/') else tool_root) / name
        if digest(path) != expected:
            raise RuntimeError('Recorded source differs: ' + str(path))
    binary = out / 'npu/s16/obj/Vtb_conv_npu'
    if digest(binary) != build['binary_sha256']:
        raise RuntimeError('Recorded NPU executable differs')
    observations = []
    for case in npu['cases']:
        log = out / 'npu/s16' / (case['name'] + '.log')
        rows = re.findall(r'^IA_REQUEST_STAGE_PASS\s+(.+)$', log.read_text(), re.MULTILINE)
        if len(rows) != 1:
            raise RuntimeError('Missing request-stage protocol result: ' + str(log))
        values = {name: int(value) for name, value in re.findall(r'(\w+)=(\d+)', rows[0])}
        observations.append(dict(suite=case['name'], log_sha256=digest(log), **values))
    if digest(observer) != observer_hash:
        raise RuntimeError('Observer changed during NPU verification')
    result = dict(passed=True, tasks=report['tasks'], int32_checks=report['int32_checks'],
                  descriptor_checks=sum(item['commands'] for item in observations),
                  observer_sha256=observer_hash, observations=observations,
                  source_sha256=build['source_sha256'], binary_sha256=build['binary_sha256'],
                  summary_sha256=digest(out / 'npu/summary.json'))
    (out / 'request_stage_summary.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({key: result[key] for key in
                      ('passed', 'tasks', 'int32_checks', 'descriptor_checks')}))


if __name__ == '__main__':
    main()
