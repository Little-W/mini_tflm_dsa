#!/usr/bin/env python3
"""Check placement accounting at shared physical LUT positions."""
import unittest

from placed_resources import placed_resources


def lut(bel, **attributes):
    return {'type': 'SLICE_LUTX', 'attributes': {'NEXTPNR_BEL': bel, **attributes}}


class PlacementResourcesTest(unittest.TestCase):
    def report(self, cells, step='place'):
        return placed_resources({'attributes': {'step': step}, 'cells': cells})

    def test_dual_output_uses_one_position(self):
        report = self.report({'first': lut('SLICE_X1Y2/A5LUT'), 'second': lut('SLICE_X1Y2/A6LUT')})
        self.assertTrue(report['placement_complete'])
        self.assertEqual(report['physical_lut_positions'], 1)
        self.assertEqual(report['placed_lut_bel_instances'], 2)
        self.assertEqual(report['shared_lut_positions'], 1)

    def test_storage_and_logic_categories_are_disjoint(self):
        report = self.report({
            'ram': lut('SLICE_X1Y2/A6LUT', X_LUT_AS_DRAM='0001'),
            'logic': lut('SLICE_X1Y2/A5LUT'),
            'srl': lut('SLICE_X1Y2/B6LUT', X_LUT_AS_SRL=1),
            'ordinary': lut('SLICE_X1Y3/A6LUT'),
        }, step='route')
        self.assertEqual(report['physical_lut_positions'], 3)
        self.assertEqual(report['physical_lut_positions_by_use'], {'logic': 1, 'distributed_ram': 1, 'shift_register': 1})
        self.assertEqual(report['storage_positions_with_logic_output'], 1)

    def test_duplicate_bel_is_rejected(self):
        report = self.report({'a': lut('SLICE_X1Y2/A6LUT'), 'b': lut('SLICE_X1Y2/A6LUT')})
        self.assertFalse(report['placement_complete'])
        self.assertIsNone(report['physical_lut_positions'])

    def test_serialized_storage_markers(self):
        report = self.report({
            'ram': lut('SLICE_X1Y2/A6LUT', X_LUT_AS_DRAM='1 '),
            'srl': lut('SLICE_X1Y2/B6LUT', X_LUT_AS_SRL='1 '),
            'ordinary': lut('SLICE_X1Y2/C6LUT'),
        })
        self.assertEqual(report['physical_lut_positions'], 3)
        self.assertEqual(report['physical_lut_positions_by_use'],
                         {'logic': 1, 'distributed_ram': 1, 'shift_register': 1})

    def test_unplaced_cell_is_rejected(self):
        report = self.report({'a': lut('SLICE_X1Y2/A6LUT'), 'ff': {'type': 'SLICE_FFX', 'attributes': {}}})
        self.assertFalse(report['placement_complete'])
        self.assertEqual(report['unplaced_cells'], ['ff'])

    def test_pack_only_is_not_placement(self):
        report = self.report({'a': lut('SLICE_X1Y2/A6LUT')}, step='pack')
        self.assertFalse(report['placement_complete'])
        self.assertIsNone(report['physical_lut_positions'])

    def test_unrecognized_lut_bel_is_rejected(self):
        report = self.report({'a': lut('DSP48_X1Y2/DSP48E1')})
        self.assertFalse(report['placement_complete'])
        self.assertEqual(len(report['resource_errors']), 1)


if __name__ == '__main__':
    unittest.main()
