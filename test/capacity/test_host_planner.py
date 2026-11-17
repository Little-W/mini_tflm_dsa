#!/usr/bin/env python3
"""Verify generated MMIO descriptors and complete INT32 reference values."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "veri/top_regression"))
from host_tiling import apply_words, payload_bound, plan_capacity, plan_dispatch


class GeneratorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="shared-generator-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def generate(self, *args, name="case", success=True):
        out = self.directory / name
        run = subprocess.run([sys.executable, str(ROOT / "veri/top_regression/gen_mem.py"),
                              "--out_dir", str(out), *map(str, args)],
                             text=True, capture_output=True, timeout=30)
        if success:
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        else:
            self.assertNotEqual(run.returncode, 0)
        return out

    @staticmethod
    def words(path):
        return [int(s, 16) for s in path.read_text().split()]

    def check_accumulators(self, out):
        c = self.words(out / "config.mem")
        image = b"".join(x.to_bytes(4, "little") for x in self.words(out / "init.mem"))
        signed = lambda value: value - (1 << 32) if value & 0x80000000 else value
        elem = 2 if c[12] else 1
        values = []
        for row in range(c[3]):
            for col in range(c[5]):
                acc = int.from_bytes(image[c[16] + col * 4:c[16] + col * 4 + 4], "little", signed=True) if c[16] else 0
                for red in range(c[4]):
                    a = c[14] + row * c[18] + red * elem
                    b = c[15] + col * c[19] + red
                    lhs = int.from_bytes(image[a:a + elem], "little", signed=True)
                    rhs = int.from_bytes(image[b:b + 1], "little", signed=True)
                    acc += (lhs + signed(c[21])) * (rhs + signed(c[22]))
                values.append(acc & 0xffffffff)
        self.assertEqual(self.words(out / "acc.mem"), values)
        return c, image

    def test_shared_int8_and_int16_full_accumulators(self):
        for dtype, mode, pc in ((1, 0, False), (1, 1, True), (2, 0, True), (2, 1, True)):
            args = ["--pcr-engine", "--size", 16, "--ps_pool_bytes", 4096, "--K", 17, "--N", 35,
                    "--M", 19, "--lhs_dtype", dtype, "--dataflow_mode", mode, "--lhs_zp", 3,
                    "--rhs_zp", -2, "--random", "--random_quant", "--tight_strides", "--mem_words", 8192]
            if pc:
                args.append("--per_channel")
            out = self.generate(*args, name=f"dtype{dtype}_mode{mode}")
            c, _ = self.check_accumulators(out)
            self.assertEqual(c[8], mode)
            self.assertNotEqual(c[16], 0)
            self.assertEqual(c[12:14], [int(dtype == 2), int(pc)])

    def test_data_images_match_between_storage_modes(self):
        args = ["--size", 16, "--K", 17, "--N", 35, "--M", 19, "--lhs_dtype", 2,
                "--dataflow_mode", 1, "--per_channel", "--random", "--random_quant"]
        ordinary = self.generate(*args, name="ordinary")
        adaptive = self.generate(*args, "--pcr-engine", "--ps_pool_bytes", 4096, name="adaptive")
        for name in ("init.mem", "golden.mem", "acc.mem"):
            self.assertEqual((ordinary / name).read_bytes(), (adaptive / name).read_bytes())

    def test_full_range_s16_and_s16_output(self):
        out = self.generate("--pcr-engine", "--size", 16, "--ps_pool_bytes", 4096,
                            "--K", 17, "--N", 35, "--M", 19, "--lhs_dtype", 2,
                            "--int16_output", "--full-range-input", "--dataflow_mode", 2)
        c, image = self.check_accumulators(out)
        self.assertEqual(c[8], 0)
        self.assertEqual(c[28], 1)
        self.assertEqual(int.from_bytes(image[c[14]:c[14] + 2], "little", signed=True), -32768)
        self.assertEqual(int.from_bytes(image[c[14] + 2:c[14] + 4], "little", signed=True), 32767)

    def test_dense_actual_frame_bound_and_single_reduction(self):
        for mode, expected, bound in ((2, (1, 2, 1), 2048), (0, (0, 1, 2), 128)):
            out = self.generate("--pcr-engine", "--size", 16, "--ps_pool_bytes", 4096,
                                "--K", 1, "--N", 800, "--M", 32, "--lhs_dtype", 1,
                                "--dataflow_mode", mode, name=f"dense{mode}")
            cfg = json.loads((out / "config.json").read_text())
            self.assertEqual((cfg["dataflow_mode"], cfg["ia_reuse_num"], cfg["w_reuse_num"]), expected)
            self.assertEqual(cfg["host_tiling"]["payload_bound_bytes"], bound)
        out = self.generate("--pcr-engine", "--size", 16, "--ps_pool_bytes", 4096,
                            "--K", 64, "--N", 9, "--M", 128, "--ia_reuse_num", 2,
                            "--w_reuse_num", 8, name="single_k")
        cfg = json.loads((out / "config.json").read_text())
        self.assertEqual((cfg["ia_reuse_num"], cfg["w_reuse_num"]), (2, 8))
        self.assertEqual(cfg["host_tiling"]["payload_bound_bytes"], 0)

    def test_tail_groups_cover_exact_logical_tiles(self):
        for mode in (0, 1):
            out = self.generate("--pcr-engine", "--size", 16, "--ps_pool_bytes", 16384,
                                "--K", 65, "--N", 17, "--M", 49, "--dataflow_mode", mode,
                                "--no_bias", name=f"tails{mode}")
            c, _ = self.check_accumulators(out)
            rg, cg = c[30] & 65535, c[30] >> 16
            rt, ct = c[31] & 65535, c[31] >> 16
            sr, sc = (c[5], c[3]) if mode else (c[3], c[5])
            self.assertEqual((rg - 1) * c[6] + rt, (sr + 15) // 16)
            self.assertEqual((cg - 1) * c[7] + ct, (sc + 15) // 16)

    def test_descriptor_auto_and_explicit_override(self):
        words = [0] * 32
        words[0:10] = [0x4e505531, 16, 4, 1, 800, 32, 0, 0, 2, 16]
        a, p = apply_words(words, 4096, adaptive=True)
        self.assertEqual(a[6:9], [2, 1, 1])
        self.assertFalse(p["adaptive_active"])
        words[8] = 0
        a, p = apply_words(words, 4096, adaptive=True)
        self.assertEqual(a[6:9], [1, 2, 0])
        self.assertFalse(p["adaptive_active"])

    def test_matrix_rows_and_directory_contexts(self):
        for mode in (False, True):
            for rows, cols in ((1, 32), (17, 49), (65, 127)):
                tiling, meta = plan_capacity(rows, cols, 16, 4, 16,
                                             is_mode=mode, pool_bytes=8192)
                active = min(cols if mode else rows, tiling["ia_reuse"] * 16)
                self.assertEqual(meta["frame_rows"], active)
                self.assertEqual(meta["payload_bound_bytes"], active * tiling["w_reuse"] * 64)
                self.assertEqual(meta["extra_directory_contexts"], 0)
                self.assertEqual(payload_bound(16, tiling["ia_reuse"], tiling["w_reuse"],
                                               cols if mode else rows), meta["payload_bound_bytes"])

    def test_invalid_size_and_pool_are_rejected(self):
        for args in (("--pcr-engine", "--size", 8, "--ps_pool_bytes", 4096),
                     ("--pcr-engine", "--size", 16, "--ps_pool_bytes", 4097),
                     ("--pcr-engine", "--size", 16, "--ps_pool_bytes", 0)):
            self.generate(*args, success=False)

    def test_reuse_25_is_supported_with_per_channel_index_constraint(self):
        a = plan_dispatch(400, 33, 400, 16, 64, 25, 25, 25, 1, True, False,
                          pool_bytes=1 << 20)
        b = plan_dispatch(400, 33, 400, 16, 64, 25, 25, 25, 1, True, True,
                          pool_bytes=1 << 20)
        self.assertEqual((a["tiling"]["ia_reuse"], a["tiling"]["w_reuse"]), (25, 25))
        self.assertEqual((b["tiling"]["ia_reuse"], b["tiling"]["w_reuse"]), (16, 25))


if __name__ == "__main__":
    unittest.main()
