#!/usr/bin/env python3
"""Verify exact component-definition reuse with independent physical state."""
from __future__ import annotations

import argparse
import collections
from contextlib import contextmanager
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from netlist_metrics import register_origins
from preserve_rtl_hierarchy import original_module
from reuse_rtl_definitions import canonical_definition, reuse_definitions
from test_hierarchy_mapping import prove_mapped_equivalence


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT
OUTPUT = None
sys.path.insert(0, str(ROOT / 'test/conv_frontend/tools'))
from measure_complete_paths import measure


@contextmanager
def directory(name):
    if OUTPUT is None:
        with tempfile.TemporaryDirectory(prefix='rtl_definition_reuse_') as temporary:
            yield Path(temporary)
    else:
        path = OUTPUT / name
        path.mkdir(parents=True, exist_ok=True)
        yield path


def source_text(count, width, accumulator, exchange=1):
    return f'''module reuse_top(
 input logic clk,input logic [{count-1}:0] commit,store,
 input logic [{width-1}:0] data[{count}],weight[{count}],
 input logic [{accumulator-1}:0] partial[{count}],
 output logic [{width-1}:0] result_data[{count}],result_weight[{count}],
 output logic [{accumulator-1}:0] result_sum[{count}]);
 for(genvar i=0;i<{count};i++) begin: g_cells
  ws_systolic_cell #(.DATA_IN_WIDTH({width}),.WEIGHT_WIDTH({width}),
   .ACC_WIDTH({accumulator}),.p_exchange_weights({exchange})) u_cell(
   .clk(clk),.commit_weight(commit[i]),.store_weight_req(store[i]),
   .weight_in(weight[i]),.data_in(data[i]),.sum_in(partial[i]),
   .data_out(result_data[i]),.weight_out(result_weight[i]),.sum_out(result_sum[i]));
 end
endmodule
'''


def load(folder, text):
    from pyosys import libyosys as yosys
    source = folder / 'source.sv'
    source.write_text(text)
    design = yosys.Design()
    yosys.run_pass('read_slang --best-effort-hierarchy --top reuse_top -D XILINX_FPGA=1 '
                  + str(source) + ' ' + str(SOURCE / 'rtl/npu/compute/ws_systolic_cell.sv'), design)
    return design


