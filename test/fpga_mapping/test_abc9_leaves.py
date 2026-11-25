#!/usr/bin/env python3
"""检查组合叶模块筛选、结构复用、逐模块等价和完整设计保留。"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'build/abc9_leaf_tests'
MAPPER = ROOT / 'scripts/fpga/map_abc9_batches.py'


def load_mapper():
    sys.path.insert(0, str(MAPPER.parent))
    spec = importlib.util.spec_from_file_location('abc9_leaf_mapper_tested', MAPPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def attributes(obj):
    return {str(key): str(value) for key, value in obj.attributes.items()}


def ports(module):
    return sorted((str(wire.name), wire.width, wire.port_input, wire.port_output,
                   wire.port_id, wire.start_offset, wire.upto, wire.is_signed,
                   tuple(sorted(attributes(wire).items())))
                  for wire in module.wires_.values() if wire.port_input or wire.port_output)


def signal(signal_value):
    return tuple(('wire', str(bit.wire.name), bit.offset) if bit.wire is not None
                 else ('constant', str(bit.data)) for bit in signal_value.bits())


def module_contents(module):
    """独立记录完整模块对象，检查未选择的父模块保持原样。"""
    return {
        'name': str(module.name), 'attributes': attributes(module), 'ports': ports(module),
        'wires': sorted((str(wire.name), wire.width, wire.start_offset, wire.upto,
                         wire.is_signed, tuple(sorted(attributes(wire).items())))
                        for wire in module.wires_.values()),
        'cells': sorted((str(cell.name), str(cell.type), tuple(sorted(attributes(cell).items())),
                         tuple(sorted((str(key), str(value)) for key, value in cell.parameters.items())),
                         tuple(sorted((str(port), signal(value))
                                      for port, value in cell.connections_.items())))
                        for cell in module.cells_.values()),
        'connections': sorted((signal(lhs), signal(rhs)) for lhs, rhs in module.connections()),
    }


def design_from_text(folder, source):
    from pyosys import libyosys as yosys
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / 'source.sv'
    path.write_text(source)
    design = yosys.Design()
    yosys.run_pass('read_verilog -sv ' + str(path), design)
    yosys.run_pass('proc; simplemap', design)
    return design


def leaf(name, internal, *, output_operand='b', module_tag=1, port_tag=11, offset=2):
    return f'''
(* keep_hierarchy = 1, mapping_test_tag = {module_tag} *)
module {name} (
    (* mapping_port_tag = {port_tag} *) input wire signed [{offset+2}:{offset}] a,
    input wire [0:2] b,
    output wire [6:4] y
);
    wire [2:0] {internal};
    assign {internal} = a ^ b;
    assign y = {internal} & {output_operand};
endmodule
'''


def buffer_module(name, width, *, reorder=False, direct=False):
    header = (f'module \\{name}\n'
              f'  wire width {width} input 1 \\a\n'
              f'  wire width {width} output 2 \\y\n')
    connection = ('{ ' + ' '.join(f'\\a [{index}]' for index in range(width)) + ' }'
                  if reorder else '\\a')
    if direct:
        return header + f'  connect \\y {connection}\nend\n'
    return (header + '  cell $buf \\u_buffer\n'
            f'    parameter \\WIDTH {width}\n'
            f'    connect \\A {connection}\n'
            '    connect \\Y \\y\n  end\nend\n')


def add_buffer_modules(design, folder):
    from pyosys import libyosys as yosys
    source = folder / 'buffers.il'
    source.write_text(buffer_module('buffer_1', 1) + buffer_module('buffer_3', 3) +
                      buffer_module('buffer_reordered', 3, reorder=True) +
                      buffer_module('direct_wires', 3, direct=True))
    yosys.run_pass('read_rtlil ' + str(source), design)


def add_constant_modules(design, folder):
    from pyosys import libyosys as yosys
    sections = []
    for value in (0, 1):
        for style in ('buffer', 'direct'):
            header = (f'module \\constant_{value}_{style}\n'
                      '  wire input 1 \\a\n  wire output 2 \\y\n')
            if style == 'buffer':
                content = ('  cell $buf \\u_buffer\n    parameter \\WIDTH 1\n'
                           f"    connect \\A 1'{value}\n"
                           '    connect \\Y \\y\n  end\n')
            else:
                content = f"  connect \\y 1'{value}\n"
            sections.append(header + content + 'end\n')
    source = folder / 'constants.il'
    source.write_text(''.join(sections))
    yosys.run_pass('read_rtlil ' + str(source), design)


def check_filters(mapper, folder):
    source = '''
module allowed(input wire a,b,output wire y); assign y=a&b; endmodule
module unknown_value(input wire a,output wire y); assign y=a?1'bx:1'b0; endmodule
module tristate_value(input wire a,en,output wire y); assign y=en?a:1'bz; endmodule
module stateful(input wire clk,a,output reg y); always @(posedge clk) y<=a; endmodule
module bidirectional(inout wire a,input wire b,output wire y); assign y=a&b; endmodule
module child_module(input wire a,b,output wire y); allowed u_child(a,b,y); endmodule
'''
    design = design_from_text(folder, source)
    add_buffer_modules(design, folder)
    add_constant_modules(design, folder)
    expected = {'allowed': True, 'unknown_value': False, 'tristate_value': False,
                'stateful': False, 'bidirectional': False, 'child_module': False,
                'buffer_1': True, 'buffer_3': True,
                'constant_0_buffer': True, 'constant_1_buffer': True,
                'constant_0_direct': True, 'constant_1_direct': True}
    actual = {name: mapper.combinational_leaf(design.module('\\' + name)) for name in expected}
    assert actual == expected, (actual, expected)
    return actual


def check_signatures(mapper, folder):
    from pyosys import libyosys as yosys
    source = leaf('original', 'internal_one') + leaf('renamed', 'different_internal')
    source += leaf('different_relation', 'renamed_internal', output_operand='a')
    source += leaf('different_range', 'renamed_again', offset=3)
    source += '''
module undriven_input(input wire a,output wire y);
    wire missing_driver; assign y=a&missing_driver;
endmodule
module combinational_cycle(input wire a,output wire y);
    wire feedback; assign feedback=a^feedback; assign y=feedback;
endmodule
'''
    design = design_from_text(folder, source)
    signatures = {name: mapper.leaf_signature(design.module('\\' + name))
                  for name in ('original', 'renamed', 'different_relation', 'different_range')}
    assert signatures['original'] == signatures['renamed']
    assert signatures['original'] != signatures['different_relation']
    assert signatures['original'] != signatures['different_range']
    add_buffer_modules(design, folder)
    for name in ('buffer_3', 'buffer_reordered', 'direct_wires'):
        signatures[name] = mapper.leaf_signature(design.module('\\' + name))
    assert signatures['buffer_3'] == signatures['direct_wires']
    assert signatures['buffer_3'] != signatures['buffer_reordered']
    add_constant_modules(design, folder)
    for value in (0, 1):
        for style in ('buffer', 'direct'):
            name = f'constant_{value}_{style}'
            signatures[name] = mapper.leaf_signature(design.module('\\' + name))
        assert signatures[f'constant_{value}_buffer'] == signatures[f'constant_{value}_direct']
    assert signatures['constant_0_direct'] != signatures['constant_1_direct']
    mismatch = folder / 'buffer_mismatch.il'
    mismatch.write_text(buffer_module('buffer_mismatch', 3).replace(
        'connect \\A \\a\n', 'connect \\A \\a [0]\n'))
    yosys.run_pass('read_rtlil ' + str(mismatch), design)
    for name in ('undriven_input', 'combinational_cycle', 'buffer_mismatch'):
        try:
            mapper.leaf_signature(design.module('\\' + name))
        except RuntimeError:
            pass
        else:
            raise AssertionError('无效组合图未被拒绝: ' + name)
    return signatures


def mapping_command(mapper, folder):
    import pyosys
    package = str(Path(pyosys.__file__).parent)
    os.environ['PATH'] = package + os.pathsep + os.environ.get('PATH', '')
    folder.mkdir(parents=True, exist_ok=True)
    return mapper.discover_profile(folder, os.environ.copy())['abc9']


def check_mapping(mapper, folder, *, corrupt_signature=False):
    from pyosys import libyosys as yosys
    source = leaf('first_leaf', 'first_internal', module_tag=17, port_tag=101)
    source += leaf('second_leaf', 'second_internal', module_tag=29, port_tag=203,
                   output_operand='a' if corrupt_signature else 'b')
    source += '''
(* keep_hierarchy=1, mapping_parent_tag=73 *)
module untouched_parent(input wire [2:0] a,b,output wire [5:0] y);
    (* mapping_instance_tag=41 *) first_leaf first(a,b,y[2:0]);
    (* mapping_instance_tag=59 *) second_leaf second(a,b,y[5:3]);
endmodule
'''
    design = design_from_text(folder, source)
    names = ['\\first_leaf', '\\second_leaf']
    original_ports = {name: ports(design.module(name)) for name in names}
    original_attributes = {name: attributes(design.module(name)) for name in names}
    parent_before = module_contents(design.module('\\untouched_parent'))
    assert all(mapper.combinational_leaf(design.module(name)) for name in names)
    command = mapping_command(mapper, folder / 'profile')
    calls = []
    original_run_pass = yosys.run_pass

    def observed_pass(value, target=None):
        if value == command:
            calls.append(value)
        return original_run_pass(value, target)

    yosys.run_pass = observed_pass
    if corrupt_signature:
        # 两个不同函数被强制归为同组时，逐模块 SAT 必须阻止合并。
        mapper.leaf_signature = lambda module: 'forced_shared_signature'
    try:
        mapper.map_leaves(design, names, folder / 'mapping.json', command)
    finally:
        yosys.run_pass = original_run_pass
    assert not corrupt_signature, '不同函数通过了逐模块 SAT 检查'
    assert len(calls) == 1, calls
    for name in names:
        assert attributes(design.module(name)) == original_attributes[name], name
        assert ports(design.module(name)) == original_ports[name], name
    assert module_contents(design.module('\\untouched_parent')) == parent_before
    yosys.run_pass('select -clear; hierarchy -check; check -assert', design)
    return {'abc9_calls': len(calls), 'leaf_modules': len(names),
            'parent_unchanged': True, 'module_attributes_preserved': True,
            'ports_and_attributes_preserved': True}


def check_reordered_buffer(mapper, folder):
    from pyosys import libyosys as yosys
    folder.mkdir(parents=True, exist_ok=True)
    design = yosys.Design()
    add_buffer_modules(design, folder)
    command = mapping_command(mapper, folder / 'profile')
    mapper.leaf_signature = lambda module: 'forced_shared_signature'
    mapper.map_leaves(design, ['\\buffer_3', '\\buffer_reordered'], folder / 'mapping.json', command)
    raise AssertionError('输出位重排通过了逐模块 SAT 检查')


def check_constant_mapping(mapper, folder):
    from pyosys import libyosys as yosys
    folder.mkdir(parents=True, exist_ok=True)
    design = yosys.Design()
    add_constant_modules(design, folder)
    names = [f'\\constant_{value}_{style}' for value in (0, 1) for style in ('buffer', 'direct')]
    original = {name: (ports(design.module(name)), attributes(design.module(name))) for name in names}
    command = mapping_command(mapper, folder / 'profile')
    mapper.map_leaves(design, names, folder / 'mapping.json', command)
    for name in names:
        assert (ports(design.module(name)), attributes(design.module(name))) == original[name]
    return {'constant_functions': 2, 'equivalent_modules': 4}


def worker(mode, folder):
    mapper = load_mapper()
    if mode == 'filters':
        result = check_filters(mapper, folder)
    elif mode == 'signatures':
        result = check_signatures(mapper, folder)
    elif mode == 'mapping':
        result = check_mapping(mapper, folder)
    elif mode == 'reject_non_equivalent':
        result = check_mapping(mapper, folder, corrupt_signature=True)
    elif mode == 'reject_reordered_buffer':
        result = check_reordered_buffer(mapper, folder)
    elif mode == 'constant_mapping':
        result = check_constant_mapping(mapper, folder)
    else:
        raise ValueError(mode)
    (folder / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print('ABC9_LEAF_TEST_PASS ' + mode, flush=True)


class Abc9LeafTests(unittest.TestCase):
    def execute(self, mode, *, expect_failure=False):
        folder = OUT / mode
        folder.mkdir(parents=True, exist_ok=True)
        log_path = folder / 'run.log'
        with log_path.open('w') as log:
            process = subprocess.run([sys.executable, str(Path(__file__).resolve()),
                '--worker', mode, '--out', str(folder)], cwd=ROOT, stdout=log,
                stderr=subprocess.STDOUT, timeout=90)
        output = log_path.read_text()
        if expect_failure:
            self.assertNotEqual(process.returncode, 0, output[-8000:])
            self.assertRegex(output, r'proof did fail|proof.*failed', output[-8000:])
        else:
            self.assertEqual(process.returncode, 0, output[-8000:])
            self.assertIn('ABC9_LEAF_TEST_PASS ' + mode, output)
        return output

    def test_eligible_boolean_modules(self):
        self.execute('filters')

    def test_signature_tracks_ports_and_logic(self):
        self.execute('signatures')

    def test_mapping_reuses_function_and_preserves_design(self):
        output = self.execute('mapping')
        self.assertRegex(output, r'(?m)^ABC9_LEAF_PROOFS 2$')
        self.assertRegex(output, r'(?m)^ABC9_LEAF_FUNCTIONS 1$')

    def test_sat_rejects_non_equivalent_reuse(self):
        self.execute('reject_non_equivalent', expect_failure=True)

    def test_sat_rejects_reordered_buffer_reuse(self):
        self.execute('reject_reordered_buffer', expect_failure=True)

    def test_mapping_preserves_zero_and_one(self):
        output = self.execute('constant_mapping')
        self.assertRegex(output, r'(?m)^ABC9_LEAF_PROOFS 4$')
        self.assertRegex(output, r'(?m)^ABC9_LEAF_FUNCTIONS 2$')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker')
    parser.add_argument('--out', type=Path, default=OUT)
    arguments, remaining = parser.parse_known_args()
    OUT = arguments.out.resolve()
    if arguments.worker:
        worker(arguments.worker, OUT)
    else:
        unittest.main(argv=[sys.argv[0]] + remaining)
