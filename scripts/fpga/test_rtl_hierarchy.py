#!/usr/bin/env python3
"""Verify original RTL component preservation and complete mapped paths."""
from __future__ import annotations

import argparse
import collections
from contextlib import contextmanager
import gzip
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from netlist_metrics import register_origins
from preserve_rtl_hierarchy import circuit_inventory
from test_hierarchy_mapping import prove_mapped_equivalence

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT
OUTPUT = None
sys.path.insert(0, str(ROOT / 'test/conv_frontend/tools'))
from measure_complete_paths import measure


@contextmanager
def directory(name):
    if OUTPUT is None:
        with tempfile.TemporaryDirectory(prefix='source_hierarchy_') as temporary:
            yield Path(temporary)
    else:
        folder = OUTPUT / name
        folder.mkdir(parents=True, exist_ok=True)
        yield folder


CHAIN = '''module source_bank(input logic clk,input logic [9:0] a,output logic [9:0] q);
 always_ff @(posedge clk) q<=a;
endmodule
module combine(input logic [3:0] a,output logic y);
 assign y=(a[0]&a[1])^(a[2]|a[3]);
endmodule
module sink_bank(input logic clk,input logic d,output logic q);
 always_ff @(posedge clk) q<=d;
endmodule
module component_top(input logic clk,input logic [9:0] a,output logic y);
 logic [9:0] q;logic first,second,third;
 source_bank u_source(clk,a,q);
 combine u_first(q[3:0],first);
 combine u_second({q[6:4],first},second);
 combine u_third({q[9:7],second},third);
 sink_bank u_sink(clk,third,y);
endmodule
'''

PRODUCTION = '''module production_components(
 input logic clk,rst_n,clear,valid,tile_done,
 input logic signed [31:0] lhs[16],rhs[16],
 input logic [5:0] amount,
 output logic accepted,done,
 output logic signed [31:0] sum[16],
 output logic signed [63:0] result,floor_value
);
 registered_vector_add #(.p_lanes(16)) u_add(
 .clk(clk),.rst_n(rst_n),.i_clear(clear),.i_valid(valid),.i_tile_done(tile_done),
 .i_lhs(lhs),.i_rhs(rhs),.o_valid(accepted),.o_tile_done(done),.o_sum(sum));
 vector_round_shift #(.REGISTER_MIDDLE(1),.REGISTER_INPUT(1)) u_round(
 .clk(clk),.value({sum[1],sum[0]}),.amount(amount),.result(result),.floor_value(floor_value));
endmodule
'''


