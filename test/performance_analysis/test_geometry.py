#!/usr/bin/env python3
"""Validate dataflow inference and padded arithmetic counts."""
from copy import deepcopy
import unittest

from analyze import geometry, observe_geometry


def matrix(m, n, k):
    node = {"op": "FULLY_CONNECTED", "input_shapes": [[m, k], [n, k]],
            "output_shapes": [[m, n]]}
    return geometry(node, 16, 8)


class GeometryTest(unittest.TestCase):
    def test_distinct_directions(self):
        base = matrix(3, 5, 17)
        self.assertEqual(base["array_macs"], 255)
        self.assertEqual(base["ws_ia_rows"], 6)
        self.assertEqual(base["is_ia_rows"], 10)
        for rows, direction in ((6, "ws"), (10, "is")):
            item = deepcopy(base)
            observe_geometry(item, 16, rows)
            self.assertEqual(item["dataflow_geometry"], direction)
            self.assertEqual(item["observed_padded_macs"], rows * 256)
        with self.assertRaises(ValueError):
            observe_geometry(deepcopy(base), 16, 5)

    def test_equal_counts_are_ambiguous(self):
        item = matrix(32, 64, 33)
        observe_geometry(item, 16, 384)
        self.assertEqual(item["dataflow_geometry"], "ambiguous")
        self.assertEqual(item["dataflow_geometry_candidates"], ["ws", "is"])
        self.assertEqual(item["observed_padded_macs"], 98304)

    def test_single_row_fc(self):
        item = matrix(1, 64, 784)
        self.assertEqual(item["ws_ia_rows"], 196)
        self.assertEqual(item["is_ia_rows"], 3136)
        observe_geometry(item, 16, 3136)
        self.assertEqual(item["spatial_occupancy"], 1 / 16)
        self.assertEqual(item["array_macs"], 50176)

    def test_unmeasured_direction(self):
        item = matrix(3, 5, 17)
        observe_geometry(item, 16, None)
        self.assertEqual(item["dataflow_geometry"], "unmeasured")
        self.assertIsNone(item["observed_padded_macs"])
        self.assertIsNone(item["spatial_occupancy"])


if __name__ == "__main__":
    unittest.main()
