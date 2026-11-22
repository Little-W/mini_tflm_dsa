#!/usr/bin/env python3
"""使用 Tcl 命令模型检查多范围路径采样、查询限制与报告导出。"""
from __future__ import annotations

import csv
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/fpga/vivado_path_diagnostics.tcl"


def tcl_word(value):
    text = str(value).replace("\\", "\\\\").replace("$", "\\$").replace("[", "\\[")
    return '"' + text.replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r") + '"'


MOCK = r'''
proc record {name args} {
    set stream [open $::call_log a]
    puts $stream [join [linsert $args 0 $name] \t]
    close $stream
}
proc named_argument {arguments name {fallback ""}} {
    set index [lsearch -exact $arguments $name]
    if {$index < 0} { return $fallback }
    return [lindex $arguments [expr {$index+1}]]
}
proc native_report {name args} {
    record $name {*}$args
    set stream [open [named_argument $args -file] w]
    puts $stream "Synthetic native $name report"
    close $stream
}
proc report_utilization {args} { native_report report_utilization {*}$args }
proc report_timing_summary {args} { native_report report_timing_summary {*}$args }
proc report_high_fanout_nets {args} { native_report report_high_fanout_nets {*}$args }
proc get_cells {args} {
    set filter [named_argument $args -filter]
    if {[string first group_range_q_reg $filter] >= 0} { return {range_cell} }
    if {[string first past_active_q_reg $filter] >= 0} { return {past_cell} }
    if {[string first ch_q_reg $filter] >= 0} {
        if {$::missing_channel} { return {} }
        return {channel_cell}
    }
    if {[string first u_picorv32 $filter] >= 0} { return {cpu_cell} }
    if {[string first g_im2col.u_frontend $filter] >= 0} { return {range_cell past_cell} }
    return {}
}
proc get_timing_paths {args} {
    record get_timing_paths {*}$args
    if {[named_argument $args -nworst] != 1} { error "Endpoint diversity requires nworst=1" }
    return {fast_path slow_path}
}
proc get_property {property object} {
    switch -- $property {
        NAME { return sys_clk }
        PERIOD { return 6.667 }
        ENDPOINT_CLOCK { return system_clock }
        STARTPOINT_PIN { return ${object}_source/Q }
        ENDPOINT_PIN { return ${object}_sink/D }
        SLACK {
            if {$::bad_slack} { return NaN }
            return [expr {$object eq "slow_path" ? -0.8 : 0.15}]
        }
        LOGIC_LEVELS { return 6 }
        default { error "Unexpected property $property" }
    }
}
proc report_timing {args} {
    set path [named_argument $args -of_objects]
    return "Native report header\nSlack (VIOLATED) : -0.800ns\n  Path: $path\n"
}
'''


class PathDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="path_diagnostics_")
        self.addCleanup(self.temporary.cleanup)
        self.work = Path(self.temporary.name)
        self.output = self.work / "reports"
        self.tclsh = shutil.which("tclsh")
        self.assertIsNotNone(self.tclsh, "tclsh is required")

    def execute(self, counts="2 3 4", *, missing_channel=False, bad_slack=False):
        script = self.work / "run.tcl"
        script.write_text(
            f"set ::call_log {tcl_word(self.work / 'calls.tsv')}\n"
            f"set ::missing_channel {int(missing_channel)}\n"
            f"set ::bad_slack {int(bad_slack)}\n"
            + MOCK
            + f"\nsource {tcl_word(SCRIPT)}\n"
            + f"path_diagnostics::write {tcl_word(self.output)} {counts}\n"
        )
        return subprocess.run([self.tclsh, str(script)], text=True, capture_output=True, timeout=30)

    def rows(self, name):
        with (self.output / name).open(newline="") as stream:
            return list(csv.DictReader(stream, delimiter="\t"))

    def test_native_reports_and_query_diversity(self):
        result = self.execute()
        self.assertEqual(result.returncode, 0, result.stderr)
        for name in ("utilization.rpt", "utilization_hier.rpt", "timing_summary.rpt",
                     "high_fanout.rpt", "design_module_endpoints.tsv", "design_module_paths.rpt"):
            self.assertTrue((self.output / name).is_file(), name)
        calls = (self.work / "calls.tsv").read_text().splitlines()
        queries = [line.split("\t") for line in calls if line.startswith("get_timing_paths\t")]
        self.assertTrue(queries)
        for query in queries:
            self.assertEqual(query[query.index("-nworst") + 1], "1")
            self.assertIn("-no_report_unconstrained", query)
        self.assertTrue(any("-from\tpast_cell" in line for line in calls))
        self.assertTrue(any("-from\tchannel_cell" in line for line in calls))
        self.assertTrue(any("-to\trange_cell" in line for line in calls))
        self.assertTrue(any("-to" not in query and "-from" not in query for query in queries))
        self.assertTrue(any("report_timing_summary\t-delay_type\tmin_max" in line for line in calls))

    def test_query_limits_and_sorted_values(self):
        result = self.execute()
        self.assertEqual(result.returncode, 0, result.stderr)
        queries = self.rows("queries.tsv")
        self.assertEqual(len(queries), 8)
        for row in queries:
            self.assertEqual(row["scope_available"], "1")
            self.assertEqual(row["returned_paths"], "2")
            self.assertEqual(row["limit_reached"], "1" if row["scope"] == "global" else "0")
        endpoints = self.rows("endpoints.tsv")
        self.assertEqual(len(endpoints), 16)
        for offset in range(0, len(endpoints), 2):
            self.assertEqual([float(row["slack_ns"]) for row in endpoints[offset:offset+2]], [-0.8, 0.15])
        detail = (self.output / "global_paths.rpt").read_text()
        self.assertNotIn("Native report header", detail)
        self.assertIn("Path: slow_path", detail)

    def test_missing_scope_is_recorded(self):
        self.output.mkdir()
        stale = self.output / "im2col_channel_paths.rpt"
        stale.write_text("earlier run")
        result = self.execute(missing_channel=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = [row for row in self.rows("queries.tsv") if row["scope"] == "im2col_channel"]
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row["scope_available"] == "0" and row["returned_paths"] == "0" for row in rows))
        self.assertFalse(stale.exists())

    def test_invalid_counts_reject_before_reports(self):
        for counts in ("0 3 4", "2 -1 4", "2 3 10001", "x 3 4"):
            with self.subTest(counts=counts):
                result = self.execute(counts)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("must be an integer", result.stderr)
                self.assertFalse(self.output.exists())

    def test_nonfinite_slack_rejects_sample(self):
        result = self.execute(bad_slack=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("finite numeric", result.stderr)


if __name__ == "__main__":
    unittest.main()
