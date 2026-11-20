#!/usr/bin/env python3
"""核对共享量化的资源记录和不支持的参数表达式处理。"""
from pathlib import Path
import tempfile
import unittest

from storage_vector_profile import resolve_vector_configuration, resolve_cache_configuration


class StorageVectorProfileChecks(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.top = self.root / "rtl/npu/top/npu_top.sv"
        self.engine = self.root / "rtl/npu/conv/vector_engine.sv"
        self.top.parent.mkdir(parents=True)
        self.engine.parent.mkdir(parents=True)
        self.top.write_text('''module npu_top #(
            parameter int SIZE = 16,
            parameter int VECTOR_PE_COUNT = 16,
            parameter int BUS_WIDTH = 64,
            parameter int WINDOW_LANES = VECTOR_PE_COUNT >= 16 ? 16 : BUS_WIDTH / 8,
            parameter int CONV_LINE_BYTES = 128,
            parameter int CONV_CACHE_WAYS = 2,
            parameter int CONV_CACHE_SETS = IM2COL_CACHE_BYTES / (CONV_CACHE_WAYS * CONV_LINE_BYTES),
            parameter int IM2COL_CACHE_BYTES = 4096
        ) ();
        localparam int REQUANT_COMPUTE_LANES =
            SHARED_RAM_ENABLED && SHARED_PHYSICAL_BANKS < 8 && SIZE > 2 && (SIZE % 2) == 0 ? 2 : SIZE;
        localparam bit DW_SHARED_QUANT_ENABLE = REQUANT_COMPUTE_LANES == SIZE;
        vector_engine #(.SHARED_QUANT_ENABLE(DW_SHARED_QUANT_ENABLE)) u_engine();
        endmodule
        ''')
        self.engine.write_text('''module vector_engine #(
            parameter int TILE = 16,
            parameter bit SHARED_QUANT_ENABLE = 1'b0,
            parameter int QUANT_LANES = SHARED_QUANT_ENABLE ? TILE : 1,
            parameter int WINDOW_LANES = 4
        ) (); endmodule
        ''')

    def resolve(self, banks=8, pe=16):
        return resolve_vector_configuration(self.root, pe_count=pe, bank_count=banks)

    def test_shared_matrix_quantization(self):
        for banks in (8, 9):
            for pe in (8, 16):
                with self.subTest(banks=banks, pe=pe):
                    row = self.resolve(banks, pe)
                    self.assertEqual(row["quantization_lanes"], 16)
                    self.assertEqual(row["shared_quant_enable"], 1)
                    self.assertEqual(row["window_lanes"], pe)

    def test_scalar_fallback(self):
        for banks in (6, 7):
            row = self.resolve(banks)
            self.assertEqual(row["quantization_lanes"], 1)
            self.assertEqual(row["shared_quant_enable"], 0)

    def test_missing_shared_connection_is_rejected(self):
        self.top.write_text(self.top.read_text().replace('.SHARED_QUANT_ENABLE(DW_SHARED_QUANT_ENABLE)', ''))
        with self.assertRaises(ValueError):
            self.resolve()

    def test_unknown_quantization_expression_is_rejected(self):
        self.engine.write_text(self.engine.read_text().replace('SHARED_QUANT_ENABLE ? TILE : 1', 'USER_SELECTED_LANES'))
        with self.assertRaises(ValueError):
            self.resolve()

    def test_unknown_selection_condition_is_rejected(self):
        self.top.write_text(self.top.read_text().replace('REQUANT_COMPUTE_LANES == SIZE', 'USER_SELECTED_MODE'))
        with self.assertRaises(ValueError):
            self.resolve()

    def test_cache_capacity_uses_production_geometry(self):
        self.assertEqual(resolve_cache_configuration(self.root, 4096),
                         dict(cache_line_bytes=128, cache_ways=2, cache_sets=16))
        self.assertEqual(resolve_cache_configuration(self.root, 8192)["cache_sets"], 32)

    def test_inconsistent_cache_set_formula_is_rejected(self):
        self.top.write_text(self.top.read_text().replace(
            'IM2COL_CACHE_BYTES / (CONV_CACHE_WAYS * CONV_LINE_BYTES)', 'IM2COL_CACHE_BYTES / 32'))
        with self.assertRaises(ValueError):
            resolve_cache_configuration(self.root, 4096)


if __name__ == "__main__":
    unittest.main()
