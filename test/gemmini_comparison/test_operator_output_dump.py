"""验证实际系统内存输出的字节顺序、边界和文件长度。"""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest

from run_storage_operators import output_tensor_dump


class OperatorOutputDumpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        verilator = os.environ.get("VERILATOR") or shutil.which("verilator")
        if not verilator:
            raise RuntimeError("Set VERILATOR to run output tensor checks")
        cls.temporary = tempfile.TemporaryDirectory(prefix="operator_output_dump_")
        cls.root = Path(cls.temporary.name)
        source = cls.root / "tb.sv"
        source.write_text("""
module memory;
    logic [31:0] mem[4];
endmodule
module tb;
    localparam int WORDS=4;
    memory u_mem();
""" + output_tensor_dump() + """
    initial begin
        u_mem.mem[0]=32'h8000ff7f;
        u_mem.mem[1]=32'h010a0d00;
        u_mem.mem[2]=32'hfe42ccaa;
        u_mem.mem[3]=32'hf0f1f2f3;
        write_output_tensor();
        $finish;
    end
endmodule
""")
        result = subprocess.run([verilator, "--binary", "--assert", "-Wno-fatal",
                                 "--top-module", "tb", "--Mdir", str(cls.root / "obj"),
                                 "-j", "1", str(source)], capture_output=True, text=True, timeout=120)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        cls.binary = cls.root / "obj/Vtb"

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def simulate(self, base, count):
        target = self.root / "output.bin"
        result = subprocess.run([str(self.binary), "+OUTPUT_DUMP=" + str(target),
                                 f"+OUTPUT_BASE={base:x}", f"+OUTPUT_BYTES={count}"],
                                capture_output=True, text=True, timeout=15)
        return result, target

    def test_all_byte_values_keep_little_endian_word_order(self):
        result, target = self.simulate(0, 16)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(target.read_bytes(), bytes.fromhex("7fff0080000d0a01aacc42fef3f2f1f0"))

    def test_unaligned_range_crosses_word_boundaries(self):
        result, target = self.simulate(3, 7)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(target.read_bytes(), bytes.fromhex("80000d0a01aacc"))

    def test_empty_range_creates_empty_output(self):
        result, target = self.simulate(16, 0)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(target.read_bytes(), b"")

    def test_range_beyond_memory_is_rejected(self):
        result, unused = self.simulate(15, 2)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Output tensor exceeds system memory", result.stdout + result.stderr)

    def test_integer_wrap_is_rejected(self):
        result, unused = self.simulate(0xffffffff, 2)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Output tensor exceeds system memory", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
