import csv
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "7_top_paths.tcl"


class TopPathsTest(unittest.TestCase):
    def run_report(self, count):
        with tempfile.TemporaryDirectory() as directory:
            harness = r'''
set PROJ_TEMP $::env(TEST_DIR)
set DESIGN_TOP sample
set PROJ_PATH $::env(TEST_DIR)
set candidates {}
for {set i 0} {$i < $::env(TEST_COUNT)} {incr i} {lappend candidates $i}
proc get_timing_paths {args} {
    if {[lsearch -exact $args -greater] >= 0} {error "unexpected delay filter"}
    return $::candidates
}
proc sizeof_collection {objects} {return [llength $objects]}
proc index_collection {objects index} {return [lindex $objects $index]}
proc get_attribute {objects attr} {
    set result {}
    foreach item $objects {
        switch -- $attr {
            cell_delay {lappend result [expr {double($item)}]}
            net_delay {lappend result 0.5}
            endpoint {lappend result "end$item"}
            startpoint {lappend result "start$item"}
            path_group {lappend result group}
            slack {lappend result 0.25}
            logic_depth {lappend result 3}
            points {return {}}
            default {error "unexpected attribute $attr"}
        }
    }
    return $result
}
proc get_object_name {object} {return $object}
proc foreach_in_collection {var collection body} {
    uplevel 1 [list foreach $var $collection $body]
}
proc report_timing {args} {}
proc getenv_default {name fallback} {return 1}
file mkdir [file join $PROJ_PATH scripts]
set fd [open [file join $PROJ_PATH scripts 8_endpoint_paths.tcl] w]
puts $fd {set ::extended_ran 1}
close $fd
source $::env(TEST_SCRIPT)
if {![info exists ::extended_ran]} {error "extended report was not invoked"}
'''
            env = dict(os.environ, TEST_DIR=directory, TEST_COUNT=str(count), TEST_SCRIPT=str(SCRIPT))
            harness_path = Path(directory) / "harness.tcl"
            harness_path.write_text(harness)
            subprocess.run(["tclsh", str(harness_path)], text=True, env=env, check=True,
                           capture_output=True)
            with open(Path(directory) / "sample_top100_delay.csv", newline="") as file:
                return list(csv.DictReader(file))

    def test_ranks_candidates_without_delay_filter(self):
        rows = self.run_report(120)
        self.assertEqual(len(rows), 100)
        self.assertEqual(rows[0]["endpoint"], "end119")
        self.assertEqual(rows[-1]["endpoint"], "end20")
        self.assertEqual(rows[0]["slack_ns"], "0.25")

    def test_no_paths_still_runs_extended_report(self):
        self.assertEqual(self.run_report(0), [])


if __name__ == "__main__":
    unittest.main()
