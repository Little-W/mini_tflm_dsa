#!/usr/bin/env python3
"""检查只读数组识别、初始化完整性以及容量预算的计数边界。"""
from __future__ import annotations

import copy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.capacity import elaboration, model


def variable(name, access):
    return dict(type="VARREF", name=name, varp=name, access=access)


def constant(value, bits=18):
    return dict(type="CONST", name=f"{bits}'h{value:x}")


def array_element(address, access="WR"):
    return dict(type="ARRAYSEL", fromp=[variable("avg_reciprocal", access)],
                bitp=[constant(address)])


def clocked(statement):
    return dict(type="ALWAYS", keyword="always_ff",
                sentreep=[dict(type="SENTREE", sensesp=[dict(type="SENITEM", edgeType="POS",
                    sensp=[variable("clk", "RD")])])], stmtsp=[statement])


def syntax_tree(mode="fpga", words=4, word_bits=18):
    """构造与 Verilator 展开格式相同的最小存储层次。"""
    statements = [dict(type="VAR", name=name, addr=name, dtypep=dtype, lifetime="VSTATICI")
                  for name, dtype in (("clk", "bit"), ("address", "word"),
                                      ("avg_reciprocal", "array"), ("read_data", "word"))]
    for address in range(words):
        assignment = dict(type="ASSIGN" if mode == "fpga" else "ASSIGNW",
                          lhsp=[array_element(address)], rhsp=[constant(address)])
        statements.append(dict(type="INITIAL", stmtsp=[assignment]) if mode == "fpga" else
                          dict(type="ALWAYS", keyword="cont_assign", sentreep=[], stmtsp=[assignment]))
    statements.append(clocked(dict(type="ASSIGNDLY", lhsp=[variable("read_data", "WR")],
        rhsp=[dict(type="ARRAYSEL", fromp=[variable("avg_reciprocal", "RD")],
                   bitp=[variable("address", "RD")])])))
    return dict(type="NETLIST", modulesp=[
        dict(type="MODULE", name="npu_axil_top", addr="top", stmtsp=[
            dict(type="CELL", name="engine", modp="engine")]),
        dict(type="MODULE", name="vector_engine", origName="vector_engine", addr="engine",
             stmtsp=statements)], dtypep=[
        dict(type="BASICDTYPE", addr="bit", range="0:0"),
        dict(type="BASICDTYPE", addr="word", range=f"{word_bits-1}:0"),
        dict(type="UNPACKARRAYDTYPE", addr="array", refDTypep="word", declRange=f"[0:{words-1}]")])


