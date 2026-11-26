#!/usr/bin/env python3
"""检查完整组合层次在单次映射和分批映射中的逻辑与连接。"""
import argparse
import collections
from contextlib import contextmanager
import json
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = None


@contextmanager
def output_folder(name):
    if OUTPUT is None:
        with tempfile.TemporaryDirectory(prefix="connected_hierarchy_") as temporary:
            yield Path(temporary)
    else:
        folder = OUTPUT / name
        folder.mkdir(parents=True, exist_ok=True)
        yield folder


def prove_mapped_equivalence(folder, reference, candidate, top, sequential):
    """在实际映射单元的功能模型上证明两个完整电路输出一致。"""
    for name, mapped in (("gold", reference), ("gate", candidate)):
        module = dict(mapped["modules"][top])
        module["attributes"] = {key: value for key, value in module.get("attributes", {}).items() if key != "top"}
        (folder / (name + ".json")).write_text(json.dumps({"modules": {name: module}}))
    script = folder / "equivalence.ys"
    temporal = "-seq 2 -set-init-zero -tempinduct " if sequential else ""
    script.write_text(f'read_json {folder / "gold.json"}\nread_json {folder / "gate.json"}\n'
        'read_verilog +/xilinx/cells_sim.v\n'
        'miter -equiv -flatten gold gate miter\nprep -top miter\nasync2sync\ndffunmap\n'
        f'sat {temporal}-verify -prove trigger 0 -show-inputs -show-outputs\n')
    log = folder / "equivalence.log"
    with log.open("w") as stream:
        subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                        "--worker", str(script)], stdout=stream, stderr=subprocess.STDOUT,
                       check=True, timeout=180)
    if "SUCCESS!" not in log.read_text():
        raise AssertionError("完整映射电路的 SAT 检查没有完成证明")


