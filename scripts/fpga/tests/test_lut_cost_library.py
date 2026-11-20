#!/usr/bin/env python3
"""检查面积成本参数及每个原语引脚延迟的保留情况。"""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from remap_fpga_luts import physical_cost_library


class LibraryTest(unittest.TestCase):
    def test_pin_delays_and_default_library(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / 'native.lut', Path(directory) / 'cost.lut'
            rows = [f'{width} {width * 2} ' + ' '.join(str(100 + pin * 7) for pin in range(width))
                    for width in range(1, 9)]
            source.write_text('\n'.join(rows) + '\n')
            for maximum in (6, 8):
                for cost in (1, 0.75, 0.5):
                    result = physical_cost_library(source, output, maximum, cost)
                    actual = [line.split() for line in output.read_text().splitlines()]
                    self.assertEqual(len(actual), maximum)
                    for width, fields in enumerate(actual, 1):
                        self.assertEqual(fields[2:], rows[width - 1].split()[2:])
                        self.assertEqual(float(fields[1]), cost if width <= 5 else 1 if width == 6 else 2 ** (width - 6))
                    self.assertTrue(result['pin_delays_preserved'])
            physical_cost_library(source, output, 8)
            default = output.read_bytes()
            physical_cost_library(source, output, 8, 1.0)
            self.assertEqual(default, output.read_bytes())

    def test_invalid_costs_and_missing_width(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / 'native.lut', Path(directory) / 'cost.lut'
            source.write_text('1 1 100\n')
            for cost in (0, -0.5, 1.01, float('nan'), float('inf')):
                with self.subTest(cost=cost), self.assertRaises(ValueError):
                    physical_cost_library(source, output, 8, cost)
            with self.assertRaises(ValueError):
                physical_cost_library(source, output, 8)


if __name__ == '__main__':
    unittest.main()
