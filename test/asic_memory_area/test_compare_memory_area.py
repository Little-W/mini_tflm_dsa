#!/usr/bin/env python3
"""验证 DC 比较入口的输入冻结、任务调度、报告解析与缺失依赖处理。"""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("compare_memory_area", ROOT / "scripts/asic/compare_memory_area.py")
COMPARE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(COMPARE)


def mock_metrics(folder, index=0):
    """数值仅供解析器测试；临时目录由测试结束时删除。"""
    values = {
        "whole": (1000 + index * 20, 600 + index * 20, 400, 101, 2, 0, 4096),
        "kernel": (100, 100, 0, 3, 0, 0, 0),
        "bias": (220, 20, 200, 3, 1, 0, 2048),
        "requant": (300, 100, 200, 12, 1, 0, 2048),
        "requant_group": (230, 30, 200, 5, 1, 0, 2048),
        "product_amount": (40, 40, 0, 4, 0, 0, 0),
    }
    lines = ["scope\tmetric\tvalue"]
    for scope, numbers in values.items():
        lines.extend(f"{scope}\t{field}\t{value}" for field, value in zip(COMPARE.AREA_FIELDS, numbers))
    lines += [f"timing\tsetup_slack_ns\t{0.05 + index * 0.001}", "timing\thold_slack_ns\t0.01",
              f"timing\tclock_period_ns\t{1000 / 150}"]
    (folder / "memory_metrics.tsv").write_text("\n".join(lines) + "\n")
    (folder / "npu_top_area.rpt").write_text(f"Total cell area: {values['whole'][0]:.4f}\n")


def mock_outputs(folder, index=0):
    mock_metrics(folder, index)
    for name in COMPARE.REQUIRED_OUTPUTS:
        path = folder / name
        if not path.exists():
            path.write_text("MOCK_DC_OUTPUT_FOR_UNIT_TEST\n")


class CompareMemoryAreaTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="dc_memory_test_")
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)

    def arguments(self):
        current, reference = self.folder / "current", self.folder / "reference"
        for source, value in ((current, 1), (reference, 0)):
            (source / "rtl").mkdir(parents=True)
            (source / "include").mkdir()
            (source / "asic/rtl").mkdir(parents=True)
            (source / "asic/synthesis/filelists").mkdir(parents=True)
            (source / "rtl/npu_top.sv").write_text(f"module npu_top (input clk, output q); assign q = 1'b{value}; endmodule\n")
            (source / "include/size.vh").write_text("`define SIZE 16\n")
            (source / "asic/rtl/smic40_sram_1r1w.sv").write_text("module smic40_sram_1r1w(input clk); endmodule\n")
            (source / "asic/synthesis/filelists/npu_top.f").write_text("+incdir+../../include\n../../rtl/npu_top.sv\n")
        for name in ("scripts", "constraints"):
            shutil.copytree(ROOT / "asic/synthesis" / name, current / "asic/synthesis" / name)
        libraries = self.folder / "libraries"
        libraries.mkdir()
        for name in ("standard.db", *COMPARE.MEMORY_DATABASES):
            (libraries / name).write_text("MOCK_LIBRARY_FOR_ORCHESTRATION_TEST\n")
        return ["--source-root", str(current), "--reference-root", str(reference),
                "--out", str(self.folder / "results"), "--std-db", str(libraries / "standard.db"),
                "--libs", str(libraries)]

    def run_synthesis_mock(self, arguments, callback):
        native_run = subprocess.run
        dispatched = []

        def run(command, **kwargs):
            if command[0] != "/test/dc_shell":
                return native_run(command, **kwargs)
            if command[1:] == ["-version"]:
                return subprocess.CompletedProcess(command, 0, "MOCK_DC_FOR_UNIT_TEST\n", "")
            folder = Path(kwargs["cwd"])
            report = json.loads((folder.parent / "comparison.json").read_text())
            self.assertEqual(report["status"], "running")
            self.assertEqual(report["active_case"], folder.name)
            self.assertTrue(report["dc_executed"])
            mock_outputs(folder, len(dispatched))
            dispatched.append(folder.name)
            code = callback(folder, len(dispatched) - 1)
            kwargs["stdout"].write("MEMORY_AREA_COMPARISON_COMPLETE\n" if code == 0 else "Error: mock synthesis failure\n")
            return subprocess.CompletedProcess(command, code)

        with mock.patch.object(COMPARE.shutil, "which", return_value="/test/dc_shell"), \
                mock.patch.object(COMPARE.subprocess, "run", side_effect=run), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            status = COMPARE.main(arguments)
        return status, dispatched

    def test_complete_report(self):
        mock_metrics(self.folder)
        report = COMPARE.parse_reports(self.folder)
        self.assertEqual(report["whole"]["total_cell_area"], 1000)
        self.assertEqual(report["whole"]["macro_capacity_bits"], 4096)
        self.assertTrue(report["timing"]["setup_met"])
        self.assertTrue(report["timing"]["hold_met"])

    def test_reject_incomplete_or_inconsistent_reports(self):
        mutations = {
            "missing_scope": lambda text: "\n".join(line for line in text.splitlines() if not line.startswith("kernel\t")),
            "nonfinite": lambda text: text.replace("whole\ttotal_cell_area\t1000", "whole\ttotal_cell_area\tnan"),
            "inconsistent_total": lambda text: text.replace("whole\tstandard_cell_area\t600", "whole\tstandard_cell_area\t900"),
            "fractional_count": lambda text: text.replace("whole\tleaf_count\t101", "whole\tleaf_count\t101.5"),
            "wrong_capacity": lambda text: text.replace("whole\tmacro_capacity_bits\t4096", "whole\tmacro_capacity_bits\t2048"),
            "wrong_clock": lambda text: text.replace(str(1000 / 150), "20.0"),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                mock_metrics(self.folder)
                path = self.folder / "memory_metrics.tsv"
                path.write_text(mutate(path.read_text()))
                with self.assertRaises(RuntimeError):
                    COMPARE.parse_reports(self.folder)
        mock_metrics(self.folder)
        (self.folder / "npu_top_area.rpt").write_text("Total cell area: 4000\n")
        with self.assertRaises(RuntimeError):
            COMPARE.parse_reports(self.folder)

    def test_negative_timing_is_a_measured_result(self):
        mock_metrics(self.folder)
        path = self.folder / "memory_metrics.tsv"
        path.write_text(path.read_text().replace("setup_slack_ns\t0.05", "setup_slack_ns\t-0.25"))
        report = COMPARE.parse_reports(self.folder)
        self.assertFalse(report["timing"]["setup_met"])
        self.assertTrue(report["timing"]["hold_met"])

    @unittest.skipUnless(shutil.which("tclsh"), "tclsh is required for the Tcl collection test")
    def test_tcl_leaf_accounting_and_hierarchy(self):
        setup = r'''
set hierarchy {top/u_kernel top/u_kernel/child top/u_bias top/u_requant top/u_requant/u_full top/u_requant/u_group top/u_requant/bank0.u_product_amount top/u_requant/bank1.u_product_amount}
set leaves {top/u_kernel/a top/u_kernel/child/b top/u_bias/ram top/u_bias/mux top/u_requant/bank0.u_product_amount/a top/u_requant/bank1.u_product_amount/b top/u_requant/u_group/ram top/u_requant/u_group/control}
array set refs {
    top/u_kernel kernel_loader_buffer_48
    top/u_kernel/child kernel_loader_buffer_regfile
    top/u_bias bias_loader_buffer_256
    top/u_requant vec_requant
    top/u_requant/u_full vec_requant_full
    top/u_requant/u_group requant_group_buffer
    top/u_requant/bank0.u_product_amount regfile_128
    top/u_requant/bank1.u_product_amount regfile_128
    top/u_kernel/a DFF
    top/u_kernel/child/b DFF
    top/u_bias/ram RAMTP128X16
    top/u_bias/mux MUX
    top/u_requant/bank0.u_product_amount/a DFF
    top/u_requant/bank1.u_product_amount/b DFF
    top/u_requant/u_group/ram RAMTP1024X16
    top/u_requant/u_group/control MUX
}
array set areas {DFF 10 MUX 5 RAMTP128X16 100 RAMTP1024X16 500}
proc get_cells {args} {
    if {[string match *true* [lindex $args end]]} {return $::hierarchy}
    return $::leaves
}
proc get_object_name {object} {return $object}
proc sizeof_collection {objects} {return [llength $objects]}
proc foreach_in_collection {variable objects body} {uplevel 1 [list foreach $variable $objects $body]}
proc get_lib_cells {args} {return lib/[file tail [lindex $args end]]}
proc get_attribute {object attribute} {
    switch -- $attribute {
        ref_name {return $::refs($object)}
        area {return $::areas([file tail $object])}
        slack {
            switch -- $object {
                setup_late {return -0.25}
                hold_late {return -0.01}
                default {return 0.5}
            }
        }
    }
    error "Unexpected attribute $attribute"
}
proc get_timing_paths {args} {
    if {[lindex $args 1] eq "max"} {return {setup_early setup_late setup_other}}
    return {hold_early hold_other hold_late}
}
proc index_collection {args} {error "Timing paths must be traversed with foreach_in_collection"}
foreach command {report_qor report_area report_design report_reference report_constraints report_timing} {
    proc $command {args} {}
}
set DESIGN_TOP npu_top
set TARGET_FREQ_MHZ 150
set COMPILE_MODE ultra
set DESIGN_PARAMETERS SIZE=16
set CLK_PERIOD_NS [expr {1000.0 / 150.0}]
'''
        script = self.folder / "measure_mock.tcl"
        script.write_text("set PROJ_TEMP " + COMPARE.tcl_string(self.folder) + "\n" + setup + COMPARE.MEASURE_TCL)
        result = subprocess.run(["tclsh", str(script)], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        (self.folder / "npu_top_area.rpt").write_text("Total cell area: 650.0\n")
        report = COMPARE.parse_reports(self.folder)
        self.assertEqual(report["whole"]["total_cell_area"], 650)
        self.assertEqual(report["whole"]["macro_area"], 600)
        self.assertEqual(report["whole"]["standard_cell_area"], 50)
        self.assertEqual(report["kernel"]["total_cell_area"], 20)
        self.assertEqual(report["bias"]["total_cell_area"], 105)
        self.assertEqual(report["requant"]["total_cell_area"], 525)
        self.assertEqual(report["requant_group"]["total_cell_area"], 505)
        self.assertEqual(report["product_amount"]["total_cell_area"], 20)
        self.assertEqual(report["timing"]["setup_slack_ns"], -0.25)
        self.assertEqual(report["timing"]["hold_slack_ns"], -0.01)

    def test_four_case_dispatch_and_snapshot(self):
        arguments = self.arguments()

        def inspect_case(folder, index):
            script = (folder / "run.tcl").read_text()
            self.assertIn('set ::env(DESIGN_TARGET_FREQ_MHZ) "150"', script)
            self.assertIn("source -e -v", script)
            self.assertNotIn("6_timing_report.tcl", script)
            return 0

        status, dispatched = self.run_synthesis_mock(arguments, inspect_case)
        self.assertEqual(status, 0)
        self.assertEqual(dispatched, ["reference_ia0", "reference_ia1", "current_ia0", "current_ia1"])
        report = json.loads((self.folder / "results/comparison.json").read_text())
        self.assertEqual(report["status"], "measured")
        self.assertEqual(len(report["differences"]), 2)
        for case in report["cases"]:
            self.assertEqual(case["parameters"]["IA_COMPACT_ENABLE"], int(case["name"][-1]))
            self.assertEqual(case["parameters"]["SIZE"], 16)
            self.assertEqual(case["parameters"]["SHARED_BANK_COUNT"], 7)
            COMPARE.require_unchanged(Path(case["output"]), case["snapshot_sha256"])
            expected = "1'b0" if case["name"].startswith("reference") else "1'b1"
            self.assertIn(expected, (Path(case["output"]) / "snapshot/rtl/npu_top.sv").read_text())

    def assert_synthesis_failure(self, fail_index):
        arguments = self.arguments()
        status, dispatched = self.run_synthesis_mock(arguments, lambda folder, index: int(index == fail_index))
        self.assertEqual(status, 1)
        self.assertEqual(len(dispatched), fail_index + 1)
        report = json.loads((self.folder / "results/comparison.json").read_text())
        self.assertEqual(report["status"], "failed")
        self.assertTrue(report["dc_executed"])
        self.assertEqual(report["failed_case"], dispatched[-1])
        self.assertEqual(report["cases"][fail_index]["status"], "failed")
        self.assertTrue(report["cases"][fail_index]["dc_executed"])
        if fail_index:
            self.assertEqual(report["cases"][0]["status"], "measured")

    def test_first_case_failure_is_recorded(self):
        self.assert_synthesis_failure(0)

    def test_second_case_failure_preserves_first_result(self):
        self.assert_synthesis_failure(1)

    def test_missing_netlist_is_rejected(self):
        arguments = self.arguments()

        def remove_output(folder, index):
            (folder / "npu_top_syn.vg").unlink()
            return 0

        status, dispatched = self.run_synthesis_mock(arguments, remove_output)
        self.assertEqual(status, 1)
        self.assertEqual(len(dispatched), 1)
        report = json.loads((self.folder / "results/comparison.json").read_text())
        self.assertEqual(report["status"], "failed")
        self.assertIn("npu_top_syn.vg", report["failure_reason"])

    def test_empty_timing_report_is_rejected(self):
        arguments = self.arguments()

        def empty_output(folder, index):
            (folder / "npu_top_hold_timing.rpt").write_text("")
            return 0

        status, dispatched = self.run_synthesis_mock(arguments, empty_output)
        self.assertEqual(status, 1)
        self.assertEqual(len(dispatched), 1)
        report = json.loads((self.folder / "results/comparison.json").read_text())
        self.assertIn("npu_top_hold_timing.rpt", report["failure_reason"])

    def test_different_source_snapshots_between_modes_are_rejected(self):
        arguments = self.arguments() + ["--prepare-only"]
        original = COMPARE.copy_snapshot
        changed = False

        def copy_then_change(source, destination):
            nonlocal changed
            result = original(source, destination)
            if source.name == "current" and not changed:
                path = source / "rtl/npu_top.sv"
                path.write_text(path.read_text() + "\n// 新源码内容\n")
                changed = True
            return result

        with mock.patch.object(COMPARE, "copy_snapshot", side_effect=copy_then_change), \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(COMPARE.main(arguments), 1)
        report = json.loads((self.folder / "results/comparison.json").read_text())
        self.assertEqual(report["status"], "failed")
        self.assertFalse(report["dc_executed"])
        self.assertIn("different source snapshots", report["failure_reason"])

    def test_prepare_has_no_area_or_timing_result(self):
        arguments = self.arguments() + ["--prepare-only"]
        with mock.patch.object(COMPARE.shutil, "which", return_value=None), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(COMPARE.main(arguments), 0)
        report = json.loads((self.folder / "results/comparison.json").read_text())
        self.assertFalse(report["dc_executed"])
        self.assertNotIn("differences", report)
        self.assertTrue(all("measurements" not in case for case in report["cases"]))

    def test_missing_dc_is_rejected(self):
        arguments = self.arguments()
        with mock.patch.object(COMPARE.shutil, "which", return_value=None), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                COMPARE.main(arguments)
        self.assertEqual(error.exception.code, 2)
        self.assertFalse((self.folder / "results").exists())

    def test_missing_library_is_rejected(self):
        arguments = self.arguments()
        (self.folder / "libraries" / COMPARE.MEMORY_DATABASES[0]).unlink()
        with mock.patch.object(COMPARE.shutil, "which", return_value="/test/dc_shell"), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(COMPARE.main(arguments), 1)
        self.assertFalse((self.folder / "results").exists())

    def test_modified_snapshot_is_rejected(self):
        path = self.folder / "source.sv"
        path.write_text("module original; endmodule\n")
        hashes = {path.name: COMPARE.digest(path)}
        path.write_text("module changed; endmodule\n")
        with self.assertRaises(RuntimeError):
            COMPARE.require_unchanged(self.folder, hashes)


if __name__ == "__main__":
    unittest.main()
