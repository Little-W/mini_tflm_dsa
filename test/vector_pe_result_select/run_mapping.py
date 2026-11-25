#!/usr/bin/env python3
"""以器件功能模型比较映射后的八通道 PE 与实际 RTL。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mapped", type=Path, required=True)
    parser.add_argument("--cells-sim", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cycles", type=int, default=4096)
    parser.add_argument("--verilator", default="verilator")
    args = parser.parse_args()
    mapped = args.mapped.resolve()
    model = args.cells_sim.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = ROOT / "rtl/npu/conv/vector_pe.sv"
    manifest = json.loads((mapped / "manifest.json").read_text())
    if manifest["sources_sha256"].get("vector_pe.sv") != digest(source):
        raise ValueError("映射输入与当前 PE 源码不同")
    netlist = mapped / "mapped.v"
    hashes = {str(path): digest(path) for path in (source, netlist, model)}
    bench = out / "mapped_comparison.sv"
    bench.write_text(r'''
`timescale 1ns/1ps
module tb #(parameter int p_cycles=4096);
  logic clk=0, i_en=0;
  logic [2:0] i_op=0;
  logic [127:0] i_a=0, i_b=0;
  logic [255:0] i_acc=0;
  wire [255:0] mapped_result, rtl_result;
  logic [31:0] rng=32'h4a1180c3;
  integer checks=0, holds=0;
  pe_array u_mapped(.clk,.i_en,.i_op,.i_a,.i_b,.i_acc,.o_result(mapped_result));
  for (genvar lane=0; lane<8; lane++) begin : g_rtl
    // 升序非打包数组经展开后，通道零对应打包端口的最高位段。
    vector_pe #(.ENABLE_EXTENDED_MULTIPLY(1'b0)) u_pe(
      .clk,.i_en,.i_op,.i_a(i_a[16*(7-lane)+:16]),.i_b(i_b[16*(7-lane)+:16]),
      .i_acc(i_acc[32*(7-lane)+:32]),.o_result(rtl_result[32*(7-lane)+:32]));
  end
  initial begin
    for (integer sample=0; sample<p_cycles; sample++) begin
      i_en=(sample==0 || sample%7!=0);
      i_op=3'(sample);
      for (integer bit_index=0; bit_index<512; bit_index++) begin
        rng=rng^(rng<<13); rng=rng^(rng>>17); rng=rng^(rng<<5);
        if (bit_index<128) i_a[bit_index]=rng[0];
        else if (bit_index<256) i_b[bit_index-128]=rng[0];
        else i_acc[bit_index-256]=rng[0];
      end
      if (sample%31==0) begin
        i_a={16'h8000,16'h7fff,16'hffff,16'h0000,16'h0001,16'hff80,16'h007f,16'h8001};
        i_b=~i_a;
        i_acc={32'h80000000,32'h7fffffff,32'hffffffff,32'h00000000,
               32'h00000001,32'hffff8000,32'h00007fff,32'hffff007f};
      end
      #5; clk=1; #5;
      if (mapped_result !== rtl_result) $fatal(1,"Mapped PE mismatch sample=%0d",sample);
      checks+=8;
      if (!i_en) holds+=8;
      clk=0;
    end
    $display("PE_RESULT_MAPPED_PASS cycles=%0d checks=%0d hold_checks=%0d",p_cycles,checks,holds);
    $finish;
  end
endmodule
''')
    binary = out / "obj/Vtb"
    command = [args.verilator, "--binary", "--timing", "-j", "1", "--output-groups", "0",
               "-Wno-fatal", "--top-module", "tb", f"-Gp_cycles={args.cycles}",
               "--Mdir", str(out / "obj"), "-CFLAGS", "-std=c++20 -O1",
               str(model), str(source), str(netlist), str(bench)]
    with (out / "compile.log").open("w") as stream:
        subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, check=True)
    result = subprocess.run([str(binary)], capture_output=True, text=True,
                            check=True, timeout=240)
    (out / "run.log").write_text(result.stdout + result.stderr)
    match = re.search(r"PE_RESULT_MAPPED_PASS cycles=(\d+) checks=(\d+) hold_checks=(\d+)", result.stdout)
    if not match:
        raise RuntimeError("映射后功能检查未完成")
    if hashes != {name: digest(Path(name)) for name in hashes}:
        raise RuntimeError("检查期间输入源码发生变化")
    report = dict(passed=True, cycles=int(match[1]), compared_outputs=int(match[2]),
                  hold_checks=int(match[3]), source_sha256=hashes,
                  compile_command=command, test_sha256=digest(bench),
                  primitive_models="Complete Xilinx cells_sim.v, including DSP48E1 arithmetic")
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(match[0])


if __name__ == "__main__":
    main()
