#!/usr/bin/env python3
"""四态检查容量观察器的配置相位、连续配置与复位采样。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
CONFIGURATION = ROOT / "rtl/npu/top/npu_task_configuration.sv"
LIMITS = ROOT / "rtl/npu/control/ps_capacity_limits.sv"
OBSERVER = Path(__file__).with_name("npu_capacity_observer.sv")


def sequential_block(source, member):
    position = source.index(member)
    start = source.rfind("always_ff", 0, position)
    depth = 0
    for token in re.finditer(r"\bbegin\b|\bend\b", source[start:]):
        depth += 1 if token.group() == "begin" else -1
        if depth == 0:
            block = source[start:start + token.end()]
            if member not in block:
                raise ValueError("Cannot locate sequential member: " + member)
            return block
    raise ValueError("Unterminated sequential block: " + member)


def assignment(source, name):
    found = re.search(r"assign\s+" + re.escape(name) + r"\s*=.*?;", source, re.S)
    if not found:
        raise ValueError("Cannot locate assignment: " + name)
    return found.group()


def generated_group(source, name):
    start = source.index("generate if", source.index(name) - 80)
    end = source.index("endgenerate", start) + len("endgenerate")
    return source[start:end]


def harness(source, binding):
    pieces = [assignment(source, "o_cfg_stage2_fire")]
    pieces += [sequential_block(source, member) for member in (
        "cfg_capacity_phase <= 0;", "ps_rows_bounded <= ps_rows_bounded_calc;",
        "o_ps_admission_rows <= ps_admission_rows_calc;")]
    pieces += [assignment(source, name) for name in (
        "ps_max_frame_rows", "ps_raw_bank_total", "ps_long_frame_words",
        "ps_long_bank_total", "ps_admission_rows_calc", "ps_admission_words")]
    pieces += [generated_group(source, name) for name in (
        "g_ps_bank_reservation", "g_ps_capacity_limits")]
    declarations = []
    names = (
        "ps_rows_bounded", "ps_frames_bounded", "ps_rows_bounded_calc",
        "ps_frames_bounded_calc", "ps_max_frame_rows", "ps_raw_bank_total",
        "ps_raw_frame_bank_words", "ps_raw_bank_capacity_fits", "ps_long_frame_words",
        "ps_long_bank_total", "ps_long_frame_bank_words", "ps_long_bank_capacity_fits",
        "ps_admission_rows_calc", "ps_admission_words", "ps_admission_bank_words",
        "ps_admission_bank_capacity_fits", "cfg_capacity_phase")
    for name in names:
        match = re.search(r"^\s*logic\s+[^;\n]*\b" + name + r"\s*;", source, re.M)
        if not match:
            raise ValueError("Cannot locate declaration: " + name)
        declarations.append(match.group())
    widths = [re.search(r"localparam int " + name + r"\s*=.*?;", source).group()
              for name in ("CAP_ROWS_W", "CAP_FRAMES_W", "CAP_WORDS_W")]
    # 观察器端口从真实 bind 语句生成，仿真工具直接实例化同一模块。
    binding = binding.replace(".i_raw_fits(ps_raw_bank_capacity_fits)", ".i_raw_fits(raw_observed)")
    binding = binding.replace(".i_long_fits(ps_long_bank_capacity_fits)", ".i_long_fits(long_observed)")
    binding = binding.replace(".i_admission_fits(ps_admission_bank_capacity_fits)",
                              ".i_admission_fits(admission_observed)")
    return """`timescale 1ns/1ps
module capacity_phase_tb;
  localparam integer p_shared_ram_enabled=1, p_shared_physical_banks=7;
  localparam integer p_size=16, p_size_shift=4, p_ia_reuse_num_max=32;
  localparam integer p_w_reuse_num_max=16, p_shared_bank_bytes=8192;
  localparam integer PS_REQUIRE_RAW_CAPACITY=1;
""" + "\n".join(widths + declarations) + """
  logic clk=0, rst_n=0;
  logic [2:0] o_cfg_valid_q=0;
  logic i_ctrl_sa_ready=0, i_frame_scheduler_ready=0;
  wire o_cfg_stage2_fire;
  logic [31:0] o_active_ps_bank_count=6;
  wire [31:0] o_active_ps_bank_depth=512;
  wire [2:0] ps_config_word_cap=3'd4;
  logic [31:0] o_frame_slice_tiles_s2;
  logic o_use_frame_commands_s2;
  logic [63:0] o_ps_admission_rows;
  logic [31:0] next_slice;
  logic next_commands;
  integer fault=0, cycles=0, configurations=0, resets=0;
  integer raw_checks=0, long_checks=0, admission_checks=0;
  integer first_unknown=0, consecutive_entries=0, waits=0;
  wire raw_observed=(fault==1 && cfg_capacity_phase==1) ?
    ~ps_raw_bank_capacity_fits : ps_raw_bank_capacity_fits;
  wire long_observed=(fault==2 && cfg_capacity_phase==1) ?
    ~ps_long_bank_capacity_fits : ps_long_bank_capacity_fits;
  wire admission_observed=(fault==3 && cfg_capacity_phase==4) ?
    ~ps_admission_bank_capacity_fits : ps_admission_bank_capacity_fits;
""" + "\n".join(pieces) + "\n" + binding + """
  // 分片字段在相位 2 保存；先前相位允许其保持未知状态。
  always @(posedge clk) begin
    if (o_cfg_valid_q[2] && cfg_capacity_phase==2) begin
      o_frame_slice_tiles_s2 <= next_slice;
      o_use_frame_commands_s2 <= next_commands;
    end
    cycles=cycles+1;
    if (!rst_n) resets=resets+1;
    if (rst_n && o_cfg_valid_q[2]) begin
      if (cfg_capacity_phase==0 && configurations==0) begin
        if ((^ps_rows_bounded)!==1'bx || (^ps_frames_bounded)!==1'bx)
          $fatal(1,"Initial bounded fields must remain unknown before capture");
        first_unknown=first_unknown+1;
      end
      if (o_active_ps_bank_count<7 && cfg_capacity_phase>=1) begin
        raw_checks=raw_checks+1;
        long_checks=long_checks+1;
      end
      if (o_active_ps_bank_count<7 && cfg_capacity_phase>=4)
        admission_checks=admission_checks+1;
      if (cfg_capacity_phase==7 && !o_cfg_stage2_fire) waits=waits+1;
      if (o_cfg_stage2_fire) configurations=configurations+1;
    end
  end
  task tick;
    #2; clk=1; #2; clk=0; #2;
  endtask
  initial begin
    if ($value$plusargs("fault=%d",fault)) begin end
    tick(); tick(); rst_n=1;
    for (integer index=0;index<64;index=index+1) begin
      if (index==32) begin
        o_cfg_valid_q=0; rst_n=0; tick(); tick(); rst_n=1;
      end else if (index!=0) consecutive_entries=consecutive_entries+1;
      o_cfg_valid_q=3'b100;
      i_ctrl_sa_ready=0; i_frame_scheduler_ready=0;
      case (index%8)
        0: o_active_ps_bank_count=6;
        1: o_active_ps_bank_count=5;
        2: o_active_ps_bank_count=3;
        3: o_active_ps_bank_count=0;
        4: o_active_ps_bank_count=4;
        5: o_active_ps_bank_count=2;
        6: o_active_ps_bank_count=7;
        7: o_active_ps_bank_count=32'hffffffff;
      endcase
      ps_rows_bounded_calc=CAP_ROWS_W'((index*71+16)%513);
      ps_frames_bounded_calc=CAP_FRAMES_W'((index*7+2)%32);
      next_slice=(index*3)%33; next_commands=index%2;
      o_frame_slice_tiles_s2='x; o_use_frame_commands_s2='x;
      repeat(7) tick();
      if (cfg_capacity_phase!==3'd7) $fatal(1,"Unexpected phase before submission");
      repeat(2) tick();
      i_ctrl_sa_ready=1; i_frame_scheduler_ready=1; tick();
      if (cfg_capacity_phase!==3'd0) $fatal(1,"Unexpected phase after submission");
    end
    o_cfg_valid_q=0; tick();
    if (configurations!=64 || first_unknown!=1 || consecutive_entries!=62 ||
        raw_checks!=432 || long_checks!=432 || admission_checks!=288 || waits!=128)
      $fatal(1,"Phase coverage incomplete");
    $display("{\\"passed\\":true,\\"cycles\\":%0d,\\"configurations\\":%0d,\\"reset_edges\\":%0d,\\"initial_unknown_checks\\":%0d,\\"consecutive_entries\\":%0d,\\"raw_checks\\":%0d,\\"long_checks\\":%0d,\\"admission_checks\\":%0d,\\"waits\\":%0d}",
      cycles,configurations,resets,first_unknown,consecutive_entries,
      raw_checks,long_checks,admission_checks,waits);
    $finish;
  end
endmodule
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--iverilog", default="iverilog")
    parser.add_argument("--vvp", default="vvp")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    observer, binding = OBSERVER.read_text().split("bind npu_task_configuration ", 1)
    binding = binding.split("`default_nettype wire", 1)[0]
    module_file = out / "observer_module.sv"
    module_file.write_text(observer + "\n`default_nettype wire\n")
    tb = out / "capacity_phase_tb.sv"
    tb.write_text(harness(CONFIGURATION.read_text(), binding))
    binary = out / "capacity_phase.vvp"
    with (out / "build.log").open("w") as log:
        subprocess.run([args.iverilog, "-g2012", "-s", "capacity_phase_tb", "-o", str(binary),
                        str(module_file), str(tb), str(LIMITS)], cwd=ROOT,
                       stdout=log, stderr=subprocess.STDOUT, check=True)
    passed = subprocess.run([args.vvp, str(binary)], text=True, capture_output=True, timeout=30)
    (out / "run.log").write_text(passed.stdout + passed.stderr)
    passed.check_returncode()
    result = json.loads(next(line for line in passed.stdout.splitlines() if line.startswith("{")))
    result["enabled_assertion_checks"] = []
    for number, name in enumerate(("Raw", "Long", "Admission"), 1):
        sample = subprocess.run([args.vvp, str(binary), f"+fault={number}"],
                                text=True, capture_output=True, timeout=30)
        (out / f"assertion_{number}.log").write_text(sample.stdout + sample.stderr)
        accepted = sample.returncode != 0 and f"{name} bank capacity differs" in sample.stdout
        if not accepted:
            raise RuntimeError("Expected active capacity assertion: " + name)
        result["enabled_assertion_checks"].append(name.lower())
    result["first_valid_phase"] = {"raw": 1, "long": 1, "admission": 4}
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    result["source_sha256"] = {str(path.relative_to(ROOT)): digest(path)
                               for path in (CONFIGURATION, LIMITS, OBSERVER, Path(__file__))}
    result["generated_sha256"] = {path.name: digest(path) for path in (module_file, tb)}
    (out / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