class DefinitionReuseTest(unittest.TestCase):
    def test_256_production_instances_keep_every_state_and_connection(self):
        with directory('production_256_instances') as folder:
            design = load(folder, source_text(256, 16, 32, 0))
            report = reuse_definitions(design, 'reuse_top', {'ws_systolic_cell'}, set(), {'ws_systolic_cell'})
            self.assertEqual(report['original_definitions'], 256)
            self.assertEqual(report['reused_definitions'], 1)
            self.assertEqual(report['physical_instance_count'], 256)
            self.assertEqual(report['before']['state_cell_count'], 1024)
            self.assertEqual(report['after']['state_cell_count'], 1024)
            self.assertEqual(report['before']['leaf_pin_count'], report['after']['leaf_pin_count'])
            self.assertEqual(report['before']['circuit_sha256'], report['after']['circuit_sha256'])
            (folder / 'comparison.json').write_text(json.dumps(report, indent=2) + '\n')

    def test_resolved_parameters_keep_distinct_definitions(self):
        with directory('resolved_parameters') as folder:
            text = source_text(4, 4, 9, 'i%2')
            design = load(folder, text)
            report = reuse_definitions(design, 'reuse_top', {'ws_systolic_cell'}, set(), {'ws_systolic_cell'})
            self.assertEqual(report['original_definitions'], 4)
            self.assertEqual(report['reused_definitions'], 2)
            self.assertEqual(report['physical_instance_count'], 4)
            (folder / 'comparison.json').write_text(json.dumps(report, indent=2) + '\n')

    def test_hardware_attributes_parameters_and_state_connections_prevent_reuse(self):
        from pyosys import libyosys as yosys
        with directory('hardware_differences') as folder:
            for mutation in ('state_input', 'clock_parameter', 'wire_keep', 'wire_init', 'cell_keep', 'module_keep'):
                with self.subTest(mutation=mutation):
                    design = load(folder, source_text(2, 4, 9))
                    modules = [module for module in design.modules_.values()
                               if original_module(design, module) == 'ws_systolic_cell']
                    module = modules[0]
                    state = next(cell for cell in module.cells_.values() if design.str(cell.type) == '$dff')
                    if mutation == 'state_input':
                        state.setPort('\\D', state.getPort('\\Q'))
                    elif mutation == 'clock_parameter':
                        state.setParam('\\CLK_POLARITY', yosys.Const(0, 1))
                    elif mutation == 'wire_keep':
                        module.wire('\\data_reg').set_bool_attribute('\\keep', True)
                    elif mutation == 'wire_init':
                        module.wire('\\data_reg').attributes['\\init'] = yosys.Const(1, 4)
                    elif mutation == 'cell_keep':
                        state.set_bool_attribute('\\keep', True)
                    else:
                        module.set_bool_attribute('\\keep', True)
                    first = canonical_definition(design, modules[0])[0]
                    second = canonical_definition(design, modules[1])[0]
                    self.assertNotEqual(first, second)
                    report = reuse_definitions(design, 'reuse_top', {'ws_systolic_cell'}, set(), {'ws_systolic_cell'})
                    self.assertEqual(report['reused_definitions'], 2)
                    self.assertEqual(report['removed_definitions'], 0)

    def mapped_components(self, name, shared_inputs=False):
        with directory(name) as folder:
            source = folder / 'components.sv'
            text = source_text(4, 3, 8)
            if shared_inputs:
                for signal in ('commit', 'store', 'data', 'weight', 'partial'):
                    text = text.replace('(' + signal + '[i])', '(' + signal + '[0])')
            source.write_text(text)
            config = folder / 'cases.json'
            config.write_text(json.dumps({'component': {
                'top': 'reuse_top', 'sources': [str(source), 'rtl/npu/compute/ws_systolic_cell.sv'],
                'options': ['-D', 'XILINX_FPGA=1'],
                'configuration': 'Four independent production systolic components with registered state'}}))
            results = {}
            for mode in ('reference', 'reused'):
                output = folder / mode
                command = [sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                    '--source-root', str(SOURCE), '--case-config', str(config), '--cases', 'component',
                    '--out', str(output), '--preserve-rtl-module', 'ws_systolic_cell', '--abc9-batch-size', '16']
                if mode == 'reused':
                    command += ['--reuse-rtl-module-definition', 'ws_systolic_cell']
                with (folder / (mode + '.log')).open('w') as log:
                    subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=240)
                case = output / 'component'
                design = json.loads((case / 'mapped.json').read_text())
                module = design['modules']['reuse_top']
                paths = measure(module)
                self.assertTrue(paths['graph_complete'])
                origins = register_origins(case / 'pre_lut.il', top='reuse_top')
                registers = [name for name, cell in module['cells'].items()
                             if cell['type'].startswith(('FDRE', 'FDCE', 'FDSE', 'FDPE'))]
                self.assertTrue(registers)
                self.assertEqual(set(registers), set(origins) & set(module['cells']))
                for index in range(4):
                    prefix = f'g_cells[{index}].u_cell.'
                    self.assertTrue(any(value.startswith(prefix) for value in origins.values()), prefix)
                results[mode] = {'design': design, 'resources': dict(collections.Counter(
                    cell['type'] for cell in module['cells'].values())), 'paths': paths,
                    'register_origins': len(registers)}
            self.assertEqual(results['reference']['resources'], results['reused']['resources'])
            proof = folder / 'mapped_equivalence'
            proof.mkdir(exist_ok=True)
            prove_mapped_equivalence(proof, results['reference']['design'], results['reused']['design'],
                                     'reuse_top', True)
            report = json.loads((folder / 'reused/component/rtl_hierarchy_report.json').read_text())['definition_reuse']
            self.assertEqual(report['original_definitions'], 4)
            self.assertEqual(report['reused_definitions'], 1)
            self.assertEqual(report['physical_instance_count'], 4)
            result = {'passed': True, 'mapped_sequential_equivalence': True,
                'all_instance_register_origins_recovered': True, 'physical_instances': 4,
                'resources': {mode: item['resources'] for mode, item in results.items()},
                'mapped_registers': {mode: item['register_origins'] for mode, item in results.items()},
                'maximum_combinational_cells': {mode: item['paths']['maximum_combinational_cells']
                                                for mode, item in results.items()}}
            (folder / 'comparison.json').write_text(json.dumps(result, indent=2) + '\n')

    def test_complete_mapped_sequential_equivalence_and_instance_origins(self):
        self.mapped_components('mapped_sequential_components')

    def test_identical_inputs_keep_distinct_physical_state(self):
        self.mapped_components('mapped_identical_inputs', shared_inputs=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path)
    args, remaining = parser.parse_known_args()
    SOURCE = args.source_root.resolve()
    OUTPUT = args.out.resolve() if args.out else None
    unittest.main(argv=[sys.argv[0], *remaining])
