#!/usr/bin/env python3
"""Compare complete designs with native parameterized combinational helpers."""
from __future__ import annotations
import argparse
import collections
import hashlib
import json
from pathlib import Path
import re
import runpy
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'test/conv_frontend/tools'))
from measure_complete_paths import measure
from test_hierarchy_mapping import prove_mapped_equivalence

SMALL = '''module helper_instances(
 input logic [12:0] sa,sb,
 input logic [12:0][1:0] da,db,
 input logic [6:0] sc,dc,
 input logic [5:0] low_a,low_b,
 input logic borrow_a,borrow_b,high_a,high_b,last_a,last_b,
 output logic [1:0] ya,yb,
 output logic yc,allowed_a,allowed_b
);
 onehot_mux #(.p_choices(13),.p_width(2)) u_a(sa,da,ya);
 onehot_mux #(.p_choices(13),.p_width(2)) u_b(sb,db,yb);
 onehot_mux #(.p_choices(7),.p_width(1)) u_c(sc,dc,yc);
 conv_channel_range_compare #(.p_width(6),.p_step(0),.p_lane(2)) u_range_a(
 low_a,low_b,borrow_a,high_a,last_a,allowed_a);
 conv_channel_range_compare #(.p_width(6),.p_step(7),.p_lane(13)) u_range_b(
 low_b,low_a,borrow_b,high_b,last_b,allowed_b);
endmodule
'''
DUPLICATE = '''module duplicate_inputs(
 input logic[12:0] s,input logic[12:0][1:0] d,output logic[1:0] a,b
);
 onehot_mux #(.p_choices(13),.p_width(2)) u_a(s,d,a);
 onehot_mux #(.p_choices(13),.p_width(2)) u_b(s,d,b);
endmodule
'''


def parallel_compare_source():
    """Exercise all current comparator widths with repeated physical instances."""
    widths = (1, 2, 3, 7, 16, 27, 35, 64)
    ports = [f'input logic [{width - 1}:0] a{index},b{index}'
             for index, width in enumerate(widths)]
    ports += ['output logic [15:0] less,equal']
    cells = []
    for index, width in enumerate(widths):
        for copy in range(2):
            lane = 2 * index + copy
            cells.append(f'parallel_unsigned_compare #(.p_width({width})) u_{lane}('
                         f'.i_a(a{index}),.i_b(b{index}),.o_less(less[{lane}]),.o_equal(equal[{lane}]));')
    return 'module parallel_compare_instances(' + ',\n'.join(ports) + ');\n' + '\n'.join(cells) + '\nendmodule\n'


def add_equal_source():
    """Cover every bit/reduction parameter while retaining original adder parents."""
    widths = (1, 2, 3, 4, 5, 6, 7, 16, 27, 32, 33, 64)
    ports = [f'input logic [{width - 1}:0] a{index},b{index},t{index},input logic c{index}'
             for index, width in enumerate(widths)]
    ports += ['output logic [25:0] equal']
    cells = []
    for index, width in enumerate(widths):
        for preserve in range(2):
            lane = 2 * index + preserve
            cells.append(f'add_equal #(.p_width({width}),.p_preserve_bits({preserve})) u_{lane}('
                         f'.i_a(a{index}),.i_b(b{index}),.i_target(t{index}),'
                         f'.i_carry_in(c{index}),.o_equal(equal[{lane}]));')
    for lane in (24, 25):
        cells.append(f'add_equal #(.p_width(32),.p_preserve_bits(1)) u_{lane}('
                     f'.i_a(a9),.i_b(b9),.i_target(t9),.i_carry_in(c9),.o_equal(equal[{lane}]));')
    return 'module add_equal_instances(' + ',\n'.join(ports) + ');\n' + '\n'.join(cells) + '\nendmodule\n'


