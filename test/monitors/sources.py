# SPDX-License-Identifier: Apache-2.0
"""Select testbench observers for the RTL modules in a simulation source list."""
from pathlib import Path
import re
import runpy


def with_observers(sources, *, source_root=None, observer_root=None):
    tool_root = Path(__file__).resolve().parents[2]
    root = Path(source_root).resolve() if source_root is not None else tool_root
    dependency_reader = runpy.run_path(str(tool_root / 'scripts/rtl/source_files.py'))
    values = dependency_reader['with_dependencies'](sources, root)
    modules = set()
    common = root / 'rtl/common'
    for name in ('regfile.v', 'onehot_check.sv', 'add_equal.sv', 'parallel_prefix_add.sv',
                 'unsigned_compare.sv'):
        dependency = common / name
        if dependency not in values:
            values.append(dependency)
    for source in values:
        path = Path(source)
        if path.suffix in ('.sv', '.v') and path.is_file():
            text = re.sub(r'//[^\n]*|/\*.*?\*/', '', path.read_text(), flags=re.S)
            modules.update(re.findall(r'\bmodule\s+(\w+)', text))
    directory = Path(observer_root).resolve() if observer_root is not None else Path(__file__).resolve().parent
    for name in sorted(modules):
        observer = directory / (name + '_observer.sv')
        if observer.is_file() and observer not in values:
            values.append(observer)
    return values
