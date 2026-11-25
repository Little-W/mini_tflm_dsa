#!/usr/bin/env python3
"""证明位置边界寄存结果在消费者读取时对应当前任务。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import runpy
import shlex
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/fpga"))
from open_fpga_synth import run_stage


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    control_path = ROOT / "rtl/npu/conv/vector_engine_control.sv"
    checker_path = ROOT / "rtl/npu/conv/vector_config_check.sv"
    originals = {str(path): digest(path) for path in (control_path, checker_path)}

    control = control_path.read_text()
    for declaration in (
        "  input wire logic [31:0] i_position_next,",
        "  input wire logic [63:0] i_position_count,",
        "  input wire logic i_config_check_done,",
        "  input wire logic i_config_check_error,",
    ):
        if control.count(declaration) != 1:
            raise ValueError("控制模块的形式连接声明不完整")
        control = control.replace(declaration, "")
    control = control.replace("  input wire logic clk,",
                              "  input wire logic clk,\n  input wire logic [47:0] proof_product,", 1)
    declarations = """
  logic [31:0] i_position_next;
  logic [63:0] i_position_count;
  logic i_config_check_done, i_config_check_error;
  logic [31:0] proof_position_count;
  logic proof_checker_ready;
  logic proof_valid = 1'b0;
"""
    assertions = """
  assign i_position_next = o_position + 32'd1;
  assign i_position_count = {32'd0, proof_position_count};
  vector_config_check_proof #(
      .TILE(p_tile), .MAX_TAPS(p_max_taps), .POOL_MAX_TAPS(p_pool_max_taps)
  ) u_proof_checker (
      .clk(clk), .rst_n(rst_n), .start(state==vector_engine_control_pkg::CHECK),
      .cfg(c), .i_input_range(global_pool), .ready(proof_checker_ready),
      .done(i_config_check_done), .error(i_config_check_error),
      .position_count(proof_position_count), .kernel_count(), .input_bytes(),
      .output_bytes(), .weight_bytes(), .o_read_end(), .proof_product(proof_product)
  );
  always_ff @(posedge clk) begin
    if (!rst_n) proof_valid <= 1'b0;
    else begin
      proof_valid <= 1'b1;
      if (proof_valid) begin
        if (state!=vector_engine_control_pkg::IDLE && state!=vector_engine_control_pkg::CHECK &&
            state!=vector_engine_control_pkg::CHECK_WAIT && state!=vector_engine_control_pkg::FAILED &&
            state!=vector_engine_control_pkg::DONE) assert(proof_checker_ready);
        if (state==vector_engine_control_pkg::DW_FINISH || state==vector_engine_control_pkg::OUTPUT_NEXT)
          assert(position_has_more == (position_next < 32'(position_count)));
        if (state==vector_engine_control_pkg::DW_FINISH && dw_snapshot_fire)
          assert(o_position_is_last == (position_next == 32'(position_count)));
      end
    end
  end
"""
    control = control.replace("\n);", "\n);\n" + declarations, 1)
    control = control.replace("\nendmodule", "\n" + assertions + "\nendmodule", 1)
    control_file = out / "controller.sv"
    control_file.write_text(control)

    checker = checker_path.read_text().replace("module vector_config_check #(",
                                               "module vector_config_check_proof #(")
    checker = checker.replace("  input logic clk,rst_n,start,",
                              "  input logic clk,rst_n,start,\n  input logic [47:0] proof_product,")
    product_definition = "wire [47:0] product_q={product_upper,multiply_low[15:0]};"
    if checker.count(product_definition) != 1:
        raise ValueError("描述符检查模块的乘积声明不完整")
    # 任意乘积扩大数值范围；状态转移、数据更新使能和完成信号使用实际 RTL。
    checker = checker.replace(product_definition, "wire [47:0] product_q=proof_product;")
    checker_file = out / "checker.sv"
    checker_file.write_text(checker)
    reader = runpy.run_path(str(ROOT / "scripts/rtl/source_files.py"))
    sources = reader["with_dependencies"]([control_file, checker_file], ROOT)
    inputs = reader["input_files"](sources, ROOT)
    summary = {"passed": False, "source_sha256": originals,
               "proof_input_sha256": {str(path): digest(path) for path in inputs},
               "method": "Temporal induction with the RTL controller and configuration checker",
               "multiplier_results": "arbitrary 48-bit input values", "cases": []}
    for bus_width, pe_count, shared in ((64, 8, 1), (32, 4, 0)):
        name = f"axi{bus_width}_pe{pe_count}"
        script = out / (name + ".ys")
        script.write_text(
            "read_slang --top vector_engine_control "
            f"-Gp_bus_width={bus_width} -Gp_pe_count={pe_count} "
            f"-Gp_window_lanes={bus_width // 8} -Gp_shared_storage_enable={shared} " +
            " ".join(shlex.quote(str(path)) for path in sources) + "\n"
            "delete -output vector_engine_control/w:*\n"
            "setattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n"
            "prep -top vector_engine_control -flatten\nasync2sync\nopt -full\n"
            "chformal -lower\nopt_clean\n"
            "sat -seq 1 -tempinduct -initsteps 3 -maxsteps 12 "
            "-set-at 1 rst_n 0 -prove-asserts -verify\n"
        )
        result = run_stage(script, script.with_suffix(".log"), dict(os.environ))
        if "Induction step proven: SUCCESS" not in script.with_suffix(".log").read_text():
            raise RuntimeError("位置边界时序关系的归纳证明未完成")
        summary["cases"].append({"name": name, "passed": True, **result})
        print("VECTOR_POSITION_PIPELINE_FORMAL_PASS", name, flush=True)
    if originals != {str(path): digest(path) for path in (control_path, checker_path)}:
        raise RuntimeError("形式检查期间 RTL 源文件发生变化")
    summary["passed"] = True
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    main()
