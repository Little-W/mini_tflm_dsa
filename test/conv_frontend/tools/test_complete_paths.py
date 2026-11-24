#!/usr/bin/env python3
"""Check interface path accounting against small connected circuits."""
import copy
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from measure_complete_paths import measure, scope_requirement
from run_complete_timing import SCOPES


def cell(kind, inputs, outputs):
    return {"type": kind, "connections": {**inputs, **outputs},
            "port_directions": {**{name: "input" for name in inputs},
                                **{name: "output" for name in outputs}},
            "parameters": {}}


class CompletePathsTest(unittest.TestCase):
    def test_cache_lookup_scope_includes_saved_query_fields(self):
        module = {"ports": {}, "netnames": {}, "cells": {
            "source": cell("FDRE", {"D": [500]}, {"Q": [1]})}}
        for index in range(12):
            module["cells"][f"address_logic_{index}"] = cell(
                "LUT1", {"I0": [index + 1]}, {"O": [index + 2]})
        names = ["work_request [0]", "lookup_snapshot_set [0]",
                 "g_direct_snapshot_fields.u_fields.request_fields_q [0]",
                 "g_direct_snapshot_fields.u_fields.range_base_q [0]",
                 "g_direct_snapshot_fields.u_fields.demand_word_q [0]",
                 "g_direct_snapshot_fields.u_fields.expected_set_q [0]"]
        for index, name in enumerate(names):
            endpoint = cell("FDRE", {"D": [13 if index == 3 else 2]}, {"Q": [100 + index]})
            endpoint["attributes"] = {
                "fpga_register_origin": "u_frontend.u_cache.g_window.u_window." + name}
            module["cells"][f"state_{index}"] = endpoint
        scope = next(item for item in SCOPES if item[0] == "all_to_cache_lookup")
        report = measure(module, path_limit=0, scopes=[scope])
        selected = report["critical_scopes"][scope[0]]
        self.assertTrue(selected["scope_available"])
        self.assertTrue(selected["graph_complete"])
        self.assertEqual(selected["selected_endpoint_ports"], len(names))
        self.assertEqual(selected["maximum_combinational_cells"], 12)
        self.assertFalse(scope_requirement(report, 11)["met"])

    def test_scope_requirement_checks_actual_available_paths(self):
        report = {"critical_scopes": {"frontend": {
            "scope_available": True, "graph_complete": True,
            "maximum_combinational_cells": 11}}}
        self.assertTrue(scope_requirement(report, 11)["met"])
        report["critical_scopes"]["frontend"]["maximum_combinational_cells"] = 12
        result = scope_requirement(report, 11)
        self.assertFalse(result["met"])
        self.assertEqual(result["exceeding_scopes"], {"frontend": 12})

    def test_scope_requirement_rejects_missing_or_incomplete_scopes(self):
        report = {"critical_scopes": {"frontend": {
            "scope_available": False, "graph_complete": False,
            "maximum_combinational_cells": 0}}}
        result = scope_requirement(report, 11)
        self.assertFalse(result["met"])
        self.assertEqual(result["unavailable_scopes"], ["frontend"])
        self.assertEqual(result["incomplete_scopes"], ["frontend"])

    def test_scope_requirement_needs_named_scopes(self):
        with self.assertRaises(ValueError):
            scope_requirement({"critical_scopes": {}}, 11)

    def test_compressed_inputs_preserve_paths_origins_and_source_hashes(self):
        module = {
            "ports": {"request": {"direction": "input", "bits": [1]},
                      "response": {"direction": "output", "bits": [4]}},
            "netnames": {},
            "cells": {
                "input_logic": cell("LUT1", {"I0": [1]}, {"O": [2]}),
                "state": cell("FDRE", {"D": [2]}, {"Q": [3]}),
                "output_logic": cell("LUT1", {"I0": [3]}, {"O": [4]}),
            },
        }
        mapped = json.dumps({"modules": {"sample": module}}).encode()
        pre_lut = ("module \\sample\n  cell \\FDRE \\state\n"
                   "    connect \\Q \\state_q\n  end\nend\n").encode()
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            reports = []
            for compressed in (False, True):
                paths = []
                for name, content in (("mapped.json", mapped), ("pre_lut.il", pre_lut)):
                    path = folder / (name + (".gz" if compressed else ""))
                    path.write_bytes(gzip.compress(content) if compressed else content)
                    paths.append(path)
                report_path = folder / ("compressed.json" if compressed else "plain.json")
                subprocess.run([
                    sys.executable, str(Path(__file__).with_name("measure_complete_paths.py")),
                    "--mapped", str(paths[0]), "--pre-lut", str(paths[1]), "--top", "sample",
                    "--out", str(report_path), "--require-max-depth", "1",
                ], check=True, capture_output=True, text=True)
                reports.append(json.loads(report_path.read_text()))
        self.assertEqual(reports[0], reports[1])
        self.assertTrue(reports[0]["requirement"]["met"])
        self.assertEqual(reports[0]["mapped_sha256"], hashlib.sha256(mapped).hexdigest())
        self.assertEqual(reports[0]["pre_lut_sha256"], hashlib.sha256(pre_lut).hexdigest())
        inputs = reports[0]["path_groups"]["input_to_register"]["paths"]
        outputs = reports[0]["path_groups"]["register_to_output"]["paths"]
        self.assertEqual(inputs[0]["endpoint"]["register_origin"], "state_q")
        self.assertEqual(outputs[0]["startpoint"]["register_origin"], "state_q")

    def test_all_four_groups_preserve_internal_connections(self):
        module = {
            "ports": {"clk": {"direction": "input", "bits": [100]},
                      "rst_n": {"direction": "input", "bits": [101]},
                      "request": {"direction": "input", "bits": [1]},
                      "response": {"direction": "output", "bits": [6]},
                      "ready": {"direction": "output", "bits": [8]}},
            "netnames": {},
            "cells": {
                "descriptor.input": cell("LUT1", {"I0": [1]}, {"O": [2]}),
                "descriptor.state": cell("FDRE", {"D": [2]}, {"Q": [3]}),
                "stream.select": cell("LUT1", {"I0": [3]}, {"O": [4]}),
                "cache.select": cell("LUT1", {"I0": [4]}, {"O": [5]}),
                "cache.output": cell("LUT1", {"I0": [5]}, {"O": [6]}),
                "cache.state": cell("FDRE", {"D": [5]}, {"Q": [9]}),
                "direct.first": cell("LUT1", {"I0": [1]}, {"O": [7]}),
                "direct.second": cell("LUT1", {"I0": [7]}, {"O": [8]}),
            },
        }
        original = copy.deepcopy(module)
        report = measure(module)
        self.assertTrue(report["graph_complete"])
        self.assertEqual({name: group["maximum_combinational_cells"]
                          for name, group in report["path_groups"].items()},
                         {"register_to_register": 2, "input_to_register": 1,
                          "register_to_output": 3, "input_to_output": 2})
        self.assertEqual(report["interface_bits"], {"input_bits": 1, "output_bits": 2})
        self.assertEqual(module, original)
        self.assertEqual(report["resources"]["logic_lut_cells"], 6)

    def test_data_io_buffers_preserve_interface_paths(self):
        module = {
            "ports": {"request": {"direction": "input", "bits": [1]},
                      "response": {"direction": "output", "bits": [64]}},
            "netnames": {},
            "cells": {"input_buffer": cell("IBUF", {"I": [1]}, {"O": [2]}),
                      "state": cell("FDRE", {"D": [15]}, {"Q": [50]}),
                      "output_buffer": cell("OBUF", {"I": [63]}, {"O": [64]})},
        }
        for index in range(13):
            module["cells"][f"input_logic_{index}"] = cell(
                "LUT1", {"I0": [index + 2]}, {"O": [index + 3]})
            module["cells"][f"output_logic_{index}"] = cell(
                "LUT1", {"I0": [index + 50]}, {"O": [index + 51]})
        report = measure(module, path_limit=0)
        self.assertTrue(report["graph_complete"])
        self.assertEqual(report["maximum_combinational_cells"], 14)
        self.assertEqual(report["path_groups"]["input_to_register"]["maximum_combinational_cells"], 14)
        self.assertEqual(report["path_groups"]["register_to_output"]["maximum_combinational_cells"], 14)

    def test_unknown_internal_module_is_reported(self):
        module = {"ports": {}, "netnames": {}, "cells": {
            "cache": cell("unmapped_cache", {"request": [1]}, {"response": [2]})}}
        report = measure(module)
        self.assertFalse(report["graph_complete"])
        self.assertEqual(report["path_groups"]["register_to_register"]["unclassified_cell_types"],
                         {"unmapped_cache": 1})

    def test_scope_retains_connections_between_storage_endpoints(self):
        module = {"ports": {}, "netnames": {}, "cells": {
            "source": cell("FDRE", {"D": [10]}, {"Q": [1]}),
            "first": cell("LUT1", {"I0": [1]}, {"O": [2]}),
            "second": cell("LUT1", {"I0": [2]}, {"O": [3]}),
            "sink": cell("FDRE", {"D": [3]}, {"Q": [4]})}}
        module["cells"]["source"]["attributes"] = {"fpga_register_origin": "queue.data [0]"}
        module["cells"]["sink"]["attributes"] = {"fpga_register_origin": "cache.valid"}
        report = measure(module, path_limit=0, scopes=[
            ("request", r"queue\.data", r"cache\.valid"),
            ("absent", "missing", r"cache\.valid")])
        selected = report["critical_scopes"]["request"]
        self.assertTrue(selected["scope_available"])
        self.assertTrue(selected["graph_complete"])
        self.assertEqual(selected["maximum_combinational_cells"], 2)
        self.assertEqual(selected["paths"], [])
        self.assertFalse(report["critical_scopes"]["absent"]["scope_available"])


if __name__ == "__main__":
    unittest.main()
