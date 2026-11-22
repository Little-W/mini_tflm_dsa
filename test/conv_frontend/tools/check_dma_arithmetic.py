#!/usr/bin/env python3
"""对预读跨行坐标和配置部分积累加的实际 RTL 进行全部输入比较。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'test/frontend_pipeline'))
from source_sections import read_module, declarations


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    frontend_path, frontend = read_module(root, 'prefetch')
    predictor_path = root / "rtl/npu/dma/cache/conv_next_use_predictor.sv"
    prefix_path = root / "rtl/common/parallel_prefix_add.sv"
    predictor = predictor_path.read_text()
    start = frontend.index("  assign prefetch_wrap_i_a =")
    end = frontend.index("  // 核行片段和跨步窗口", start)
    coordinate_logic = declarations(frontend, ('prefetch_next_x', 'prefetch_wrapped_x',
        'prefetch_wrap_base', 'prefetch_wrap_base_q', 'prefetch_wrap_i_a',
        'prefetch_wrap_i_b', 'unused_prefetch_x_carry'))+frontend[start:end]
    coordinate_logic = coordinate_logic.replace("32'(pfa_x)", "input_x")
    coordinate_logic = coordinate_logic.replace("32'(accepted_coordinate_q[0])", "input_x")
    coordinate_logic = coordinate_logic.replace("c.input_w", "input_w")
    accumulator_logic = "\n".join(re.search(pattern, predictor, re.S).group(0) for pattern in (
        r"  logic \[47:0\] cfg_accumulate_addend;",
        r'  \s*logic \[47:0\] cfg_accumulated_upper;',
        r"  assign cfg_accumulate_addend = .*?;",
        r"  assign cfg_accumulated_upper = .*?;",
    ))
    for assignment in ("cfg_product_accumulator", "cfg_product"):
        if assignment + " <= {cfg_accumulated_upper, cfg_product_accumulator[15:0]};" not in predictor:
            raise RuntimeError("Partial product result connection is missing")
    proof = out / "dma_arithmetic.sv"
    proof.write_text("""module dma_arithmetic_proof (
    input logic [31:0] input_x, pf_step_q,
    input logic [15:0] input_w,
    input logic [63:0] cfg_product_accumulator,
    input logic [31:0] cfg_partial_product,
    input logic [3:0] cfg_multiply_phase,
    output logic equivalent
);
""" + coordinate_logic + "\n" + accumulator_logic + """
    logic [31:0] reference_wrap;
    logic [63:0] reference_accumulation;
    assign prefetch_wrap_base_q = prefetch_wrap_base;
    assign reference_wrap = input_x + pf_step_q - {16'd0, input_w};
    assign reference_accumulation = cfg_product_accumulator +
        (cfg_multiply_phase == 4'd8 ? {cfg_partial_product, 32'd0} :
                                    {16'd0, cfg_partial_product, 16'd0});
    assign equivalent = prefetch_wrapped_x == reference_wrap &&
        {cfg_accumulated_upper, cfg_product_accumulator[15:0]} == reference_accumulation;
endmodule
""")
    snapshot_prefix = out / prefix_path.name
    snapshot_prefix.write_bytes(prefix_path.read_bytes())
    summary = {"inputs_constrained": False, "input_bits": 180,
               "source_sha256": {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
                                 for path in (frontend_path, predictor_path, prefix_path)},
               "proof_sha256": hashlib.sha256(proof.read_bytes()).hexdigest(), "runs": []}
    for fpga in (0, 1):
        script, log = out / f"fpga{fpga}.ys", out / f"fpga{fpga}.log"
        script.write_text("read_slang --top dma_arithmetic_proof " +
                          ("-D XILINX_FPGA=1 " if fpga else "") +
                          shlex.join(map(str, (snapshot_prefix, proof))) + "\n" +
                          "prep -top dma_arithmetic_proof -flatten\ncheck -assert\n" +
                          "sat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
        with log.open("w") as stream:
            subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                            "--worker", str(script)], stdout=stream, stderr=subprocess.STDOUT,
                           check=True, timeout=180)
        if "SAT proof finished - no model found: SUCCESS!" not in log.read_text():
            raise RuntimeError(f"DMA arithmetic comparison did not complete: {log}")
        summary["runs"].append({"xilinx_fpga": bool(fpga), "passed": True,
                                "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest()})
        print(f"DMA_ARITHMETIC_PASS xilinx_fpga={fpga}", flush=True)
    summary["passed"] = True
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    main()
