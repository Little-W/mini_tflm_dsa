"""验证 DC 量化存储检查的层次范围、宏容量统计和执行条件。"""
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "asic/synthesis/scripts/check_requant_storage.tcl"


class RequantStorageCheckTests(unittest.TestCase):
    def run_check(self, cells):
        declarations = "\n".join(
            f"dict set definitions {{{name}}} [list {{{reference}}} {int(hierarchical)}]"
            for name, reference, hierarchical in cells
        )
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "storage.rpt"
            script = f"""
set definitions [dict create]
{declarations}
proc get_cells {{args}} {{
    global definitions
    if {{[lsearch -exact $args -filter] < 0}} {{return [dict keys $definitions]}}
    set selected {{}}
    dict for {{name fields}} $definitions {{
        lassign $fields reference hierarchical
        if {{$hierarchical && [string match *requant_group_buffer* $reference]}} {{
            lappend selected $name
        }}
    }}
    return $selected
}}
proc get_object_name {{value}} {{return $value}}
proc get_attribute {{value attribute}} {{
    global definitions
    if {{$attribute ne "ref_name"}} {{error "Unexpected attribute"}}
    return [lindex [dict get $definitions $value] 0]
}}
proc sizeof_collection {{values}} {{return [llength $values]}}
proc foreach_in_collection {{variable values body}} {{
    uplevel 1 [list foreach $variable $values $body]
}}
source {{{CHECK}}}
if {{[catch {{check_requant_storage {{{output}}}}} result]}} {{
    puts stderr $result
    exit 1
}}
puts "checked=$result"
"""
            result = subprocess.run(["tclsh"], input=script, text=True, capture_output=True)
            report = output.read_text() if output.exists() else ""
            return result, report

    def test_complete_production_storage(self):
        cells = [("u_quant/u_group_buffer", "requant_group_buffer_p_lanes16_p_rows512", True)]
        cells += [(f"u_quant/u_group_buffer/g_data/g_bank[{bank}]/g_lane[{lane}]/u_sram",
                   "RAMTP128X16", False) for bank in range(4) for lane in range(33)]
        result, report = self.run_check(cells)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("u_quant/u_group_buffer\t132\t270336\t0", report)

    def test_storage_in_another_hierarchy_does_not_satisfy_check(self):
        result, report = self.run_check([
            ("u_group", "requant_group_buffer_p_lanes16", True),
            ("u_group_extra/u_sram", "RAMTP128X16", False),
        ])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("u_group\t0\t0\t0", report)

    def test_inferred_row_array_is_detected_with_partial_macro_mapping(self):
        result, report = self.run_check([
            ("u_group", "requant_group_buffer_p_rows512", True),
            ("u_group/u_rows", "regfile_p_data_width513_p_depth512", True),
            ("u_group/u_marker/u_sram", "RAMTP128X16", False),
        ])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("u_group\t1\t2048\t1", report)

    def test_parameter_and_partition_names(self):
        result, report = self.run_check([
            ("g_quant[1]/u_buffer", "PS_CACHE_requant_group_buffer_p_rows32", True),
            ("g_quant[1]/u_buffer/u_sram", "RAMTP128X16", False),
            ("g_quant[10]/u_buffer/u_sram", "RAMTP1024X16", False),
        ])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("g_quant[1]/u_buffer\t1\t2048\t0", report)

    def test_each_group_buffer_is_checked(self):
        result, report = self.run_check([
            ("first", "requant_group_buffer_p_rows32", True),
            ("first/u_sram", "RAMTP128X16", False),
            ("second", "requant_group_buffer_p_rows64", True),
        ])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("first\t1\t2048\t0", report)
        self.assertIn("second\t0\t0\t0", report)

    def test_parallel_quantization_needs_no_group_buffer(self):
        result, report = self.run_check([("u_quant", "vec_requant_full", True)])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("checked=0", result.stdout)
        self.assertEqual(len(report.splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
