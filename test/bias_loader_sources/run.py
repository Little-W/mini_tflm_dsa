#!/usr/bin/env python3
"""检查偏置加载器测试入口的源文件依赖并实际展开其完整模型。"""
import argparse
import hashlib
import json
from pathlib import Path
import runpy
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / 'rtl/common/parallel_prefix_add.sv'
WORKER = ROOT / 'scripts/fpga/open_fpga_synth.py'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class SourceCommandsCollected(Exception):
    pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--formal-results', type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reports = []
    original_run = subprocess.run

    def elaborate(name, commands, entry):
        script, log = out / (name + '.ys'), out / (name + '.log')
        rows = []
        for command in commands:
            if rows:
                rows.append('design -reset')
            top = shlex.split(command)[shlex.split(command).index('--top') + 1]
            rows += [command, f'prep -top {top} -flatten', 'hierarchy -check', 'check -assert']
        assert rows and all('parallel_prefix_add.sv' in command for command in commands)
        script.write_text('\n'.join(rows) + '\n')
        with log.open('w') as stream:
            result = original_run([sys.executable, str(WORKER), '--worker', str(script)],
                                  cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, timeout=120)
        if result.returncode:
            raise RuntimeError(log.read_text()[-5000:])
        reports.append({'entry': entry, 'elaborated_models': len(commands),
                        'passed': True, 'script_sha256': digest(script), 'log_sha256': digest(log)})

    def check_entry(entry, name):
        folder = out / name
        folder.mkdir(exist_ok=True)
        previous_argv, previous_path = sys.argv[:], sys.path[:]
        sys.path.insert(0, str((ROOT / entry).parent))
        module = runpy.run_path(str(ROOT / entry), run_name='source_dependency_check')

        def capture(command, *positional, **keywords):
            if '--worker' not in command:
                return original_run(command, *positional, **keywords)
            source_script = Path(command[command.index('--worker') + 1])
            commands = [row for row in source_script.read_text().splitlines()
                        if row.startswith('read_slang ')]
            elaborate(name, commands, entry)
            raise SourceCommandsCollected

        sys.argv = [str(ROOT / entry), '--out', str(folder)]
        subprocess.run = capture
        try:
            module['main']()
        except SourceCommandsCollected:
            pass
        else:
            raise RuntimeError(f'No source compilation requested by {entry}')
        finally:
            subprocess.run = original_run
            sys.argv, sys.path = previous_argv, previous_path

    for entry, name in [
        ('test/bias_read_depth/prove.py', 'read_depth'),
        ('test/bias_read_depth/prove_shared.py', 'shared_control'),
        ('test/bias_loader_range/run_formal.py', 'range_formal'),
        ('test/bias_loader_range/synthesis.py', 'range_synthesis'),
        ('test/bias_group_index/run_formal.py', 'group_index'),
        ('test/bias_residency_timing/run_formal.py', 'residency')]:
        check_entry(entry, name)

    commands = []
    for label in ['reference', 'current']:
        folder = out / 'shared_control'
        sources = [folder / label / 'bias_loader.sv', folder / label / 'bias_loader_buffer.sv',
                   folder / 'source' / label / 'rtl/npu/loaders/bias_loader_ctrl.sv',
                   folder / 'source' / label / 'rtl/common/parallel_prefix_add.sv']
        commands.append('read_slang --top bias_loader -GSIZE=4 -GBUS_WIDTH=32 '
                        '-GCOUNT_WIDTH=1 -GGROUP_BLOCKS_MAX=1 ' +
                        ' '.join(shlex.quote(str(path)) for path in sources))
    elaborate('shared_loader', commands, 'test/bias_read_depth/prove_shared.py')

    cache_entry = 'test/bias_cache_data/run_formal.py'
    cache = runpy.run_path(str(ROOT / cache_entry), run_name='cache_dependency_check')
    source = (ROOT / 'rtl/npu/loaders/bias_loader_buffer.sv').read_text()
    observer = out / 'cache_control.sv'
    observer.write_text(cache['controller_observer'](source))
    sources = [observer, ROOT / 'rtl/common/regfile.v', HELPER]
    elaborate('cache_control', ['read_slang --top bias_loader_buffer -GSIZE=4 '
        '-GBUS_WIDTH=32 -GCOUNT_WIDTH=1 -GGROUP_BLOCKS_MAX=1 ' +
        ' '.join(shlex.quote(str(path)) for path in sources)], cache_entry)

    make_dir = ROOT / 'test/bias_loader_reuse'
    dry = subprocess.check_output(['make', '-n', 'run', 'JOBS=1', f'BUILD={out / "make_obj"}'],
                                  cwd=make_dir, text=True)
    command = shlex.split(dry.splitlines()[0])
    assert '--binary' in command and any('parallel_prefix_add.sv' in part for part in command)
    command[command.index('--binary')] = '--lint-only'
    log = out / 'reuse_make.log'
    with log.open('w') as stream:
        result = original_run(command, cwd=make_dir, stdout=stream, stderr=subprocess.STDOUT, timeout=120)
    if result.returncode:
        raise RuntimeError(log.read_text()[-5000:])
    reports.append({'entry': 'test/bias_loader_reuse/Makefile', 'passed': True,
                    'method': 'actual Makefile source list with Verilator --lint-only',
                    'command': command, 'log_sha256': digest(log)})
    report = {'passed': True,
              'scope': 'source elaboration and module dependency checks; historical equivalence proofs are separate tests',
              'helper_sha256': digest(HELPER), 'checks': reports,
              'entry_sha256': {row['entry']: digest(ROOT / row['entry']) for row in reports},
              'script_sha256': digest(Path(__file__))}
    if args.formal_results:
        report['formal_checks'] = {}
        for name,count in [('read_proof',6),('shared_proof',5)]:
            path = args.formal_results / name / 'summary.json'
            result = json.loads(path.read_text())
            assert result['passed'] and len(result['profiles']) == count
            for row in result['inputs']['sources']:
                assert row['current_sha256'] == digest(ROOT / row['source'])
            report['formal_checks'][name] = result
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'passed': True, 'checks': len(reports)}))


if __name__ == '__main__':
    main()
