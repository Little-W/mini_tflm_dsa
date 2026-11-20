#!/usr/bin/env python3
"""通过 FPGA 功能模型检查 IA 全部输出及生产共享 RAM 的数值行为。"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

from primitives import prepare_models

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='437a8d81')
    parser.add_argument('--verilator', default='verilator-modern')
    parser.add_argument('--cases', nargs='+', choices=('interface', 'shared'),
                        default=('interface', 'shared'))
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    verilator = shutil.which(args.verilator)
    if verilator is None:
        raise RuntimeError('Cannot locate Verilator: ' + args.verilator)
    source_names = ['rtl/npu/loaders/ia_loader_cache_mgr.sv', 'rtl/npu/compute/select_add.sv',
        'rtl/npu/loaders/ia_loader.sv', 'rtl/npu/loaders/ia_loader_ctrl.sv',
        'rtl/npu/buffers/ia_ps_shared_ram.sv']
    hashes = {name: digest(ROOT / name) for name in source_names}
    summary = dict(passed=False, reference_commit=subprocess.check_output(
        ['git', 'rev-parse', args.reference], cwd=ROOT, text=True).strip(),
        source_sha256=hashes, fpga_primitives_enabled=True, runs=[])
    for name in args.cases:
        folder = out / name
        folder.mkdir(exist_ok=True)
        models = ('DSP48E1',) if name == 'interface' else ('LUT6', 'LUT6_2', 'DSP48E1')
        model, model_info = prepare_models(folder, models)
        extra = [str(ROOT / 'rtl/npu/compute/select_add.sv'), str(model)]
        # 原语库包含未使用模式的显式截断及字符串宽度转换，应用 RTL 保留位宽检查。
        lint_config = folder / 'primitive_widths.vlt'
        lint_config.write_text('`verilator_config\n' +
            'lint_off -rule WIDTHEXPAND -file ' + json.dumps(str(model)) + '\n' +
            'lint_off -rule WIDTHTRUNC -file ' + json.dumps(str(model)) + '\n')
        extra.insert(0, str(lint_config))
        if name == 'shared':
            extra.append('-DXILINX_FPGA=1')
        wrapper = folder / 'verilator_models'
        wrapper.write_text('#!' + sys.executable + '\nimport os,sys\n' +
            'args=sys.argv[1:]\n' +
            "if '--getenv' not in args and '--version' not in args:\n" +
            '    args += ' + repr(extra) + '\n' +
            'os.execv(' + repr(verilator) + ',[' + repr(verilator) + ']+args)\n')
        wrapper.chmod(0o755)
        command = [sys.executable]
        if name == 'interface':
            command += [str(ROOT / 'test/ia_write_admission/run_interface.py'),
                        '--reference-rev', args.reference]
        else:
            command += [str(ROOT / 'test/ia_shared/run.py'), '--bank-bytes', '8192',
                '--bank-count', '7', '--compact-offset-width', '9', '--jobs', '1']
        command += ['--out', str(folder / 'run'), '--verilator', str(wrapper)]
        log = folder / 'run.log'
        with log.open('w') as stream:
            result = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                                    timeout=540)
        report_path = folder / 'run/summary.json'
        data = json.loads(report_path.read_text()) if report_path.exists() else {}
        row = dict(name=name, passed=result.returncode == 0 and data.get('passed', False),
            command=command, primitive_models=model_info, result=data,
            log_sha256=digest(log), wrapper_sha256=digest(wrapper),
            primitive_lint_file_sha256=digest(lint_config),
            primitive_lint_scope={'file': str(model), 'rules': ['WIDTHEXPAND', 'WIDTHTRUNC']})
        summary['runs'].append(row)
        summary['passed'] = all(item['passed'] for item in summary['runs'])
        (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
        print(json.dumps(dict(name=name, passed=row['passed'])), flush=True)
        if not row['passed']:
            raise RuntimeError('IA numerical check did not complete: ' + str(log))
    if hashes != {name: digest(ROOT / name) for name in source_names}:
        raise RuntimeError('Measured sources changed during numerical verification')


if __name__ == '__main__':
    main()