class ReadOnlyInventoryTests(unittest.TestCase):
    def test_both_constant_encodings_count_once(self):
        for mode in ("fpga", "asic"):
            with self.subTest(mode=mode):
                result = elaboration.inventory(syntax_tree(mode))
                self.assertEqual(result["buffer_arrays_bits"], {"vector_pool_reciprocal_rom": 72})
                self.assertEqual(result["read_only_arrays_bits"], result["buffer_arrays_bits"])
                self.assertEqual(result["total_bits"], 72+18)
                self.assertEqual(len(result["sequential_declarations"]), 1)
                self.assertEqual(result["read_only_declarations"][0]["initialized_words"], 4)
                self.assertEqual(result["read_only_declarations"][0]["read_latency_cycles"], 1)

    def test_dimensions_follow_elaborated_types(self):
        for words, bits in ((2, 10), (50, 15), (256, 17), (257, 18), (258, 18)):
            with self.subTest(words=words, bits=bits):
                result = elaboration.inventory(syntax_tree(words=words, word_bits=bits))
                self.assertEqual(result["read_only_arrays_bits"]["vector_pool_reciprocal_rom"], words*bits)
                self.assertEqual(result["total_bits"], (words+1)*bits)

    def test_each_instance_has_its_own_storage(self):
        tree = syntax_tree()
        tree["modulesp"][0]["stmtsp"].append(dict(type="CELL", name="engine_second", modp="engine"))
        result = elaboration.inventory(tree)
        self.assertEqual(result["read_only_arrays_bits"], {"vector_pool_reciprocal_rom": 144})
        self.assertEqual(result["declaration_counts"], {"vector_pool_reciprocal_rom": 2})
        self.assertEqual(result["total_bits"], 180)
        self.assertEqual(len({item["path"] for item in result["read_only_declarations"]}), 2)

    def test_initial_assignment_without_schema_is_not_a_rom(self):
        tree = syntax_tree()
        tree["modulesp"][1]["origName"] = "other_module"
        result = elaboration.inventory(tree)
        self.assertEqual(result["buffer_arrays_bits"], {})
        self.assertEqual(result["read_only_declarations"], [])
        self.assertEqual(result["total_bits"], 18)

    def test_runtime_write_is_rejected(self):
        tree = syntax_tree()
        tree["modulesp"][1]["stmtsp"].append(clocked(dict(type="ASSIGNDLY",
            lhsp=[array_element(0)], rhsp=[constant(2)])))
        with self.assertRaisesRegex(ValueError, "运行期写入"):
            elaboration.inventory(tree)

    def test_complete_initialization_is_required(self):
        tree = syntax_tree()
        del tree["modulesp"][1]["stmtsp"][4]
        with self.assertRaisesRegex(ValueError, "完整数组"):
            elaboration.inventory(tree)

    def test_duplicate_and_out_of_range_addresses_are_rejected(self):
        for address in (1, 4):
            with self.subTest(address=address):
                tree = syntax_tree()
                tree["modulesp"][1]["stmtsp"][4]["stmtsp"][0]["lhsp"] = [array_element(address)]
                with self.assertRaisesRegex(ValueError, "超出数组范围或重复"):
                    elaboration.inventory(tree)

    def test_nonconstant_and_unknown_contents_are_rejected(self):
        for value in (variable("address", "RD"), dict(type="CONST", name="18'hx")):
            with self.subTest(value=value):
                tree = syntax_tree()
                tree["modulesp"][1]["stmtsp"][4]["stmtsp"][0]["rhsp"] = [value]
                with self.assertRaisesRegex(ValueError, "常量"):
                    elaboration.inventory(tree)

    def test_conditional_and_delayed_initialization_are_rejected(self):
        for mode in ("conditional", "delayed"):
            with self.subTest(mode=mode):
                tree = syntax_tree()
                initial = tree["modulesp"][1]["stmtsp"][4]
                if mode == "conditional":
                    initial["stmtsp"] = [dict(type="IF", condp=[variable("address", "RD")],
                                              ifsp=initial["stmtsp"])]
                else:
                    initial["stmtsp"][0]["timingControlp"] = [dict(type="DELAY", lhsp=[constant(1)])]
                with self.assertRaisesRegex(ValueError, "初始化"):
                    elaboration.inventory(tree)

    def test_registered_read_is_required(self):
        tree = syntax_tree()
        tree["modulesp"][1]["stmtsp"][-1]["sentreep"] = []
        with self.assertRaisesRegex(ValueError, "同步读取"):
            elaboration.inventory(tree)

    def test_whole_element_assignment_is_required(self):
        tree = syntax_tree()
        assignment = tree["modulesp"][1]["stmtsp"][4]["stmtsp"][0]
        assignment["lhsp"] = [dict(type="SEL", fromp=assignment["lhsp"], lsbp=[constant(0)])]
        with self.assertRaisesRegex(ValueError, "完整数组元素"):
            elaboration.inventory(tree)

    def test_production_budget_includes_the_read_only_array(self):
        arrays = model.buffer_arrays_bits(4, 16, 49152, bank_bytes=8192, bank_count=7)
        self.assertEqual(arrays["vector_pool_reciprocal_rom"], 4626)
        writable = copy.deepcopy(arrays)
        del writable["vector_pool_reciprocal_rom"]
        self.assertEqual(sum(writable.values()), 953640)
        self.assertEqual(sum(arrays.values()), 958266)
        allocation = model.allocation(4, 16, 49152, 131072, bank_bytes=8192, bank_count=7)
        self.assertEqual(allocation["budget_used_bytes"], 119784)
        self.assertGreaterEqual(allocation["unused_budget_bytes"], 0)


if __name__ == "__main__":
    unittest.main()
