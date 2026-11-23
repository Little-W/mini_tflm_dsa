"""检查 IA 存储模式的配置、构建参数、容量计算与报告隔离。"""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.capacity import config, elaboration, menuconfig, model


class IaCompactConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="ia_compact_config_")
        self.work = Path(self.temporary.name)
        self.configuration = self.work / "npu.mk"
        self.configuration.write_text("IA_COMPACT_ENABLE ?= 1\n")
        self.environment = {key: value for key, value in os.environ.items()
                            if key not in {*config.DEFAULTS, "NPU_CONFIG", "MAKEFLAGS", "MFLAGS"}}

    def tearDown(self):
        self.temporary.cleanup()

    def make(self, directory, compact, expression, *, accepted=True):
        extra = self.work / "inspect.mk"
        extra.write_text(".RECIPEPREFIX :=\nUNIT := npu_top\ninspect-ia:\n\t@$(info " + expression + ")\n\t@:\n")
        run = subprocess.run(["make", "--no-print-directory", "-C", str(ROOT / directory),
                              "-f", "Makefile", "-f", str(extra), "inspect-ia",
                              f"NPU_CONFIG={self.configuration}", f"IA_COMPACT_ENABLE={compact}"],
                             env=self.environment, text=True, capture_output=True, timeout=30)
        self.assertEqual(run.returncode == 0, accepted, run.stdout + run.stderr)
        return run.stdout + run.stderr

    def test_configuration_values_and_environment_precedence(self):
        for compact in (0, 1):
            values = config.validate_config({**config.DEFAULTS, "IA_COMPACT_ENABLE": compact})
            self.assertEqual(values["IA_COMPACT_ENABLE"], compact)
            self.assertIn(f"#define NPU_CONFIG_IA_COMPACT_ENABLE {compact}", config.emit_c_header(values))
            with patch.dict(os.environ, {"IA_COMPACT_ENABLE": str(compact)}):
                self.assertEqual(config.selected_config(self.configuration)["IA_COMPACT_ENABLE"], compact)
        for invalid in (-1, 2, 32, True, 1.0, "1"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                config.validate_config({**config.DEFAULTS, "IA_COMPACT_ENABLE": invalid})
        self.assertEqual(next(field for field in menuconfig.FIELDS
                              if field.key == "IA_COMPACT_ENABLE").choices, (0, 1))

    def test_make_build_parameters_and_distinct_outputs(self):
        for compact in (0, 1):
            unit = self.make(".", compact, "$(UNIT_DEFINES) $(CONFIG_TAG) $(NPU_CAPACITY_SET_ARGS)")
            self.assertIn(f"_iac{compact}", unit)
            self.assertIn(f"+TB_IA_COMPACT_ENABLE={compact}", unit)
            self.assertIn(f"--set 'IA_COMPACT_ENABLE={compact}'", unit)
            soc = self.make("veri/sim", compact, "$(MMA_PARAM_OPTS) $(SOC_HW_DEFINES) $(SIMV) $(PCR_CONFIG_TAG)")
            self.assertIn(f"-pvalue+tb_top.DUT_IA_COMPACT_ENABLE={compact}", soc)
            self.assertIn(f"-DNPU_CONFIG_IA_COMPACT_ENABLE={compact}", soc)
            self.assertEqual(soc.count(f"_IAC{compact}"), 2)
            asic = self.make("asic/synthesis", compact, "$(DESIGN_PARAMETERS) $(PROJ_TEMP)")
            self.assertIn(f"IA_COMPACT_ENABLE={compact}", asic)
            self.assertIn(f"_iac{compact}", asic)

    def test_make_rejects_invalid_switch_before_building(self):
        for invalid in ("", "2", "-1", "0 1", "%", "true", "0x1"):
            with self.subTest(invalid=invalid):
                output = self.make(".", invalid, "$(NPU_EFFECTIVE_CONFIG_VALUES)", accepted=False)
                self.assertIn("IA_COMPACT_ENABLE must be 0 or 1", output)

    def test_python_backend_configuration_and_output_identity(self):
        for compact in (0, 1):
            run = subprocess.run([sys.executable, str(ROOT / "veri/python_model/build_backend.py"),
                                  "--config", str(self.configuration), "--ia-compact-enable", str(compact),
                                  "--print-config"], env=self.environment, text=True,
                                 capture_output=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stderr)
            parameters = json.loads(run.stdout)
            self.assertEqual(parameters["ia_compact_enable"], compact)
            self.assertIn(f"_iac{compact}", parameters["tag"])

    def test_capacity_tracks_physical_storage_and_input_reuse(self):
        self.assertEqual(config.DEFAULTS["IA_COMPACT_ENABLE"], 0)
        self.assertFalse(model.memory_geometry(4, 16, 12288)["ia_compact_enable"])
        for bank_bytes in (2048, 8192):
            for bank_count in (7, 8):
                layouts, arrays = {}, {}
                for compact in (0, 1):
                    options = dict(bank_bytes=bank_bytes, bank_count=bank_count,
                                   ia_compact_enable=bool(compact))
                    layouts[compact] = model.memory_geometry(4, 16, 12288, **options)
                    arrays[compact] = model.buffer_arrays_bits(4, 16, 12288, **options)
                self.assertEqual(layouts[1]["max_r_s8"], 2 * layouts[0]["max_r_s8"])
                self.assertEqual(layouts[1]["max_r_s16"], layouts[0]["max_r_s16"])
                self.assertEqual([layouts[value]["default_ia_banks"] for value in (0, 1)], [2, 1])
                for compact in (0, 1):
                    self.assertEqual(layouts[compact]["register_reset_ia_banks"], 1)
                    self.assertEqual(layouts[compact]["default_ia_banks_s16"], 2)
                    self.assertEqual(layouts[compact]["default_max_r_s16"], bank_bytes // 512)
                    first = layouts[compact]["runtime_bank_allocations"][0]
                    self.assertEqual(first["supports_s8_stream"], bool(compact))
                    self.assertFalse(first["supports_s16_stream"])
                    self.assertEqual(layouts[compact]["default_ia_bytes"] +
                                     layouts[compact]["default_ps_pool_bytes"], bank_bytes * bank_count)
                self.assertEqual(arrays[1]["ia_ps_shared_ram"], arrays[0]["ia_ps_shared_ram"])
                for name in ("ia_cache_tags", "ia_slot_metadata", "bias_cache", "requant_is_cache"):
                    self.assertEqual(arrays[1][name], 2 * arrays[0][name])
        plans = [model.plan_for_hardware(256, 9, 32, 4, 16, 12288, mode=0,
                                        ia_compact_enable=bool(compact)) for compact in (0, 1)]
        self.assertEqual([plan["R"] for plan in plans], [4, 8])
        for mode in (0, 1):
            plan = model.plan_for_hardware(16, 16, 16, 4, 16, 12288,
                                           mode=mode, ia_compact_enable=False)
            self.assertGreaterEqual(plan["ia_bank_count"], 2)

    def test_elaboration_reports_are_specific_to_storage_mode(self):
        off, on = ({**config.DEFAULTS, "IA_COMPACT_ENABLE": value} for value in (0, 1))
        sources = {"rtl/npu/top/npu_top.sv": "source-digest"}
        self.assertNotEqual(elaboration.identity(off, sources), elaboration.identity(on, sources))
        report = dict(passed=True, elaboration_target="asic", source_sha256=sources,
                      hardware_configuration=elaboration.hardware_config(on))
        with patch.object(elaboration, "sources_sha256", return_value=sources):
            self.assertTrue(elaboration.current_report(on, report))
            self.assertFalse(elaboration.current_report(off, report))


if __name__ == "__main__":
    unittest.main()
