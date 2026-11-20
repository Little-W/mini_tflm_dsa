"""检查 ASIC 分模块综合所使用的公共模块和存储封装源文件。"""
import importlib.util
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("partition_synthesis", ROOT / "scripts/asic/partition_synthesis.py")
PARTITIONS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PARTITIONS)


class PartitionSourceTests(unittest.TestCase):
    def test_parameterized_storage_modules_have_source_files(self):
        sources = PARTITIONS.rtl_sources(ROOT)
        modules = {}
        for path in sources:
            for module in re.findall(r"\bmodule\s+(\w+)", path.read_text()):
                modules[module] = path
        expected = {
            "regfile_p_data_width513_p_depth512": "rtl/common/regfile.v",
            "smic40_sram_1r1w_DATA_WIDTH513_DEPTH512": "asic/rtl/smic40_sram_1r1w.sv",
            "requant_group_buffer_p_lanes16_p_rows512": "rtl/npu/writeback/requant_group_buffer.sv",
        }
        for design, source in expected.items():
            matched = [name for name in modules if design == name or design.startswith(name + "_")]
            self.assertTrue(matched, design)
            self.assertEqual(modules[max(matched, key=len)], ROOT / source)

    def test_common_port_wrappers_are_in_source_inventory(self):
        sources = {str(path.relative_to(ROOT)) for path in PARTITIONS.rtl_sources(ROOT)}
        self.assertIn("rtl/common/pseudo_dual_port_ram.v", sources)
        self.assertIn("rtl/common/single_port_ram.v", sources)
        self.assertIn("rtl/common/add_equal.sv", sources)


if __name__ == "__main__":
    unittest.main()