class SourceHierarchyTest(unittest.TestCase):
    def run_case(self, folder, case, modules, mapped=True):
        config = folder / 'cases.json'
        config.write_text(json.dumps({'component': case}, indent=2) + '\n')
        result = {}
        for mode in ('reference', 'preserved'):
            out = folder / mode
            command = [sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                       '--source-root', str(SOURCE), '--case-config', str(config),
                       '--cases', 'component', '--out', str(out)]
            if mode == 'preserved':
                command += [argument for module in modules for argument in ('--preserve-rtl-module', module)]
                if mapped:
                    command += ['--abc9-batch-size', '2']
            if not mapped:
                command += ['--through', 'elaborate']
            with (folder / (mode + '.log')).open('w') as log:
                subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=300)
            if mapped:
                design = json.loads((out / 'component/mapped.json').read_text())
                module = design['modules'][case['top']]
                paths = measure(module)
                self.assertTrue(paths['graph_complete'])
                origins = register_origins(out / 'component/pre_lut.il', top=case['top'])
                count = sum(cell['type'].startswith(('FDRE', 'FDCE', 'FDSE', 'FDPE'))
                            for cell in module['cells'].values())
                self.assertEqual(sum(name in module['cells'] for name in origins), count)
                result[mode] = {'design': design, 'paths': paths, 'flip_flops': count,
                                'origins': origins, 'resources': dict(collections.Counter(
                                    cell['type'] for cell in module['cells'].values()))}
        audit_path = folder / 'preserved/component/rtl_hierarchy_report.json'
        audit = json.loads(audit_path.read_text())
        self.assertTrue(audit['passed'])
        self.assertTrue(audit['all_leaf_pin_connections_equal'])
        self.assertTrue(audit['all_state_connections_equal'])
        self.assertTrue(audit['all_memory_declarations_equal'])
        self.assertGreater(audit['after']['retained_instance_count'], 0)
        if mapped:
            self.assertEqual(result['reference']['flip_flops'], result['preserved']['flip_flops'])
            proof = folder / 'mapped_equivalence'
            proof.mkdir(exist_ok=True)
            prove_mapped_equivalence(proof, result['reference']['design'],
                                     result['preserved']['design'], case['top'], True)
            report = {'passed': True, 'mapped_sequential_equivalence': True,
                      'register_counts_equal': True, 'graph_complete': True,
                      'retained_instances': audit['after']['retained_instance_count'],
                      'resources': {mode: value['resources'] for mode, value in result.items()},
                      'maximum_combinational_cells': {
                          mode: value['paths']['maximum_combinational_cells'] for mode, value in result.items()},
                      'all_register_origins_recovered': True}
            (folder / 'comparison.json').write_text(json.dumps(report, indent=2) + '\n')
        return result, audit

    def test_complete_path_crosses_three_original_components(self):
        with directory('connected_components') as folder:
            source = folder / 'components.sv'
            source.write_text(CHAIN)
            result, audit = self.run_case(folder, {
                'top': 'component_top', 'sources': [str(source)], 'options': [],
                'configuration': 'Five original components with a three-LUT combinational path'},
                ['source_bank', 'combine', 'sink_bank'])
            actual = result['preserved']
            self.assertEqual(actual['paths']['maximum_combinational_cells'], 3)
            self.assertEqual(actual['resources'], {'FDRE': 11, 'LUT4': 3})
            self.assertEqual(audit['after']['retained_instance_count'], 5)
            self.assertTrue(any(value.startswith('u_source.') for value in actual['origins'].values()))

    def test_complete_production_register_components(self):
        with directory('production_components') as folder:
            source = folder / 'production_components.sv'
            source.write_text(PRODUCTION)
            result, audit = self.run_case(folder, {
                'top': 'production_components', 'sources': [str(source),
                    'rtl/npu/compute/registered_vector_add.sv', 'rtl/npu/conv/vector_round_shift.sv'],
                'options': ['-D', 'SYNTHESIS=1'],
                'configuration': 'Complete 16-lane vector adder and registered 64-bit rounding component'},
                ['registered_vector_add', 'vector_round_shift'])
            self.assertGreater(result['preserved']['flip_flops'], 500)
            self.assertEqual(audit['after']['retained_instance_count'], 2)

    def test_nested_memory_parameters_and_state_connections(self):
        with directory('memory_components') as folder:
            source = folder / 'memory_components.sv'
            source.write_text('''module memory_leaf(input logic clk,input logic [1:0] a,
 input logic [7:0] d,output logic [7:0] q,output logic parity);
 logic [7:0] memory[4];
 always_ff @(posedge clk) begin memory[a]<=d;q<=memory[a];end
 assign parity=^q;
endmodule
module memory_middle(input logic clk,input logic [1:0] a,input logic [7:0] d,
 output logic [7:0] q);
 memory_leaf inner(.clk(clk),.a(a),.d(d),.q(q),.parity());
endmodule
module memory_components(input logic clk,input logic [1:0] a,input logic [7:0] d,
 output logic [7:0] q,r);
 memory_middle left(clk,a,d,q);
 memory_middle right(clk,a,q,r);
endmodule
''')
            _, audit = self.run_case(folder, {
                'top': 'memory_components', 'sources': [str(source)], 'options': [],
                'configuration': 'Two original memory instances below retained components'},
                ['memory_middle'], mapped=False)
            self.assertEqual(audit['after']['memory_count'], 2)
            self.assertEqual(audit['after']['state_cell_count'], 6)

    def test_changed_state_input_is_detected(self):
        from pyosys import libyosys as yosys
        with directory('state_connection_check') as folder:
            source = folder / 'state.sv'
            source.write_text(CHAIN)
            design = yosys.Design()
            yosys.run_pass('read_slang --best-effort-hierarchy --top component_top ' + str(source), design)
            before = circuit_inventory(design, 'component_top', {'source_bank'}, set())
            for module in design.selected_unboxed_whole_modules_warn():
                for cell in module.cells_.values():
                    if design.str(cell.type) == '$dff':
                        cell.setPort('\\D', cell.getPort('\\Q'))
            after = circuit_inventory(design, 'component_top', {'source_bank'}, set())
            self.assertNotEqual(before['circuit_sha256'], after['circuit_sha256'])
            self.assertNotEqual(before['state_connections_sha256'], after['state_connections_sha256'])

    def test_nested_compressed_register_origin_names(self):
        text = '''attribute \\top 1
module \\top
  cell \\middle \\u
  end
end
module \\middle
  cell \\inner \\v
  end
end
module \\inner
  cell \\FDRE $priv@42  # $auto$state
    connect \\Q \\data_q [1]
  end
end
'''
        with directory('register_names') as folder:
            path = folder / 'pre_lut.il.gz'
            path.write_bytes(gzip.compress(text.encode()))
            self.assertEqual(register_origins(path), {
                '$flatten\\u.\\v.$auto$state': 'u.v.data_q [1]'})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path)
    args, remaining = parser.parse_known_args()
    SOURCE = args.source_root.resolve()
    OUTPUT = args.out.resolve() if args.out else None
    unittest.main(argv=[sys.argv[0], *remaining])