def formatter_helper_source():
    """Exercise recursive boundaries, vector widths and independent copies."""
    ports = ['input logic[8:0] sum_a,sum_b,sum_c,sum_d', 'output logic[8:0] sum_y,sum_z']
    cells = ['conv_im2col_sample_sum u_sum_a(sum_a,sum_b,sum_y);',
             'conv_im2col_sample_sum u_sum_b(sum_c,sum_d,sum_z);']
    for index, (count, width) in enumerate(((1, 1), (2, 2), (3, 16), (6, 1), (7, 16), (18, 16), (37, 2))):
        ports += [f'input logic[{count-1}:0][{width-1}:0] r{index}_a,r{index}_b',
                  f'output logic[{width-1}:0] r{index}_y,r{index}_z']
        for suffix, result in (('a', 'y'), ('b', 'z')):
            cells.append(f'conv_im2col_formatter_reduce #(.p_count({count}),.p_width({width})) '
                         f'u_reduce_{index}_{suffix}(r{index}_{suffix},r{index}_{result});')
    for index, (count, width) in enumerate(((1, 1), (2, 2), (3, 16), (4, 16), (8, 16), (18, 16), (48, 2))):
        ports += [f'input logic[{count-1}:0] m{index}_s,m{index}_t',
                  f'input logic[{count-1}:0][{width-1}:0] m{index}_a,m{index}_b',
                  f'output logic[{width-1}:0] m{index}_y,m{index}_z']
        for suffix, selected, result in (('a', 's', 'y'), ('b', 't', 'z')):
            cells.append(f'conv_im2col_formatter_mux #(.p_choices({count}),.p_width({width})) '
                         f'u_mux_{index}_{suffix}(m{index}_{selected},m{index}_{suffix},m{index}_{result});')
    return 'module formatter_helpers(' + ',\n'.join(ports) + ');\n' + '\n'.join(cells) + '\nendmodule\n'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command, log):
    with log.open('w') as stream:
        subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT,
                       check=True, timeout=300)


def export_hierarchy(folder, top):
    """Normalize aliases and retain every reachable hierarchy definition."""
    script = folder / 'hierarchy.ys'
    script.write_text(f'read_rtlil {folder / "elaborated.il"}\n'
                     f'select {top} %s %s %s %s\n'
                     'opt_expr\nopt_clean\n'
                     f'write_json -selected {folder / "hierarchy.json"}\n')
    run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
         '--worker', str(script)], folder / 'hierarchy.log')
    return json.loads((folder / 'hierarchy.json').read_text())


def hierarchy_inventory(design, top):
    """Expand module instances and identify every connected module port bit."""
    modules = design['modules']
    parent, endpoints, instances, states = {}, {}, {}, collections.Counter()

    def bit_node(path, bit):
        return ('constant', bit) if isinstance(bit, str) else (path, bit)

    def find(node):
        parent.setdefault(node, node)
        if parent[node] != node:
            parent[node] = find(parent[node])
        return parent[node]

    def join(first, second):
        first, second = find(first), find(second)
        if first != second:
            parent[first] = second

    def walk(name, path, active):
        assert name not in active, ('recursive hierarchy', name)
        module = modules[name]
        attributes = module.get('attributes', {})
        assert not attributes.get('blackbox') and not attributes.get('whitebox'), name
        origin = attributes.get('hdlname', name.split('$')[0])
        ports = {port: (details['direction'], len(details['bits']))
                 for port, details in module['ports'].items()}
        instances[path] = {'origin': origin, 'ports': ports,
                           'keep_hierarchy': attributes.get('keep_hierarchy')}
        for port, details in module['ports'].items():
            for index, bit in enumerate(details['bits']):
                endpoints[(path, port, index)] = bit_node(path, bit)
        for cell_name, cell in module['cells'].items():
            kind = cell['type']
            if kind in modules:
                child_path = path + '.' + cell_name.lstrip('\\')
                child_ports = modules[kind]['ports']
                assert set(cell['connections']) == set(child_ports), (child_path, 'port names')
                walk(kind, child_path, active | {name})
                for port, bits in cell['connections'].items():
                    child = child_ports[port]
                    assert len(bits) == len(child['bits']), (child_path, port, 'width')
                    assert cell['port_directions'][port] == child['direction']
                    for external, internal in zip(bits, child['bits']):
                        join(bit_node(path, external), bit_node(child_path, internal))
            elif re.search(r'dff|dffe|latch|mem', kind, re.IGNORECASE):
                states[(path, kind, json.dumps(cell['parameters'], sort_keys=True))] += 1
            else:
                assert kind.startswith('$'), (path, 'unresolved module', kind)
    walk(top, top, set())
    groups = collections.defaultdict(list)
    for endpoint, node in endpoints.items():
        groups[find(node)].append(endpoint)
    for node in parent:
        if node[0] == 'constant':
            groups[find(node)].append(('<constant>', node[1], 0))
    connected_ports = sorted(sorted(value) for value in groups.values())
    return {'instances': instances, 'connected_ports': connected_ports,
            'state_cells': sorted((list(key), count) for key, count in states.items()),
            'module_definitions': len(modules), 'expanded_instances': len(instances) - 1}


