#!/usr/bin/env python3
"""用生产倒数表的真实 Verilator AST 检查两种常量写法及参数容量。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from run_formal import unit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.capacity import elaboration


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--verilator", default="verilator-modern")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    production = ROOT/"rtl/npu/conv/vector_engine.sv"
    runs = []
    for maximum in (1, 3, 49, 255, 256, 257):
        bits, address_bits = 9+maximum.bit_length(), maximum.bit_length()
        source = out/f"rom_{maximum}.sv"
        source.write_text(unit(production.read_text()).replace("module reciprocal_unit #(", "module vector_engine #(", 1)+f"""
module npu_axil_top(input logic clk, input logic [{address_bits-1}:0] i_taps,
                    output logic [{bits-1}:0] o_reciprocal);
  vector_engine #(.POOL_MAX_TAPS({maximum})) engine (.*);
endmodule
""")
        for mode, options in (("fpga", []), ("asic", ["-DASIC_SYNTHESIS"])):
            folder = out/f"{mode}_{maximum}"
            folder.mkdir(exist_ok=True)
            tree_path = folder/"elaborated.tree.json"
            command = [args.verilator, "--json-only", "--json-only-output", str(tree_path),
                       "--Mdir", str(folder/"obj"), "--top-module", "npu_axil_top", "-Wno-fatal",
                       *options, str(source)]
            with (folder/"elaboration.log").open("w") as log:
                subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
            result = elaboration.inventory(json.loads(tree_path.read_text()))
            expected = {"vector_pool_reciprocal_rom": (maximum+1)*bits}
            assert result["buffer_arrays_bits"] == result["read_only_arrays_bits"] == expected
            assert result["total_bits"] == (maximum+2)*bits
            assert len(result["read_only_declarations"]) == 1
            assert result["read_only_declarations"][0]["initialization_kinds"] == [
                "initial" if mode == "fpga" else "continuous"]
            runs.append(dict(passed=True, pool_max_taps=maximum, mode=mode,
                             buffer_arrays_bits=result["buffer_arrays_bits"], total_bits=result["total_bits"],
                             declarations=result["read_only_declarations"],
                             tree_sha256=hashlib.sha256(tree_path.read_bytes()).hexdigest()))
            tree_path.unlink()
    summary = dict(passed=True, runs=runs,
        source_sha256={str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                       for path in (production, ROOT/"scripts/capacity/elaboration.py",
                                    ROOT/"scripts/capacity/model.py", Path(__file__).resolve())})
    (out/"summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps(dict(passed=True, checks=len(runs))), flush=True)


if __name__ == "__main__":
    main()
