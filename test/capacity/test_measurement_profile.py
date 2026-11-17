"""Check hardware profiles used by the production-plan measurement tools."""
import hashlib
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "test/ps_compression"))
from planner_profile import capability_expectations, normalize_profile, profile_header, profile_signature


def manifest(width=64, bank_bytes=2048, banks=7):
    return {"profile": dict(size=16, ia_cache_blocks=4, ps_frame_count=16,
        bus_width=width, dma_max_bytes=256*(width//8), ps_compress=True,
        shared_bank_bytes=bank_bytes, shared_bank_count=banks,
        shared_total_bytes=bank_bytes*banks, shared_ia_bank_choices=[1,2,4],
        ps_directory_rows=1024, output_banks_s16_max=4, ps_storage_rows=799,
        ram_continuous_read_beat_cycles=1, ram_read_first_latency=8)}


class MeasurementProfileTests(unittest.TestCase):
    def test_supported_physical_geometries(self):
        for width in (32, 64):
            for bank_bytes in (2048, 4096, 8192):
                for banks in range(6, 10):
                    p = normalize_profile(manifest(width, bank_bytes, banks), root=ROOT,
                                          literal_bound=True)
                    self.assertEqual(p["shared_total_bytes"], bank_bytes*banks)
                    self.assertEqual(p["dma_max_bytes"], 256*(width//8))
                    self.assertEqual(p["ps_pool_bytes"], bank_bytes*(banks-1))
                    self.assertEqual(p["ps_caps"], 0x01100037)
                    self.assertEqual(p["ps_directory_bits_per_row"],
                                     {2048:34,4096:38,8192:42}[bank_bytes])
                    self.assertEqual(p["matrix_output_banks"],
                                     max(32, bank_bytes // 128) | (4 << 16))

    def test_conv_memory_defaults_are_recorded(self):
        memory = ROOT / "test/conv_npu/axi_memory.sv"
        m = dict(size=16, bus_width=64, ps_compress=True, pool_bytes=12288,
                 shared_bank_bytes=2048, shared_bank_count=0,
                 source_sha256={"test/conv_npu/axi_memory.sv":hashlib.sha256(memory.read_bytes()).hexdigest()})
        p = normalize_profile(m, root=ROOT)
        self.assertEqual(p["shared_bank_count"], 7)
        self.assertEqual(p["memory_timing"]["ram_read_first_latency"], 8)
        self.assertEqual(p["memory_timing"]["ram_continuous_read_beat_cycles"], 1)
        self.assertEqual(p["planner_costs"]["read_beat_cycles"], 1)
        self.assertEqual(p["memory_timing"]["sources"]["source_sha256"],
                         m["source_sha256"]["test/conv_npu/axi_memory.sv"])
        m["source_sha256"]["test/conv_npu/axi_memory.sv"] = "0"*64
        with self.assertRaises(ValueError):
            normalize_profile(m, root=ROOT)
        m.update(ram_continuous_read_beat_cycles=2, ram_read_first_latency=16)
        explicit = normalize_profile(m, root=ROOT)
        self.assertEqual(explicit["memory_timing"]["ram_read_first_latency"], 16)
        self.assertEqual(explicit["planner_costs"]["read_beat_cycles"], 2)

    def test_invalid_physical_profiles(self):
        for name, value in (("bus_width", True), ("bus_width", 128),
                ("shared_bank_bytes", 512), ("shared_bank_bytes", 1024), ("shared_bank_count", True),
                ("shared_bank_count", 10), ("shared_total_bytes", 8192),
                ("dma_max_bytes", 4096), ("dma_max_bytes", 12),
                ("ram_continuous_read_beat_cycles", 0), ("ram_read_first_latency", 0),
                ("schedule_ia_tile_setup_cycles", -1),
                ("schedule_quant_group_setup_cycles", True),
                ("shared_ia_bank_choices", [0,1,2,4])):
            m = manifest(); m["profile"][name] = value
            with self.subTest(name=name,value=value), self.assertRaises(ValueError):
                normalize_profile(m, root=ROOT)
        for value in (-1, 256, True):
            with self.assertRaises(ValueError):
                normalize_profile(manifest(), root=ROOT, ram_fixed_lat=value)

    def test_effective_costs_and_first_response_are_independent(self):
        m = manifest()
        p = normalize_profile(m, root=ROOT)
        m["profile"]["ram_read_first_latency"] = 16
        q = normalize_profile(m, root=ROOT)
        self.assertEqual(p["planner_costs"], q["planner_costs"])
        self.assertNotEqual(profile_signature(p), profile_signature(q))
        m["profile"]["schedule_read_request_cycles"] = 4
        r = normalize_profile(m, root=ROOT)
        self.assertEqual(r["planner_costs"]["read_request_cycles"], 4)
        self.assertNotEqual(profile_signature(q), profile_signature(r))
        s = normalize_profile(m, root=ROOT, ram_fixed_lat=2)
        self.assertNotEqual(profile_signature(r), profile_signature(s))

    def test_loader_control_costs_are_recorded(self):
        m = manifest()
        default = normalize_profile(m, root=ROOT)
        self.assertEqual(default["planner_costs"]["ia_tile_setup_cycles"], 2)
        self.assertEqual(default["planner_costs"]["quant_group_setup_cycles"], 2)
        m["profile"]["schedule_ia_tile_setup_cycles"] = 3
        m["profile"]["schedule_quant_group_setup_cycles"] = 5
        custom = normalize_profile(m, root=ROOT)
        self.assertNotEqual(profile_signature(default), profile_signature(custom))
        header = profile_header(custom)
        self.assertIn("#define DSA_SCHEDULE_IA_TILE_SETUP_CYCLES 3u", header)
        self.assertIn("#define DSA_SCHEDULE_QUANT_GROUP_SETUP_CYCLES 5u", header)

    def test_generated_header_and_runtime_capabilities(self):
        p = normalize_profile(manifest(64,4096,9),root=ROOT,literal_bound=True)
        header = profile_header(p)
        for value in ("#define DENSE_SWEEP_BUS_WIDTH 64u", "#define DENSE_SWEEP_DMA_MAX_BYTES 2048u",
                      "#define DENSE_SWEEP_SHARED_TOTAL_BYTES 36864u",
                      "#define DSA_SCHEDULE_READ_BEAT_CYCLES 1u",
                      "#define DSA_SCHEDULE_QUANT_GROUP_SETUP_CYCLES 2u"):
            self.assertIn(value, header)
        caps = {address:(value,mask) for address,value,mask in capability_expectations(p)}
        self.assertEqual(caps[0x0f4], (64,0xffffffff))
        self.assertEqual(caps[0x0f0], (2048,0xffffffff))
        self.assertEqual(caps[0x124], (0x01100037,0xffffffff))
        self.assertEqual(caps[0x104], (4096,0xffffffff))
        self.assertEqual(caps[0x134], (32768,0xffffffff))
        p = normalize_profile(manifest(),root=ROOT)
        self.assertEqual(dict((a,(v,m)) for a,v,m in capability_expectations(p))[0x124],
                         (0x01100017,0xffffffdf))


if __name__ == "__main__":
    unittest.main()
