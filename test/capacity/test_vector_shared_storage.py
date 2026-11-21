"""验证向量共享存储的容量归属、工作累加寄存器及实例检查。"""
import copy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.capacity import config, elaboration, model


def declaration(module, name, bits, category=None, path=None):
    return dict(module=module, name=name, bits=bits, buffer_category=category,
                path=path or f"npu_axil_top.dut.engine.{name}")


def storage_state(shared):
    state = dict(module_instances={"vector_engine": 1}, sequential_declarations=[
        declaration("vector_engine", "acc_buf", 512, "vector_buffers")])
    if shared:
        state["module_instances"].update(vector_shared_store=1, ia_ps_channel_ram=1)
    else:
        state["module_instances"]["vector_weight_store"] = 1
        state["sequential_declarations"] += [
            declaration("regfile", "mem", 6272, "vector_buffers",
                        "npu_axil_top.dut.engine.g_private_weights.u_weights.u_storage.mem"),
            declaration("vector_engine", "g_private_snapshot.dw_snapshot", 512,
                        "vector_dw_snapshot")]
    return state


class VectorSharedStorageTests(unittest.TestCase):
    def test_shared_data_is_counted_in_the_existing_memory(self):
        for bank_bytes in (2048, 4096, 8192):
            for banks in (6, 7, 8, 9):
                arrays = model.buffer_arrays_bits(4, 16, 12288,
                    bank_bytes=bank_bytes, bank_count=banks)
                self.assertEqual(arrays["ia_ps_shared_ram"], bank_bytes * banks * 8)
                self.assertEqual(arrays["vector_buffers"], 16 * (80 + 128 + 6))
                self.assertNotIn("vector_dw_snapshot", arrays)

    def test_nonshared_configuration_keeps_private_data(self):
        for options in ({"shared": False}, {"compressed": False}):
            arrays = model.buffer_arrays_bits(4, 16, 12288, **options)
            self.assertEqual(arrays["vector_buffers"], 16 * (80 + 49 * 8 + 128 + 6))
            self.assertEqual(arrays["vector_dw_snapshot"], 512)
            self.assertNotIn("ia_ps_shared_ram", arrays)

    def test_hardware_identity_records_storage_selection(self):
        shared = {**config.DEFAULTS, "PCR_ENGINE": 1, "SHARED_BANK_COUNT": 8}
        private = {**shared, "PCR_ENGINE": 0}
        self.assertEqual(elaboration.hardware_config(shared)["SHARED_STORAGE_ENABLE"], 1)
        self.assertEqual(elaboration.hardware_config(private)["SHARED_STORAGE_ENABLE"], 0)

    def test_each_valid_implementation_passes(self):
        for shared in (False, True):
            self.assertTrue(elaboration.vector_storage_inventory(storage_state(shared), shared)["passed"])

    def test_shared_build_rejects_private_weight_module(self):
        for module in ("vector_weight_store", "vector_weight_bank"):
            state = storage_state(True)
            state["module_instances"][module] = 1
            self.assertFalse(elaboration.vector_storage_inventory(state, True)["passed"])

    def test_shared_build_rejects_private_data_declarations(self):
        for item in storage_state(False)["sequential_declarations"][1:]:
            state = storage_state(True)
            state["sequential_declarations"].append(copy.deepcopy(item))
            self.assertFalse(elaboration.vector_storage_inventory(state, True)["passed"])

    def test_shared_build_requires_one_memory_and_one_adapter(self):
        for module in ("vector_shared_store", "ia_ps_channel_ram"):
            for count in (0, 2):
                state = storage_state(True)
                state["module_instances"][module] = count
                self.assertFalse(elaboration.vector_storage_inventory(state, True)["passed"])
        state = storage_state(True)
        state["module_instances"]["ia_ps_shared_ram"] = 1
        self.assertFalse(elaboration.vector_storage_inventory(state, True)["passed"])

    def test_working_accumulator_remains_in_both_implementations(self):
        for shared in (False, True):
            state = storage_state(shared)
            state["sequential_declarations"][0]["bits"] = 0
            self.assertFalse(elaboration.vector_storage_inventory(state, shared)["passed"])

    def test_private_build_requires_complete_weight_and_snapshot_capacity(self):
        for index in (1, 2):
            state = storage_state(False)
            state["sequential_declarations"][index]["bits"] -= 8
            self.assertFalse(elaboration.vector_storage_inventory(state, False)["passed"])


if __name__ == "__main__":
    unittest.main()
