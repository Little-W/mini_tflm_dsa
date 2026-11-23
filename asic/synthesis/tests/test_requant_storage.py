import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_requant_storage.tcl"


class RequantStorageTest(unittest.TestCase):
    def run_check(self, storage_reference):
        with tempfile.TemporaryDirectory() as directory:
            harness = r'''
set parent u_vec/g_serial_arithmetic_u_group_buffer
set helper $parent/add_117
set storage $parent/g_bank/u_storage
array set refs [list $parent requant_group_buffer $helper npu_top_requant_group_buffer_add_117 $storage $::env(STORAGE_REF)]
proc get_cells {args} {
    if {[lsearch -exact $args -filter] >= 0} {return [list $::helper $::parent]}
    return [list $::parent $::helper $::storage]
}
proc foreach_in_collection {var collection body} {
    uplevel 1 [list foreach $var $collection $body]
}
proc get_object_name {object} {return $object}
proc get_attribute {object attr} {return $::refs($object)}
source $::env(TEST_SCRIPT)
set status [catch {check_requant_storage $::env(TEST_REPORT)} result]
puts "status=$status result=$result"
'''
            path = Path(directory) / "test.tcl"
            path.write_text(harness)
            env = dict(os.environ, TEST_SCRIPT=str(SCRIPT),
                       TEST_REPORT=str(Path(directory) / "report.tsv"),
                       STORAGE_REF=storage_reference)
            result = subprocess.run(["tclsh", str(path)], text=True, env=env,
                                    check=True, capture_output=True)
            return result.stdout, (Path(directory) / "report.tsv").read_text()

    def test_mapped_helper_is_not_a_second_buffer(self):
        result, report = self.run_check("RAMTP1024X16")
        self.assertIn("status=0 result=1", result)
        self.assertEqual(len(report.splitlines()), 2)
        self.assertIn("\t1\t16384\t0", report)

    def test_missing_macro_still_fails(self):
        result, report = self.run_check("regfile")
        self.assertIn("status=1", result)
        self.assertIn("SRAM macros=0, regfile instances=1", result)
        self.assertEqual(len(report.splitlines()), 2)


if __name__ == "__main__":
    unittest.main()