def compare_case(source_root, output, configuration, name, case):
    inventories, mapped, summaries, graphs = {}, {}, {}, {}
    for mode in ('slang', 'native'):
        out = output / ('descriptor_' + mode)
        command = [sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                   '--source-root', str(source_root), '--case-config', str(configuration),
                   '--cases', name, '--out', str(out), '--resume']
        if mode == 'native':
            command.append('--native-combinational-helpers')
        run(command, output / (name + '_' + mode + '.log'))
        folder = out / name
        inventories[mode] = hierarchy_inventory(export_hierarchy(folder, case['top']), case['top'])
        mapped[mode] = json.loads((folder / 'mapped.json').read_text())
        graphs[mode] = measure(mapped[mode]['modules'][case['top']])
        assert graphs[mode]['graph_complete'], mode
        (folder / 'complete_paths.json').write_text(json.dumps(graphs[mode], indent=2) + '\n')
        summaries[mode] = json.loads((out / 'summary.json').read_text())['cases'][name]
    before, after = inventories['slang'], inventories['native']
    assert before['instances'] == after['instances'], 'Expanded instances or module ports changed'
    assert before['connected_ports'] == after['connected_ports'], 'Module port connections changed'
    assert before['state_cells'] == after['state_cells'], 'State boundaries changed'
    assert after['module_definitions'] < before['module_definitions']
    for key in ('cell_counts', 'lut_cells', 'flip_flops', 'dsp', 'ramb18', 'ramb36',
                'longest_combinational_path_cells'):
        assert summaries['slang'][key] == summaries['native'][key], key
    assert graphs['slang']['maximum_combinational_cells'] == graphs['native']['maximum_combinational_cells']
    proof = output / (name + '_proof')
    proof.mkdir(exist_ok=True)
    prove_mapped_equivalence(proof, mapped['slang'], mapped['native'], case['top'], bool(before['state_cells']))
    report = {
        'passed': True, 'top': case['top'], 'parameters': case.get('parameters', {}),
        'sources_sha256': summaries['slang']['sources_sha256'],
        'input_sources_identical': summaries['slang']['sources_sha256'] == summaries['native']['sources_sha256'],
        'module_definitions': {mode: inventories[mode]['module_definitions'] for mode in inventories},
        'expanded_instances': before['expanded_instances'],
        'all_instance_interfaces_equal': True, 'all_module_port_connections_equal': True,
        'state_boundaries_equal': True, 'mapped_functionally_equivalent': True,
        'mapped_cell_counts': summaries['native']['cell_counts'],
        'maximum_combinational_cells': graphs['native']['maximum_combinational_cells'],
        'interface_bits': graphs['native']['interface_bits'], 'graph_complete': True,
        'mapping_stages': {mode: summaries[mode]['stages']['03_map_lut'] for mode in summaries},
        'proof_log_sha256': digest(proof / 'equivalence.log'),
    }
    assert report['input_sources_identical']
    (output / (name + '_comparison.json')).write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: report[key] for key in ('passed', 'top', 'parameters',
          'module_definitions', 'expanded_instances', 'maximum_combinational_cells')}), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    supported = ['helpers', 'duplicate', 'parallel_compare', 'add_equal', 'descriptor_8', 'descriptor_16',
                 'formatter_helpers', 'formatter_8', 'formatter_16']
    parser.add_argument('--cases', nargs='+', default=supported, choices=supported)
    args = parser.parse_args()
    output, source_root = args.out.resolve(), args.source_root.resolve()
    output.mkdir(parents=True, exist_ok=True)
    small = output / 'helper_instances.sv'
    small.write_text(SMALL)
    duplicate = output / 'duplicate_instances.sv'
    duplicate.write_text(DUPLICATE)
    comparison = output / 'parallel_compare_instances.sv'
    comparison.write_text(parallel_compare_source())
    addition = output / 'add_equal_instances.sv'
    addition.write_text(add_equal_source())
    cases = {'helpers': {'top': 'helper_instances',
             'sources': [str(small), 'rtl/common/onehot_mux.sv',
                         'rtl/npu/conv/conv_channel_range_compare.sv'], 'options': [],
             'configuration': 'Independent instances with repeated and distinct helper parameters'}}
    cases['duplicate'] = {'top': 'duplicate_inputs',
                         'sources': [str(duplicate), 'rtl/common/onehot_mux.sv'], 'options': [],
                         'configuration': 'Independent helper instances receiving identical inputs'}
    cases['parallel_compare'] = {
        'top': 'parallel_compare_instances',
        'sources': [str(comparison), 'rtl/common/parallel_unsigned_compare.sv'],
        'options': ['-D', 'SYNTHESIS=1'],
        'configuration': 'Repeated complete comparator trees at widths 1, 2, 3, 7, 16, 27, 35 and 64',
    }
    cases['add_equal'] = {
        'top': 'add_equal_instances',
        'sources': [str(addition), 'rtl/common/add_equal.sv'],
        'options': ['-D', 'SYNTHESIS=1'],
        'configuration': 'Original add_equal parents at twelve widths and both structural modes, with repeated 32-bit instances',
    }
    if any(name.startswith('formatter') for name in args.cases):
        stream = 'rtl/npu/conv/conv_im2col_stream.sv'
        helper_model = output / 'formatter_helpers.sv'
        helper_model.write_text(formatter_helper_source())
        cases['formatter_helpers'] = {
            'top': 'formatter_helpers', 'sources': [str(helper_model), stream],
            'options': ['-D', 'SYNTHESIS=1'],
            'configuration': 'Independent formatter helpers with recursive counts and vector widths',
        }
        checker = source_root / 'test/conv_frontend/tools/check_return_formatter.py'
        formatter = runpy.run_path(str(checker))['model']((source_root / stream).read_text())
        formatter_model = output / 'formatter.sv'
        formatter_model.write_text(formatter[formatter.index('module formatter #'):])
        for lanes in (8, 16):
            cases[f'formatter_{lanes}'] = {
                'top': 'formatter', 'sources': [str(formatter_model), stream],
                'options': ['-D', 'SYNTHESIS=1', f'-Gp_lanes={lanes}', f'-Gp_cache_read_bytes={lanes}'],
                'parameters': {'p_lanes': lanes, 'p_cache_read_bytes': lanes},
                'configuration': f'Complete {lanes}-lane formatter extracted from the production stream',
            }
    for lanes in (8, 16):
        cases[f'descriptor_{lanes}'] = {
            'top': 'conv_im2col_descriptor',
            'sources': ['rtl/npu/conv/conv_im2col_pkg.sv', 'rtl/npu/conv/conv_im2col_frontend_pkg.sv',
                        'rtl/npu/conv/conv_im2col_descriptor.sv'],
            'options': ['-D', 'SYNTHESIS=1', '-Gp_size=16', f'-Gp_lanes={lanes}',
                        '-Gp_line_bytes=128', '-Gp_register_descriptor=0'],
            'parameters': {'p_size': 16, 'p_lanes': lanes, 'p_line_bytes': 128, 'p_register_descriptor': 0},
            'configuration': f'Complete descriptor with {lanes} lanes, 128-byte cache lines, direct descriptor acceptance',
        }
    configuration = output / 'helper_cases.json'
    configuration.write_text(json.dumps(cases, indent=2) + '\n')
    results = {name: compare_case(source_root, output, configuration, name, cases[name]) for name in args.cases}
    (output / 'comparison_summary.json').write_text(json.dumps({'passed': True, 'cases': results}, indent=2) + '\n')


if __name__ == '__main__':
    main()
