"""检查仿真生成文件的清理范围和保留内容。"""
from pathlib import Path
import tempfile
import unittest

from run_storage_operators import clean_build_products


class OperatorBuildProductsTest(unittest.TestCase):
    def exercise_cleanup(self, output, objects, outside):
        generated = (
            "Vtb_latest_operators__part.o", "Vtb_latest_operators__ALL.a",
            "Vtb_latest_operators__pch.h.fast.gch", "Vtb_latest_operators__part.cpp",
            "Vtb_latest_operators.h", "Vtb_latest_operators__part.d",
            "Vtb_latest_operators.mk", "verilated.o", "verilated_threads.d",
        )
        preserved = ("Vtb_latest_operators", "build.json", "compile.log",
                     "unrelated.cpp", "Vtb_latest_operators__verFiles.dat")
        for name in generated + preserved:
            (objects / name).write_text(name)
        (outside / "Vtb_latest_operators__external.cpp").write_text("external")
        (objects / "Vtb_latest_operators__link.cpp").symlink_to(
            outside / "Vtb_latest_operators__external.cpp")
        (objects / "nested").symlink_to(outside, target_is_directory=True)
        result = clean_build_products(output)
        self.assertEqual(result["files_removed"], len(generated))
        self.assertEqual(result["bytes_removed"], sum(len(name) for name in generated))
        for name in generated:
            self.assertFalse((objects / name).exists())
        for name in preserved:
            self.assertEqual((objects / name).read_text(), name)
        self.assertTrue((objects / "Vtb_latest_operators__link.cpp").is_symlink())
        self.assertEqual((outside / "Vtb_latest_operators__external.cpp").read_text(), "external")
        self.assertEqual(clean_build_products(output)["files_removed"], 0)

    def test_only_named_generated_files_are_removed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "result"
            objects = output / "sim" / "obj"
            objects.mkdir(parents=True)
            outside = root / "outside"
            outside.mkdir()
            self.exercise_cleanup(output, objects, outside)

    def test_separate_object_directory_preserves_path_limits(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "result"
            (output / "sim").mkdir(parents=True)
            objects = root / "temporary_objects"
            objects.mkdir()
            (output / "sim" / "obj").symlink_to(objects, target_is_directory=True)
            outside = root / "outside"
            outside.mkdir()
            self.exercise_cleanup(output, objects, outside)

    def test_parent_directory_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "result"
            (output / "sim").mkdir(parents=True)
            (output / "sim" / "obj").symlink_to(output, target_is_directory=True)
            binary = output / "Vtb_latest_operators"
            binary.write_text("simulator")
            with self.assertRaises(ValueError):
                clean_build_products(output)
            self.assertEqual(binary.read_text(), "simulator")


if __name__ == "__main__":
    unittest.main()
