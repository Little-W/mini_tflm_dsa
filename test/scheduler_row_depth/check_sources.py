#!/usr/bin/env python3
"""实际展开帧调度器各测试入口使用的完整源码列表。"""
import argparse
import ast
import json
from pathlib import Path
import runpy
import shlex
import subprocess
import sys
from prove import ROOT, SOURCE, digest


class SourcesChecked(Exception):
    pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    original_run = subprocess.run
    reports = []
    entries = [('test/scheduler_metadata/run_formal.py', 'metadata', []),
               ('test/scheduler_control/run_formal.py', 'control', []),
               ('test/config_onehot/run_control_equivalence.py', 'onehot', ['--cases','scheduler_bounded']),
               ('test/npu_admission/run_formal.py', 'admission', [])]
    for entry,name,options in entries:
        folder = out / name
        folder.mkdir(exist_ok=True)
        previous_argv, previous_path = sys.argv[:], sys.path[:]
        sys.path.insert(0,str((ROOT/entry).parent))
        module = runpy.run_path(str(ROOT/entry),run_name='scheduler_source_check')
        admission_script = None
        if name == 'admission':
            entry_text = (ROOT/entry).read_text()
            first = entry_text.index("    scheduler = out / 'scheduler_observed.sv'")
            last = entry_text.index('    scheduler.write_text(text)',first) + len('    scheduler.write_text(text)')
            values = {**module,'out':folder,'size':16,'frames':16,'reuse':32}
            first_line,last_line = entry_text[:first].count('\n')+1,entry_text[:last].count('\n')+1
            tree = ast.parse(entry_text)
            main_function = next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='main')
            statements = [node for node in main_function.body if first_line<=node.lineno<=last_line]
            exec(compile(ast.Module(body=statements,type_ignores=[]),entry,'exec'),values)
            commands = []
            for node in ast.walk(tree):
                if isinstance(node,ast.JoinedStr):
                    literals = ''.join(part.value for part in node.values
                                       if isinstance(part,ast.Constant) and isinstance(part.value,str))
                    if literals.startswith('read_slang ') and '--top ps_window_scheduler ' in literals:
                        commands.append(eval(compile(ast.Expression(node),entry,'eval'),values))
            assert len(commands)==2
            admission_script = folder/'source_commands.ys'
            admission_script.write_text('\n'.join(commands)+'\n')

        def capture(command,*positional,**keywords):
            if '--worker' not in command:
                return original_run(command,*positional,**keywords)
            source_script = Path(command[command.index('--worker')+1])
            commands = [row for row in source_script.read_text().splitlines()
                        if row.startswith('read_slang ') and '--top ps_window_scheduler ' in row]
            if not commands:
                return original_run(command,*positional,**keywords)
            assert commands and all('parallel_prefix_add.sv' in row and 'regfile.v' in row for row in commands)
            rows = []
            for command in commands:
                if rows:rows.append('design -reset')
                rows += [command,'prep -top ps_window_scheduler -flatten','hierarchy -check','check -assert']
            script,log = out/(name+'.ys'),out/(name+'.log')
            script.write_text('\n'.join(rows)+'\n')
            with log.open('w') as stream:
                result = original_run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),
                                       '--worker',str(script)],cwd=ROOT,stdout=stream,
                                      stderr=subprocess.STDOUT,timeout=120)
            if result.returncode:raise RuntimeError(log.read_text()[-5000:])
            reports.append({'entry':entry,'models':len(commands),'passed':True,
                            'entry_sha256':digest(ROOT/entry),'script_sha256':digest(script),
                            'log_sha256':digest(log)})
            raise SourcesChecked

        sys.argv = [str(ROOT/entry),'--out',str(folder)]+options
        subprocess.run = capture
        try:
            if admission_script:
                capture([sys.executable,'--worker',str(admission_script)])
            else:
                module['main']()
        except SourcesChecked:
            pass
        else:
            raise RuntimeError(f'No complete scheduler compilation requested by {entry}')
        finally:
            subprocess.run = original_run
            sys.argv,sys.path = previous_argv,previous_path
    report = {'passed':True,'source_sha256':digest(ROOT/SOURCE),'checks':reports,
              'scope':'actual complete scheduler source elaboration; historical equivalence checks are separate tests',
              'script_sha256':digest(Path(__file__))}
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'passed':True,'checks':len(reports),'models':sum(row['models'] for row in reports)}))


if __name__=='__main__':
    main()
