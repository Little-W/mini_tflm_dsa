"""验证读地址间隔限制、默认逐周期接受和两侧握手一致性。"""
from pathlib import Path
import os
import re
import shutil
import subprocess
import tempfile
import unittest

from run_storage_operators import ar_interval_monitor


class OperatorAddressIntervalTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        verilator = os.environ.get("VERILATOR") or shutil.which("verilator")
        if not verilator:
            raise RuntimeError("Set VERILATOR to run the address interval simulation")
        cls.temporary = tempfile.TemporaryDirectory(prefix="operator_ar_interval_")
        root = Path(cls.temporary.name)
        source = root / "tb.sv"
        source.write_text("""
module tb;
    logic clk = 0, rst_n = 0, arvalid = 1, arready;
    bit stall_memory;
    integer drive_cycle = 0;
    always #1 clk = !clk;
""" + ar_interval_monitor() + """
    assign memory_arready = !stall_memory || (drive_cycle % 3 != 1);
    initial begin
        stall_memory = $test$plusargs("STALL_MEMORY");
        repeat (2) @(negedge clk);
        rst_n = 1;
        for (drive_cycle = 0; drive_cycle < 12; drive_cycle++) @(negedge clk);
        $finish;
    end
    always @(posedge clk) if (rst_n && arvalid && arready)
        $display("ACCEPT cycle=%0d", drive_cycle);
endmodule
""")
        command = [verilator, "--binary", "--timing", "--assert", "-Wno-fatal",
                   "--top-module", "tb", "--Mdir", str(root / "obj"),
                   "-j", "1", str(source)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=120)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        cls.binary = root / "obj/Vtb"

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def simulate(self, *arguments):
        result = subprocess.run([str(self.binary), *arguments], capture_output=True,
                                text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        cycles = [int(value) for value in re.findall(r"ACCEPT cycle=(\d+)", result.stdout)]
        match = re.search(r"COMMON_AR_INTERVAL minimum=(\d+) required=(\d+) accepted=(\d+)",
                          result.stdout)
        self.assertIsNotNone(match, result.stdout)
        minimum, required, accepted = map(int, match.groups())
        self.assertEqual(accepted, len(cycles))
        self.assertEqual(minimum, min(b - a for a, b in zip(cycles, cycles[1:])))
        self.assertGreaterEqual(minimum, required)
        return cycles

    def test_default_accepts_each_cycle(self):
        self.assertEqual(self.simulate(), list(range(12)))

    def test_requested_intervals(self):
        for interval in (1, 2, 3):
            with self.subTest(interval=interval):
                self.assertEqual(self.simulate(f"+AR_MIN_INTERVAL={interval}"),
                                 list(range(0, 12, interval)))

    def test_memory_backpressure_preserves_both_handshakes(self):
        self.assertEqual(self.simulate("+AR_MIN_INTERVAL=2", "+STALL_MEMORY"),
                         [0, 2, 5, 8, 11])

    def test_zero_interval_is_rejected(self):
        result = subprocess.run([str(self.binary), "+AR_MIN_INTERVAL=0"],
                                capture_output=True, text=True, timeout=15)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Read address interval must be positive", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
