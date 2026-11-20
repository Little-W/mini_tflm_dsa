# SPDX-License-Identifier: Apache-2.0
"""Select testbench observers for the RTL modules in a simulation source list."""
from pathlib import Path
import re


def with_observers(sources):
    values = list(sources)
    modules = set()
    common = Path(__file__).resolve().parents[2] / 'rtl/common'
    for name in ('regfile.v', 'onehot_check.sv', 'add_equal.sv'):
        dependency = common / name
        if dependency not in values:
            values.append(dependency)
    for source in values:
        path = Path(source)
        if path.suffix in ('.sv', '.v') and path.is_file():
            text = re.sub(r'//[^\n]*|/\*.*?\*/', '', path.read_text(), flags=re.S)
            modules.update(re.findall(r'\bmodule\s+(\w+)', text))
    directory = Path(__file__).resolve().parent
    for name in sorted(modules):
        observer = directory / (name + '_observer.sv')
        if observer.is_file() and observer not in values:
            values.append(observer)
    return values
