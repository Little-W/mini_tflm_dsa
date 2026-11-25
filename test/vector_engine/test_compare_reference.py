"""检查逐周期比较使用的输入连接与完整端口解析。"""
from pathlib import Path
import tempfile
import unittest

from compare_reference import prepare_reference


class ReferenceConnectionsTest(unittest.TestCase):
    def prepare(self, declaration):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        folder = Path(temporary.name)
        source = folder / "engine.sv"
        source.write_text(declaration)
        files, report = prepare_reference(source, source, folder)
        return files[1].read_text(), report

    def test_wire_inputs_and_outputs(self):
        observer, report = self.prepare("""
module vector_engine #(
  parameter int TILE = 16
) (
  input wire logic clk, rst_n,
  input wire vector_engine_pkg::vector_engine_cfg_t cfg,
  input logic signed [7:0] values[TILE] = '{default:8'sd0},
  output logic ready,
  output logic [31:0] result[TILE]
);
endmodule
""")
        for name in ("clk", "rst_n", "cfg", "values"):
            self.assertIn(f".{name}(vector_engine.{name})", observer)
        for name in ("ready", "result"):
            self.assertIn(f".{name}(reference_{name})", observer)
        self.assertEqual(report["public_ports"], 6)
        self.assertEqual(report["compared_output_ports"], 2)

    def test_unparsed_type_is_rejected(self):
        with self.assertRaises(ValueError):
            self.prepare("""
module vector_engine #(
  parameter int TILE = 16
) (
  input bit clk,
  output logic ready
);
endmodule
""")


if __name__ == "__main__":
    unittest.main()
