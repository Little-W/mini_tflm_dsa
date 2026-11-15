#!/usr/bin/env python3
"""Small checks for generated cases, stable seeds and external output paths."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from generate_vectors import generate_layers


class GeneratedVectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='conv-source-vectors-')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.out = Path(cls.temp.name)
        cls.primary = generate_layers(cls.out/'primary', ['mnist_cnn_sg0_op0', 'mnist_cnn_sg0_op2'])

    def test_subset_selection_preserves_seed_and_all_vectors(self):
        generated = generate_layers(self.out/'subset', ['mnist_cnn:sg0:op2'])
        a = self.primary['cases']['mnist_cnn_sg0_op2']
        b = generated['cases']['mnist_cnn_sg0_op2']
        for name in ['input.bin','filter.bin','bias.bin','multiplier.bin','shift.bin','output.bin',
                     'init.mem','golden.mem','required.mem','config.mem']:
            with self.subTest(filename=name):
                self.assertEqual((a/name).read_bytes(), (b/name).read_bytes())

    def test_metadata_mode_has_no_numerical_payload(self):
        result = generate_layers(self.out/'metadata', ['mnist_cnn_sg0_op0'], metadata_only=True)
        a, b = result['layers'][0], self.primary['layers'][0]
        self.assertEqual(a['parameters'], b['parameters'])
        self.assertEqual(a['tiling'], b['tiling'])
        self.assertEqual(a['required_unique_input_bytes'], b['required_unique_input_bytes'])
        self.assertIsNone(a['tensors']['output']['sha256'])
        self.assertEqual(result['cases'], {})
        self.assertFalse(list((self.out/'metadata').rglob('*.mem')))
        self.assertFalse(list((self.out/'metadata').rglob('*.bin')))

    def test_explicit_seed_changes_data_preserves_model_geometry(self):
        result = generate_layers(self.out/'newseed', ['mnist_cnn_sg0_op0'], seed=20261116)
        case = result['cases']['mnist_cnn_sg0_op0']
        old = self.primary['cases']['mnist_cnn_sg0_op0']
        self.assertNotEqual((case/'input.bin').read_bytes(), (old/'input.bin').read_bytes())
        self.assertEqual(result['layers'][0]['parameters'], self.primary['layers'][0]['parameters'])
        self.assertEqual(result['layers'][0]['model_layer'], self.primary['layers'][0]['model_layer'])

    def test_soc_images_use_relative_paths_outside_repository(self):
        script = Path(__file__).resolve().parents[1]/'conv_soc_perf/run.py'
        spec = importlib.util.spec_from_file_location('source_vector_soc_runner', script)
        soc = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(soc)
        source = self.primary['cases']['mnist_cnn_sg0_op0']
        a = soc.prepare_case(self.out/'soc_a', 'mnist_cnn_sg0_op0', 0, source)
        b = soc.prepare_case(self.out/'soc_b', 'mnist_cnn_sg0_op0', 0, source)
        self.assertEqual(a['expected_starts'], 25)
        self.assertEqual(a['data_mem_sha256'], b['data_mem_sha256'])
        self.assertEqual((self.out/'soc_a'/a['source_case']).resolve(), source)
        self.assertFalse(Path(a['source_case']).is_absolute())
        self.assertEqual(hashlib.sha256((self.out/'soc_a/data.mem').read_bytes()).hexdigest(), a['data_mem_sha256'])
        self.assertEqual(a['vector_sha256']['output.bin'], self.primary['layers'][0]['tensors']['output']['sha256'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
