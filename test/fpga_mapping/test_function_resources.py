#!/usr/bin/env python3
"""检查功能归属的共享集合、DSP 数据端口和资源总数。"""
from fractions import Fraction
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from function_resources import analyze, unobserved_cells


def cell(kind, inputs, outputs):
    ports = {**inputs, **outputs}
    return {'type': kind, 'connections': ports,
            'port_directions': {port: 'input' if port in inputs else 'output' for port in ports},
            'parameters': {'INIT': '10'} if kind == 'LUT1' else {}}


def main():
    cells = {name: cell('LUT1', {'I0': [1]}, {'O': [bit]})
             for name, bit in [('shared', 2), ('unique', 3), ('dead', 4),
                               ('clock', 5), ('dsp_c', 6), ('memory_data', 8)]}
    cells.update({
        'matrix_ff': cell('FDRE', {'D': [2], 'CE': [3], 'C': [0]}, {'Q': [10]}),
        'vector_ff': cell('FDRE', {'D': [2], 'CE': ['1'], 'C': [5]}, {'Q': [11]}),
        'vector_result': cell('FDRE', {'D': [7], 'CE': ['1'], 'C': [0]}, {'Q': [12]}),
        'dsp': cell('DSP48E1', {'C': [6], 'CLK': [0]}, {'P': [7]}),
        'u_axi_sim_ram.mem': cell('RAMB18E1', {'DIADI': [8], 'CLKARDCLK': [0]}, {'DOADO': [9]}),
    })
    module = {'cells': cells, 'netnames': {},
              'ports': {'result': {'direction': 'output', 'bits': [9, 10, 11, 12]}}}
    origins = {'matrix_ff': 'u_npu_axil_top.u_npu_top.u_matrix_engine.u_ia_loader.data [0]',
               'vector_ff': 'u_npu_axil_top.u_npu_top.g_vector_engine.u_engine.u_control.flag [0]',
               'vector_result': 'u_npu_axil_top.u_npu_top.g_vector_engine.u_engine.u_control.result [0]'}
    assert unobserved_cells(module) == {'dead'}
    result = analyze(module, origins, unobserved_cells(module))
    assert result['logic_lut_cells'] == 6
    assert result['categories'] == {'shared': 1, 'unique': 3, 'unobserved': 1, 'unclassified': 1}
    assert set(result['lut_assignments']['shared']['owners']) == {'matrix.u_ia_loader', 'vector.u_control'}
    assert result['lut_assignments']['dsp_c']['owners'] == ('vector.u_control',)
    assert result['lut_assignments']['memory_data']['owners'] == ('axi_system_memory',)
    assert sum(Fraction(row['allocated_logic_lut_fraction']) for row in result['functions']) == 6
    print('FUNCTION_ATTRIBUTION_TEST_PASS lut_cells=6 shared=1 unique=3 unobserved=1 unclassified=1')


if __name__ == '__main__':
    main()