class HierarchyMappingTest(unittest.TestCase):
    def map_and_compare(self, folder, case, batch_size, sequential=False):
        configuration = folder / "cases.json"
        configuration.write_text(json.dumps({"connected": case}))
        results = {}
        sys.path.insert(0, str(ROOT / "test/conv_frontend/tools"))
        from measure_complete_paths import measure
        for name, batch in (("reference", None), ("batched", batch_size)):
            output = folder / name
            command = [sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                       "--out", str(output), "--cases", "connected", "--case-config", str(configuration)]
            saved_stages = None
            if batch is not None:
                with (folder / "pre_lut.log").open("w") as log:
                    subprocess.run(command + ["--through", "pre_lut"], stdout=log,
                                   stderr=subprocess.STDOUT, check=True, timeout=180)
                saved_stages = json.loads((output / "connected/stages.json").read_text())
                command += ["--resume", "--abc9-batch-size", str(batch)]
                if sequential:
                    command.append("--abc9-keep-checkpoints")
            with (folder / (name + ".log")).open("w") as log:
                completed = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT,
                                           check=False, timeout=300)
            self.assertEqual(completed.returncode, 0, (folder / (name + ".log")).read_text()[-12000:])
            if saved_stages is not None:
                stages = json.loads((output / "connected/stages.json").read_text())
                for stage, details in saved_stages.items():
                    self.assertEqual(stages[stage], details)
            mapped = json.loads((output / "connected/mapped.json").read_text())
            module = mapped["modules"][case["top"]]
            paths = measure(module)
            self.assertTrue(paths["graph_complete"])
            counts = dict(collections.Counter(cell["type"] for cell in module["cells"].values()))
            self.assertFalse(any(kind.startswith("$") for kind in counts))
            (output / "connected/complete_paths.json").write_text(json.dumps(paths, indent=2) + "\n")
            results[name] = {"mapped": mapped, "paths": paths, "cell_counts": counts}
        expected, actual = results["reference"], results["batched"]
        self.assertEqual(actual["cell_counts"], expected["cell_counts"])
        self.assertEqual(actual["paths"]["maximum_combinational_cells"],
                         expected["paths"]["maximum_combinational_cells"])
        self.assertEqual(actual["paths"]["interface_bits"], expected["paths"]["interface_bits"])
        prove_mapped_equivalence(folder, expected["mapped"], actual["mapped"], case["top"], sequential)
        batch_report_path = folder / "batched/connected/abc9_batches/summary.json"
        batches = json.loads(batch_report_path.read_text())
        self.assertTrue(batches["passed"])
        self.assertTrue(batches["all_module_interfaces_preserved"])
        worker_ids = [stage["worker_pid"] for stage in batches["stages"]]
        self.assertEqual(len(worker_ids), len(set(worker_ids)))
        self.assertEqual(sum(len(stage.get("modules", [])) for stage in batches["stages"]), batches["module_count"])
        report = {"passed": True, "top": case["top"], "mapped_logic_equivalent": True,
                  "cell_counts": actual["cell_counts"], "maximum_combinational_cells":
                      actual["paths"]["maximum_combinational_cells"],
                  "interface_bits": actual["paths"]["interface_bits"], "graph_complete": True,
                  "module_count": batches["module_count"], "batch_count": batches["batch_count"],
                  "mapping_commands": batches["identity"]["mapping_commands"],
                  "elaboration_and_pre_lut_reused": True,
                  "all_module_interfaces_preserved": True,
                  "peak_batch_worker_rss_bytes": max(stage["peak_process_tree_rss_bytes"] for stage in batches["stages"]),
                  "peak_reference_mapping_rss_bytes": json.loads(
                      (folder / "reference/connected/stages.json").read_text())["03_map_lut"]["peak_process_tree_rss_bytes"]}
        (folder / "comparison.json").write_text(json.dumps(report, indent=2) + "\n")
        return actual, batches

    def restart_from_first_batch(self, folder, reference):
        """从第一批完整检查点启动新进程，验证后续批次与完整结果。"""
        initial = folder / "batched/connected/abc9_batches"
        restarted = folder / "restarted"
        restarted.mkdir(parents=True, exist_ok=True)
        status = json.loads((initial / "progress.json").read_text())
        status["stages"] = status["stages"][:2]
        first_batch = status["stages"][-1]
        status.update(completed_modules=first_batch["modules"], checkpoint=first_batch["checkpoint"],
                      checkpoint_sha256=first_batch["output_sha256"])
        shutil.copyfile(initial / "inventory.json", restarted / "inventory.json")
        shutil.copyfile(initial / status["checkpoint"], restarted / status["checkpoint"])
        (restarted / "progress.json").write_text(json.dumps(status, indent=2) + "\n")
        mapped_json, mapped_verilog = restarted / "mapped.json", restarted / "mapped.v"
        with (restarted / "run.log").open("w") as log:
            subprocess.run([sys.executable, str(ROOT / "scripts/fpga/map_abc9_batches.py"),
                "--input", str(folder / "batched/connected/pre_lut.il"),
                "--top", "hierarchy_top", "--out", str(restarted),
                "--mapped-json", str(mapped_json), "--mapped-verilog", str(mapped_verilog),
                "--batch-size", "1", "--resume"], stdout=log, stderr=subprocess.STDOUT,
                check=True, timeout=180)
        result = json.loads((restarted / "summary.json").read_text())
        self.assertEqual(result["stages"][:2], status["stages"])
        self.assertEqual(result["module_count"], 4)
        self.assertFalse((restarted / "batch_0001.log").exists())
        self.assertTrue((restarted / "batch_0002.log").exists())
        mapped = json.loads(mapped_json.read_text())
        self.assertEqual(collections.Counter(cell["type"] for cell in mapped["modules"]["hierarchy_top"]["cells"].values()),
                         reference["cell_counts"])
        prove_mapped_equivalence(restarted, reference["mapped"], mapped, "hierarchy_top", True)
        (restarted / "comparison.json").write_text(json.dumps({
            "passed": True, "resumed_after_modules": 1, "remaining_modules_mapped": 3,
            "completed_batches_reused": True, "mapped_logic_equivalent": True}, indent=2) + "\n")

    def test_three_modules_are_counted_as_three_connected_logic_cells(self):
        with output_folder("three_stages") as folder:
            source = folder / "hierarchy.sv"
            source.write_text("""(* keep_hierarchy = "yes" *)
module combine(input logic[3:0]a,output logic y);
 assign y=(a[0]&a[1])^(a[2]|a[3]);
endmodule
module hierarchy_top(input logic clk,input logic[9:0]a,output logic y);
 logic[9:0]source_q;
 logic first,second,third;
 always_ff @(posedge clk) begin source_q<=a;y<=third;end
 combine first_stage(.a(source_q[3:0]),.y(first));
 combine second_stage(.a({source_q[6:4],first}),.y(second));
 combine third_stage(.a({source_q[9:7],second}),.y(third));
endmodule
""")
            result, batches = self.map_and_compare(folder, {
                "top": "hierarchy_top", "sources": [str(source)], "options": [],
                "configuration": "Three preserved combinational stages",
            }, 1, sequential=True)
            self.assertEqual(result["paths"]["maximum_combinational_cells"], 3)
            self.assertEqual(result["cell_counts"], {"FDRE": 11, "LUT4": 3})
            self.assertEqual(batches["batch_count"], 4)
            self.restart_from_first_batch(folder, result)
            remapped = folder / "remapped"
            with (folder / "remapped.log").open("w") as log:
                subprocess.run([sys.executable, str(ROOT / "scripts/fpga/remap_fpga_luts.py"),
                    "--source", str(folder / "reference/connected"), "--out", str(remapped)],
                    stdout=log, stderr=subprocess.STDOUT, check=True, timeout=180)
            metrics = json.loads((remapped / "metrics.json").read_text())
            self.assertTrue(metrics["paths"]["graph_complete"])
            self.assertEqual(metrics["paths"]["longest_register_path_cells"], 3)
            self.assertEqual(metrics["resources"]["logic_lut_cells"], 3)
            mapped = json.loads((remapped / "mapped.json").read_text())
            prove_mapped_equivalence(remapped, result["mapped"], mapped, "hierarchy_top", True)

    def test_production_descriptor_selection_in_complete_batches(self):
        with output_folder("descriptor_selection") as folder:
            helper = runpy.run_path(str(ROOT / "test/conv_frontend/tools/check_descriptor_selection.py"))
            rtl = ROOT / "rtl/npu/conv/conv_im2col_descriptor.sv"
            source = folder / "descriptor_selection.sv"
            current = rtl.read_text()
            source.write_text(helper["helper_modules"](current) + helper["model"]("descriptor_selection", current))
            result, batches = self.map_and_compare(folder, {
                "top": "descriptor_selection", "sources": [str(source),
                    "rtl/common/add_equal.sv", "rtl/common/onehot_mux.sv"],
                "options": ["-D", "SYNTHESIS=1"],
                "configuration": "Production descriptor comparisons and complete candidate qualification",
            }, 8)
            self.assertGreaterEqual(sum(result["cell_counts"].values()), 200)
            self.assertGreater(batches["batch_count"], 1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--out", type=Path)
    arguments, remaining = parser.parse_known_args()
    OUTPUT = arguments.out.resolve() if arguments.out else None
    unittest.main(argv=[sys.argv[0], *remaining])
