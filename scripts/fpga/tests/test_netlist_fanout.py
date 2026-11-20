#!/usr/bin/env python3
"""检查输入引脚扇出、常量排除、时钟分类及实际路径关联。"""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from netlist_fanout import analyze_fanout
from netlist_metrics import analyze
from test_netlist_metrics import cell, flop


class FanoutTest(unittest.TestCase):
    def test_pin_loads_and_path(self):
        module = {'cells': {'q0': flop(1, '0'), 'q1': flop(4, 3),
                           'lut': cell('LUT2', {'I0': [1], 'I1': [1]}, {'O': [3]})},
                  'netnames': {'enable': {'bits': [1]}, 'clock': {'bits': [100]}}}
        module['cells']['q1']['connections']['CE'] = [1]
        report = analyze_fanout(module, analyze(module)['paths'])
        self.assertEqual(report['maximum_nonclock_pin_fanout'], 3)
        self.assertEqual(report['nonclock_nets'][0]['net'], 'enable')
        self.assertEqual(report['nonclock_nets'][0]['control_pin_loads'], 1)
        self.assertEqual(report['clock_nets'][0]['clock_pin_loads'], 2)
        self.assertEqual(report['register_path_groups'][0]['maximum_pin_fanout'], 3)
        self.assertTrue(all(item['net'] not in ('0', '1') for item in report['nonclock_nets']))

    def test_mixed_clock_data(self):
        module = {'cells': {'q': flop(1, 100)}, 'netnames': {}}
        report = analyze_fanout(module)
        self.assertEqual(report['nonclock_nets'][0]['input_pin_loads'], 2)
        self.assertEqual(report['nonclock_nets'][0]['nonclock_pin_loads'], 1)
        self.assertEqual(report['clock_nets'][0]['clock_pin_loads'], 1)

    def test_asynchronous_reset_and_preset_are_controls(self):
        module = {'cells': {'clear': cell('FDCE', {'C': [100], 'CLR': [1], 'D': ['0']}, {'Q': [2]}),
                            'preset': cell('FDPE', {'C': [100], 'PRE': [1], 'D': ['0']}, {'Q': [3]})},
                  'netnames': {}}
        report = analyze_fanout(module)
        self.assertEqual(report['nonclock_nets'][0]['control_pin_loads'], 2)


if __name__ == '__main__':
    unittest.main()
