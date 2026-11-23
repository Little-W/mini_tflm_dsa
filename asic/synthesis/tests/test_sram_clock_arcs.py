import csv
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "9_sram_clock_arcs.tcl"


class SramClockArcsTest(unittest.TestCase):
    def test_pin_connectivity_and_unavailable_values(self):
        with tempfile.TemporaryDirectory() as directory:
            harness = r'''
set PROJ_TEMP $::env(TEST_DIR)
set DESIGN_TOP top
proc foreach_in_collection {var collection body} {uplevel 1 [list foreach $var $collection $body]}
proc get_libs {args} {return {}}
proc get_cells {args} {return {u_ram u_unconnected}}
proc get_object_name {object} {return $object}
proc sizeof_collection {objects} {return [llength $objects]}
proc get_pins {args} {return [lindex $args end]}
proc get_nets {args} {
    set pin [lindex $args end]
    if {[string match u_unconnected/* $pin]} {return {}}
    if {[string match */COLLDISN $pin]} {return tie_net}
    return clock_net
}
proc get_attribute {args} {
    if {[lindex $args 0] eq "-quiet"} {set args [lrange $args 1 end]}
    lassign $args object attribute
    switch -- $attribute {
        ref_name {return RAMTP128X16}
        clocks {
            if {[string match u_ram/CLK* $object]} {return core_clk}
            return {}
        }
        case_value {
            if {$object eq "u_ram/COLLDISN"} {return 1}
            return {}
        }
        default {error "unexpected attribute $attribute"}
    }
}
source $::env(TEST_SCRIPT)
'''
            path = Path(directory) / "test.tcl"
            path.write_text(harness)
            subprocess.run(["tclsh", str(path)], check=True, capture_output=True,
                           text=True, env=dict(os.environ, TEST_DIR=directory, TEST_SCRIPT=str(SCRIPT)))
            with open(Path(directory) / "top_sram_clock_pins.tsv", newline="") as file:
                rows = {(row["instance"], row["pin"]): row for row in csv.DictReader(file, delimiter="\t")}
            self.assertEqual(rows[("u_ram", "CLKA")]["clocks"], "core_clk")
            self.assertEqual(rows[("u_ram", "CLKA")]["case_value"], "NA")
            self.assertEqual(rows[("u_ram", "COLLDISN")]["case_value"], "1")
            self.assertEqual(rows[("u_unconnected", "CLKA")]["nets"], "NA")
            text = (Path(directory) / "top_sram_clock_diagnostics.rpt").read_text()
            self.assertIn("u_ram: CLKA/CLKB same net = 1", text)
            self.assertIn("u_unconnected: CLKA/CLKB same net = NA", text)


if __name__ == "__main__":
    unittest.main()
