#!/usr/bin/env python3
"""Check shared-array capacity, state-budget requirements and Make entry points."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from capacity import config, model

SOLVER = ROOT / "scripts/capacity/solve.py"
WORKLOADS = [dict(M=1, K=800, N=32), dict(M=800, K=32, N=64), dict(M=65, K=35, N=127)]


def json_from_stdout(text):
    decoder = json.JSONDecoder()
    for offset, char in enumerate(text):
        if char == "{":
            try:
                return decoder.raw_decode(text[offset:])[0]
            except json.JSONDecodeError:
                pass
    raise AssertionError("No JSON object in output: " + text)


class ModelTests(unittest.TestCase):
    def test_buffer_inventory_includes_every_shared_subsystem(self):
        a = model.allocation(4, 8, 16384, 131072, shared=False)
        expected = dict(ia_cache=4*16*16*16, ia_cache_tags=8*62, ia_slot_metadata=8*12,
                        kernel_cache=3*16*16*16,
                        bias_cache=2*4*16*32, requant_is_cache=4*16*103,
                        oa_s8_fifo=16*16*16*8, oa_s16_fifo=4*16*16*16,
                        conv_data_cache=16*2*128*8, conv_cache_metadata=16*2*148,
                        conv_prefetch_queue=8*129, conv_request_queue=135,
                        conv_response_queue=129, vector_buffers=16*(80+49*8+134),
                        vector_dw_snapshot=16*32, vector_dw_result_queue=2*16*8,
                        vector_write_queue=2*64*8,
                        vector_pool_reciprocal_rom=257*18,
                        ps_payload=16384*8, ps_frame_lengths=8*7,
                        ps_decoded_fifo=8*512, ps_decoded_first=8, ps_frame_valid=8)
        self.assertEqual(a["buffer_arrays_bits"], expected)
        self.assertEqual(a["buffer_ram_bits"], sum(expected.values()))
        self.assertIsNone(a["logical_state_bits"])

    def test_ordinary_ps_uses_complete_rows_and_same_compute_buffers(self):
        a = model.buffer_arrays_bits(4, 16, 16384, compressed=True, shared=False)
        b = model.buffer_arrays_bits(4, 16, 0, compressed=False)
        for key in a:
            if not key.startswith("ps_"):
                self.assertEqual(a[key], b[key])
        self.assertEqual(b["ps_payload"], 47*17*512)
        self.assertNotIn("ps_directory", b)

    def test_complete_state_cannot_use_an_unmeasured_formula(self):
        with self.assertRaisesRegex(ValueError, "elaboration"):
            model.allocation(4, 8, 16384, 131072, "logical-state")
        with self.assertRaisesRegex(ValueError, "elaboration"):
            model.solve(WORKLOADS, 65536, "logical-state")

    def test_dense_bound_and_no_ps_single_reduction(self):
        ws = model.plan_for_hardware(1, 800, 32, 4, 16, 4096, mode=0)
        self.assertEqual((ws["R"], ws["W"], ws["frame_rows"], ws["required_pool_bytes"]), (1, 2, 1, 128))
        one = model.plan_for_hardware(64, 9, 128, 4, 16, 4096, mode=0)
        self.assertEqual((one["R"], one["W"], one["required_pool_bytes"]), (4, 8, 0))

    def test_raw_and_adaptive_guaranteed_plans_match(self):
        for task in WORKLOADS:
            a = model.plan_for_hardware(**task, cache=4, frames=16, pool_bytes=4096, representation="adaptive", adaptive=False)
            b = model.plan_for_hardware(**task, cache=4, frames=16, pool_bytes=4096, representation="raw32", adaptive=False)
            self.assertEqual(a, b)

    def test_shared_single_k_uses_available_ia_banks(self):
        for width, expected_r in ((1, 8), (2, 4)):
            p = model.plan_for_hardware(256, 9, 32, 4, 16, 12288, mode=0, lhs_bytes=width)
            self.assertEqual((p["R"], p["ia_bank_count"], p["ia_bytes"], p["ps_pool_bytes"]),
                             (expected_r, 2, 4096, 10240))
            self.assertEqual(p["required_pool_bytes"], 0)
            self.assertFalse(p["adaptive_active"])

    def test_shared_s16_allocation_follows_streaming_operand(self):
        ws = model.plan_for_hardware(256, 35, 32, 4, 16, 12288,
                                     mode=0, lhs_bytes=2, adaptive=False)
        is_plan = model.plan_for_hardware(32, 35, 256, 4, 16, 12288,
                                          mode=1, lhs_bytes=2, adaptive=False)
        self.assertEqual((ws["ia_bank_count"], ws["ia_bytes"], ws["ps_pool_bytes"]),
                         (2, 4096, 10240))
        self.assertEqual((is_plan["ia_bank_count"], is_plan["ia_bytes"], is_plan["ps_pool_bytes"]),
                         (1, 2048, 12288))
        for p in (ws, is_plan):
            ps_banks = p["ps_pool_bytes"] // 2048
            self.assertEqual(p["ia_bytes"] + p["ps_pool_bytes"], 14336)
            self.assertGreaterEqual(ps_banks, 4)
            self.assertLessEqual(p["W"] * model.ceil_div(4 * p["frame_rows"], ps_banks), 128)
            self.assertEqual(p["raw_safe_is_mode"], p["mode"])
            self.assertEqual(p["raw_safe_ia_bank_count"], p["ia_bank_count"])
            self.assertEqual(p["raw_safe_pool_bytes"], p["ps_pool_bytes"])

    def test_buffer_search_obeys_budget_and_frame_bound(self):
        for budget in (49152, 65536, 131072):
            result = model.solve(WORKLOADS, budget)
            a = result["allocation"]
            self.assertLessEqual(a["budget_used_bytes"], budget)
            self.assertTrue(a["shared_ia_ps_enabled"])
            self.assertEqual(a["ps_pool_bytes"] % 64, 0)
            for p in result["plans"]:
                self.assertLessEqual(p["R"], a["max_r_s8"])
                self.assertLessEqual(p["W"], a["ps_frame_count"])
                if not p["adaptive_active"]:
                    self.assertLessEqual(p["required_pool_bytes"], p["ps_pool_bytes"])
                self.assertLessEqual(model.ceil_div(p["frame_rows"] * p["literal_record_bytes"], 64) * 64,
                                     p["ps_pool_bytes"])
                self.assertGreaterEqual(p["ideal_operand_read_bytes"], p["M"] * p["K"] + p["N"] * p["K"])

    def test_search_uses_shared_physical_banks(self):
        tasks = [dict(M=961, K=144, N=32), dict(M=225, K=288, N=64)]
        result = model.solve(tasks, 49152)
        allocation = result["allocation"]
        self.assertTrue(allocation["shared_ia_ps_enabled"])
        self.assertEqual(allocation["shared_total_bytes"], allocation["shared_physical_bank_count"] * 2048)
        self.assertEqual(result["search"]["enumerated_geometries"], 4)
        self.assertLessEqual(result["search"]["feasible_geometries"],
                             result["search"]["enumerated_geometries"])
        self.assertEqual(result["search"]["feasible_configurations"],
                         result["search"]["feasible_geometries"])

    def test_requant_group_storage_follows_physical_bank_selection(self):
        for bank_bytes in (2048, 4096, 8192):
            for bank_count in (6, 7, 8, 9):
                parameters = dict(bank_bytes=bank_bytes, bank_count=bank_count)
                layout = model.memory_geometry(4, 16, 49152, **parameters)
                arrays = model.buffer_arrays_bits(4, 16, 49152, **parameters)
                expected = layout["max_r_s8"] * 16 * 513 if bank_count < 8 else 0
                self.assertEqual(arrays.get("requant_input_rows", 0), expected)
        fixed = model.buffer_arrays_bits(4, 16, 49152, shared=False)
        self.assertNotIn("requant_input_rows", fixed)

    def test_production_bank_configurations_preserve_capacity_budget(self):
        expected_bytes = {6: 111591.25, 7: 119783.25, 8: 114617.25, 9: 122809.25}
        for bank_count, expected in expected_bytes.items():
            arrays = model.buffer_arrays_bits(4, 16, 49152, bank_bytes=8192,
                                             bank_count=bank_count)
            used = sum(arrays.values()) / 8
            self.assertEqual(used, expected)
            self.assertLessEqual(used, 131072)

    def test_pool_increment_and_real_tails(self):
        for pool in (4096, 8192, 16384):
            self.assertEqual(model.buffer_ram_bytes(4, 8, pool + 64, shared=False) -
                               model.buffer_ram_bytes(4, 8, pool, shared=False), 64)
        p = model.plan_for_hardware(17, 35, 49, 4, 16, 16384, mode=1)
        self.assertGreaterEqual(p["ideal_operand_read_bytes"], 17 * 35 + 49 * 35)
        self.assertEqual((p["row_groups"]-1)*p["R"]+p["row_tail_tiles"], 4)
        self.assertEqual((p["column_groups"]-1)*p["W"]+p["column_tail_tiles"], 2)

    def test_configurable_shared_bank_geometry_and_plans(self):
        for bank_bytes in (2048, 4096, 8192):
            for bank_count in range(6, 10):
                parameters = dict(bank_bytes=bank_bytes, bank_count=bank_count)
                layout = model.memory_geometry(4, 16, 4096, **parameters)
                arrays = model.buffer_arrays_bits(4, 16, 4096, **parameters)
                self.assertTrue(layout["shared_ia_ps_enabled"])
                self.assertEqual(layout["shared_total_bytes"], bank_bytes*bank_count)
                self.assertEqual(layout["payload_bank_depth"], bank_bytes//16)
                self.assertEqual(layout["payload_metadata_bank_count"], bank_count-1)
                self.assertEqual(layout["max_r_s8"], (4 if bank_count >= 8 else 2)*bank_bytes//512)
                self.assertEqual(layout["max_r_s16"], (4 if bank_count >= 8 else 2)*bank_bytes//1024)
                self.assertEqual(layout["default_max_r_s8"], bank_bytes//512)
                self.assertEqual(layout["max_frame_rows"], (4 if bank_count >= 8 else 2)*bank_bytes//32)
                self.assertEqual(arrays["ia_ps_shared_ram"], bank_count*bank_bytes*8)
                self.assertNotIn("ps_free_bitmap", arrays)
                self.assertNotIn("ps_directory", arrays)
                self.assertEqual(layout["output_banks_s8"], max(32, layout["max_r_s8"]))
                self.assertEqual(arrays["oa_s8_fifo"], layout["output_banks_s8"]*16*16*8)
                for representation in ("raw32", "adaptive"):
                    plan = model.plan_for_hardware(256, 144, 64, 4, 16, 4096,
                                                  representation, **parameters)
                    self.assertEqual(plan["ia_bytes"]+plan["ps_pool_bytes"], bank_count*bank_bytes)
                    self.assertEqual(plan["ia_bytes"], plan["ia_bank_count"]*bank_bytes)
                    ps_banks = bank_count-plan["ia_bank_count"]
                    record_bytes = 64 if plan["ps_control"] & 1 else plan["literal_record_bytes"]
                    reserved = model.ceil_div(plan["frame_rows"]*(record_bytes//16), ps_banks)
                    self.assertLessEqual(reserved, bank_bytes//16)
                    if not plan["ps_control"] & 2:
                        stationary = 256 if plan["mode"] else 64
                        self.assertLessEqual(reserved*min(plan["W"], model.ceil_div(stationary, 16)),
                                             bank_bytes//16)
                    if representation == "raw32":
                        self.assertTrue(plan["ps_control"] & 1)
        for width, reuse in ((1, 16), (2, 8)):
            plan = model.plan_for_hardware(512, 9, 32, 4, 16, 12288, mode=0,
                                          lhs_bytes=width, bank_bytes=4096, bank_count=7)
            self.assertEqual((plan["R"], plan["ia_bank_count"], plan["ia_bytes"]), (reuse, 2, 8192))
            self.assertEqual(plan["required_pool_bytes"], 0)

    def test_explicit_banks_and_fixed_storage_are_independent(self):
        parameters = dict(bank_bytes=4096, bank_count=6)
        a = model.memory_geometry(4, 16, 4096, **parameters)
        b = model.memory_geometry(4, 16, 8192, **parameters)
        self.assertEqual(a["shared_total_bytes"], 24576)
        self.assertEqual(a["shared_total_bytes"], b["shared_total_bytes"])
        fixed = model.buffer_arrays_bits(4, 16, 4096, shared=False, **parameters)
        self.assertNotIn("ia_ps_shared_ram", fixed)
        self.assertEqual(fixed["ia_cache"], 2048*8)
        self.assertEqual(fixed["ps_payload"], 4096*8)
        for bank_bytes in (0, 512, 1024, 1536, 16384):
            with self.assertRaises(ValueError):
                model.memory_geometry(4, 16, 12288, bank_bytes=bank_bytes, bank_count=7)
        for bank_count in (0, 5, 10, True):
            with self.assertRaises(ValueError):
                model.memory_geometry(4, 16, 12288, bank_count=bank_count)

    def test_search_uses_selected_bank_size_and_shared_capacity(self):
        for bank_bytes in (2048, 4096, 8192):
            result = model.solve(WORKLOADS, 131072, bank_bytes=bank_bytes)
            a = result["allocation"]
            self.assertTrue(a["shared_ia_ps_enabled"])
            self.assertEqual(a["shared_bank_bytes"], bank_bytes)
            self.assertIn(a["shared_physical_bank_count"], range(6, 10))
            self.assertEqual(a["default_ps_pool_bytes"], (a["shared_physical_bank_count"]-1)*bank_bytes)
            self.assertLessEqual(a["budget_used_bytes"], 131072)
            for plan in result["plans"]:
                self.assertEqual(plan["ia_bytes"]+plan["ps_pool_bytes"], a["shared_total_bytes"])
            pool, state = model.max_pool_bytes(4, 16, 131072, bank_bytes=bank_bytes, bank_count=7)
            self.assertEqual(pool, 6*bank_bytes)
            self.assertIsNone(state)

    def test_shared_search_preserves_build_parameters(self):
        result = model.solve(WORKLOADS, 131072, bank_bytes=4096,
                             cache_blocks=2, frame_count=4, ps_build_bytes=16384)
        a = result["allocation"]
        self.assertEqual((a["ia_cache_blocks"], a["ps_frame_count"], a["configured_ps_pool_bytes"]),
                         (2, 4, 16384))
        legal_ia_banks = [1, 2, 4] if a["shared_physical_bank_count"] >= 8 else [1, 2]
        self.assertEqual([entry["ia_banks"] for entry in a["runtime_bank_allocations"]], legal_ia_banks)
        for entry in a["runtime_bank_allocations"]:
            self.assertEqual(entry["ia_bytes"] + entry["ps_bytes"], a["shared_total_bytes"])
        for plan in result["plans"]:
            self.assertIn(plan["ia_bank_count"], legal_ia_banks)
            self.assertEqual(plan["ia_bytes"] + plan["ps_pool_bytes"], a["shared_total_bytes"])

    def test_measured_search_receives_explicit_bank_geometry(self):
        calls = []
        def measure(cache, frames, pool, representation, *, bank_bytes, bank_count):
            calls.append((cache, frames, pool, representation, bank_bytes, bank_count))
            return sum(model.buffer_arrays_bits(cache, frames, pool,
                bank_bytes=bank_bytes, bank_count=bank_count).values())+4096
        result = model.solve([dict(M=512, K=16, N=32)], 131072, "logical-state",
                             measure=measure, bank_bytes=4096)
        self.assertTrue(calls)
        self.assertEqual({item[4] for item in calls}, {4096})
        self.assertEqual({item[5] for item in calls}, {6, 7, 8, 9})
        a = result["allocation"]
        self.assertEqual(a["logical_state_bits"], a["buffer_ram_bits"]+4096)
        self.assertEqual(a["shared_total_bytes"], a["shared_physical_bank_count"]*4096)

    def test_invalid_geometry_and_workloads(self):
        for args in ((3, 8, 16384), (4, 0, 16384), (4, 8, 16385), (4, 8, 0)):
            with self.assertRaises(ValueError):
                model.buffer_ram_bytes(*args)
        for tasks in ([], [dict(M=0, K=1, N=1)], [dict(M=True, K=1, N=1)], [dict(M=1<<20, K=1, N=1)]):
            with self.assertRaises(ValueError):
                model.solve(tasks, 65536)


class CliTests(unittest.TestCase):
    def setUp(self):
        inherited = set(config.DEFAULTS) | {
            "NPU_CONFIG", "MAKEFLAGS", "MFLAGS", "MAKELEVEL", "GNUMAKEFLAGS", "NPU_CONFIG_INCLUDED"}
        environment = mock.patch.dict(os.environ, {key: value for key, value in os.environ.items()
                                                  if key not in inherited}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        self.temporary = tempfile.TemporaryDirectory(prefix="shared-capacity-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.path = self.directory / "npu.mk"
        self.path.write_text("# User setting\n" + "".join(f"{k} ?= {v}\n" for k, v in config.DEFAULTS.items()))

    def run_cli(self, *args, success=True):
        run = subprocess.run([sys.executable, str(SOLVER), "--config", str(self.path), *map(str, args)],
                             text=True, capture_output=True, timeout=30)
        self.assertEqual(run.returncode == 0, success, run.stdout + run.stderr)
        return run

    def test_solve_readonly_and_atomic_apply(self):
        original = self.path.read_bytes()
        self.run_cli("--shape", "1,800,32", "--max-ram-kib", 64)
        self.assertEqual(self.path.read_bytes(), original)
        self.run_cli("--shape", "1,800,32", "--max-ram-kib", 64, "--apply")
        self.assertIn("# User setting", self.path.read_text())
        before = self.path.read_bytes(), self.path.stat().st_mtime_ns
        self.run_cli("--shape", "1,800,32", "--max-ram-kib", 64, "--apply")
        self.assertEqual((self.path.read_bytes(), self.path.stat().st_mtime_ns), before)

    def test_apply_preserves_nonallocation_build_parameters(self):
        config.update_config(self.path, {"IA_CACHE_BLOCKS": 2, "PS_FRAME_COUNT": 4,
                                         "PS_POOL_BYTES": 16384})
        result = json_from_stdout(self.run_cli("--shape", "256,1024,128", "--max-ram-kib", 128,
                                               "--apply").stdout)
        saved = config.read_config(self.path)
        self.assertEqual((saved["IA_CACHE_BLOCKS"], saved["PS_FRAME_COUNT"], saved["PS_POOL_BYTES"]),
                         (2, 4, 16384))
        self.assertNotIn("PS_POOL_BYTES", result["configuration_updates"])
        self.assertEqual(result["plans"][0]["ia_bytes"] + result["plans"][0]["ps_pool_bytes"],
                         result["allocation"]["shared_total_bytes"])

    def test_inspection_covers_both_ps_modes(self):
        for active in (0, 1):
            result = json_from_stdout(self.run_cli("--show", "--set", f"PCR_ENGINE={active}").stdout)
            self.assertTrue(result["capacity_model_applies"])
            self.assertFalse(result["allocation"]["compressed_ps"])
            self.assertEqual(result["allocation"]["ps_frame_store_enabled"], bool(active))
            self.assertIn("vector_buffers", result["allocation"]["buffer_arrays_bits"])

    def test_raw_setting_and_generated_header(self):
        result = json_from_stdout(self.run_cli("--show", "--set", "PS_FORCE_RAW=1").stdout)
        self.assertEqual(result["configuration"]["CAPACITY_REPRESENTATION"], "raw32")
        header = self.directory / "config.h"
        self.run_cli("--emit-c-header", header)
        self.assertIn("NPU_CONFIG_BUFFER_RAM_BITS", header.read_text())
        self.assertNotIn("PANEL", header.read_text())

    def test_invalid_commands_do_not_change_configuration(self):
        before = self.path.read_bytes()
        for args in (("--check", "--set", "SIZE=8"), ("--check", "--set", "PS_POOL_BYTES=4097"),
                     ("--max-state-kib", 64), ("--max-ram-kib", 1, "--apply"),
                     ("--set", "PS_POOL_BYTES=$(touch /tmp/unwanted)", "--check")):
            self.run_cli(*args, success=False)
            self.assertEqual(self.path.read_bytes(), before)

    @unittest.skipUnless(shutil.which("make"), "GNU Make is required")
    def test_make_capacity_check_uses_shared_defaults(self):
        run = subprocess.run(["make", "--no-print-directory", "capacity-check", f"NPU_CONFIG={self.path}"],
                             cwd=ROOT, text=True, capture_output=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        result = json_from_stdout(run.stdout)
        self.assertEqual(result["allocation"]["max_frame_rows"], 128)
        self.assertEqual(result["allocation"]["shared_total_bytes"], 14336)
        self.assertEqual(result["allocation"]["logical_ps_rows"], 1024)
        self.assertNotIn("panel_max_r", result["allocation"])


if __name__ == "__main__":
    unittest.main()
