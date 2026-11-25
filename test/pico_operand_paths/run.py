#!/usr/bin/env python3
"""验证完整 CPU 的关系比较、跳转加法和除法结果符号变换。"""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCES = [Path('rtl/soc') / name for name in (
    'picorv32_npu.v', 'picorv32_pcpi_mul.v', 'picorv32_pcpi_div.v',
    'picorv32_pcpi_fast_mul.v', 'picorv32_regs.v')]
SOURCES += [Path('rtl/common/unsigned_compare.sv'), Path('rtl/common/parallel_prefix_add.sv')]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', default='d8699b87320d74538fd37d0773ff4fb609f23dc1')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--stages', nargs='+', choices=['formal', 'execution', 'mapping'],
                        default=['formal', 'execution', 'mapping'])
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    sources, hashes = {}, {}
    for label in ('reference', 'current'):
        contents = {}
        folder = out / 'inputs' / label
        for path in SOURCES:
            data = (subprocess.check_output(['git', 'show', f'{args.reference}:{path}'], cwd=ROOT)
                    if label == 'reference' else (ROOT / path).read_bytes())
            destination = folder / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
            contents[str(path)] = data
        hashes[label] = {path: digest(data) for path, data in contents.items()}
        sources[label] = out / f'{label}.sv'
        sources[label].write_bytes(b'\n'.join(contents.values()))
    spec = importlib.util.spec_from_file_location('complete_cpu', ROOT / 'test/pico_pc_arithmetic/run.py')
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    report = {'passed': False, 'reference_commit': args.reference, 'source_sha256': hashes,
              'test_sha256': digest(Path(__file__).read_bytes()), 'stages': {}}
    (out / 'inputs.json').write_text(json.dumps(report, indent=2) + '\n')
    if 'formal' in args.stages:
        report['stages']['formal'] = helper.formal(out / 'formal', sources)
    if 'execution' in args.stages:
        bench = ROOT / 'test/pico_pc_arithmetic/tb_execution.sv'
        report['stages']['execution'] = helper.execution(out / 'execution', sources, bench)
        original_run = helper.run

        def synthesis_run(command, log, timeout=900):
            if command[0] == 'iverilog':
                command = command[:1] + ['-DSYNTHESIS=1'] + command[1:]
            return original_run(command, log, timeout)

        helper.run = synthesis_run
        report['stages']['synthesis_execution'] = helper.execution(out / 'synthesis_execution', sources, bench)
        helper.run = original_run
    if 'mapping' in args.stages:
        cases = {}
        for label in sources:
            folder = out / 'inputs' / label
            cases[label] = {
                'top': 'picorv32',
                'options': ['-D', 'SYNTHESIS=1', '-D', 'XILINX_FPGA=1'] +
                           [f'-G{k}={v}' for k, v in helper.PARAMETERS.items()],
                'sources': [str(folder / p) for p in SOURCES[:5]],
                'configuration': '完整生产 CPU，双端口寄存器、迭代乘除法、32 位计数器'}
        config = out / 'cases.json'
        config.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + '\n')
        for label in sources:
            helper.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                        '--source-root', str(out / 'inputs' / label),
                        '--case-config', str(config), '--cases', label,
                        '--out', str(out / 'mapping'),
                        '--abc9-batch-size', '64', '--abc9-isolate-leaves',
                        '--max-register-path-cells', '10'], out / f'mapping_{label}.log', 1800)
        mapped = {}
        for label in sources:
            path = out / 'mapping' / label / 'metrics.json'
            measured = json.loads(path.read_text())
            if not measured['paths']['graph_complete']:
                raise RuntimeError(f'{label} 的组合路径图不完整')
            mapped[label] = {
                'resources': measured['resources'],
                'register_path_requirement': measured['register_path_requirement'],
                'metrics_sha256': digest(path.read_bytes())}
        report['stages']['mapping'] = mapped
    if any(digest((ROOT / p).read_bytes()) != hashes['current'][str(p)] for p in SOURCES):
        raise RuntimeError('验证期间 CPU 源文件发生变化')
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'passed': True, 'out': str(out)}), flush=True)


if __name__ == '__main__':
    main()
