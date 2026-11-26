#!/usr/bin/env python3
"""比较完整向量写回模块及其四态源字节选择行为。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import resource
import shlex
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
RTL = Path("rtl/npu/conv/vector_banked_writeback.sv")
PROFILES = [(1, 32, 1, 3), (1, 128, 1, 3), (2, 64, 1, 4),
            (3, 32, 1, 4), (16, 32, 1, 7), (16, 64, 1, 7),
            (16, 128, 1, 7), (64, 64, 1, 9), (3, 32, 0, 4),
            (16, 64, 0, 7), (16, 64, 1, 9)]


def execute(command, log, timeout=600):
    with log.open("w") as output:
        result = subprocess.run(command, cwd=ROOT, stdout=output,
                                stderr=subprocess.STDOUT, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"运行未通过：{log}\n{log.read_text()[-6000:]}")


def simulation_source(source, reference=False):
    """将状态枚举表示为同宽常量，供 Icarus 保留四态条件运算。"""
    old = b"typedef enum logic [1:0] {IDLE, REQUEST, DATA, RESPONSE} state_t;"
    new = (b"typedef logic [1:0] state_t;\n"
           b"  localparam logic [1:0] IDLE=2'd0, REQUEST=2'd1, DATA=2'd2, RESPONSE=2'd3;")
    assert source.count(old) == 1
    result = source.replace(old, new, 1)
    if reference:
        result = result.replace(b"module vector_banked_writeback",
                                b"module vector_banked_writeback_reference", 1)
    return result


def simulation(tile, bus, coalesce, count_width):
    """使用完整模块实例比较公开输出，并遍历源选择的四态输入。"""
    params = (f".TILE({tile}), .BUS_WIDTH({bus}), .COUNT_WIDTH({count_width}), "
              f".p_coalesce_bytes_only({coalesce})")
    common = """.clk, .rst_n, .request_valid, .request_address, .request_bytes,
      .request_byte_output, .result_words, .request_coalesce, .request_last,
      .flush, .wr_granted, .src_wready, .wr_done, .wr_error"""
    outputs = {"request_ready": "", "busy": "", "done": "", "error": "",
               "wr_req": "", "wr_start": "", "wr_base_addr": "[31:0]",
               "wr_row_stride": "[31:0]", "wr_rows_to_write": "[31:0]",
               "wr_burst_len_m1": "[7:0]", "src_wdata": f"[{bus - 1}:0]",
               "src_wmask": f"[{bus // 8 - 1}:0]", "src_wvalid": ""}
    declarations = "\n".join(f"  wire {width} {label}_{port};"
                              for label in ("ref", "dut")
                              for port, width in outputs.items())
    instances = "\n".join(
        f"  {module} #({params}) u_{label} ({common}, " +
        ", ".join(f".{port}({label}_{port})" for port in outputs) + ");"
        for label, module in (("ref", "vector_banked_writeback_reference"),
                              ("dut", "vector_banked_writeback")))
    reference = "{" + ", ".join("ref_" + name for name in outputs) + "}"
    candidate = "{" + ", ".join("dut_" + name for name in outputs) + "}"
    return f"""`timescale 1ns/1ps
`default_nettype none
// 同时驱动两个完整写回模块，比较其公开输出与源数据选择结果。
module tb;
  localparam int TILE = {tile};
  localparam int BUS_WIDTH = {bus};
  localparam int COUNT_WIDTH = {count_width};
  localparam int GROUP_COUNT = (4*TILE + BUS_WIDTH/8 - 1)/(BUS_WIDTH/8);
  localparam int ROW_WIDTH = GROUP_COUNT <= 1 ? 1 : $clog2(GROUP_COUNT);
  logic clk = 0;
  logic rst_n = 0;
  logic request_valid = 0;
  logic [31:0] request_address = 0;
  logic [COUNT_WIDTH-1:0] request_bytes = 0;
  logic request_byte_output = 0;
  logic [32*TILE-1:0] result_words = 0;
  logic request_coalesce = 0, request_last = 0, flush = 0;
  logic wr_granted = 0, src_wready = 0, wr_done = 0, wr_error = 0;
  logic [ROW_WIDTH-1:0] selected_group = 0;
  logic [31:0] random_state = 32'h9e3779b9;
  integer comparisons = 0, cycle_comparisons = 0;
{declarations}
{instances}

  // 固定随机序列用于复现数据位与控制位中的未知值。
  function automatic logic [31:0] next_random(input logic [31:0] value);
    logic [31:0] shifted;
    begin
      shifted = value ^ (value << 13);
      shifted = shifted ^ (shifted >> 17);
      next_random = shifted ^ (shifted << 5);
    end
  endfunction
  function automatic logic four_state(input integer code);
    case (code & 3)
      0: four_state = 1'b0;
      1: four_state = 1'b1;
      2: four_state = 1'bx;
      default: four_state = 1'bz;
    endcase
  endfunction
  task automatic compare_outputs;
    begin
      if ({reference} !== {candidate})
        $fatal(1, "公开输出不一致，比较次数=%0d", comparisons);
      if (u_ref.source_word !== u_dut.source_word)
        $fatal(1, "源选择不一致 group=%b format=%b reference=%h candidate=%h",
               selected_group, request_byte_output, u_ref.source_word, u_dut.source_word);
      comparisons = comparisons + 1;
    end
  endtask
  task automatic fill_data(input integer pattern);
    begin
      for (integer bit_index = 0; bit_index < 32*TILE; bit_index++) begin
        random_state = next_random(random_state);
        case (pattern)
          0: result_words[bit_index] = 1'b0;
          1: result_words[bit_index] = 1'b1;
          2: result_words[bit_index] = 1'bx;
          3: result_words[bit_index] = 1'bz;
          4: result_words[bit_index] = bit_index % 2;
          5: result_words[bit_index] = four_state(bit_index % 4);
          6: result_words[bit_index] = random_state[0];
          default: result_words[bit_index] = four_state(int'(random_state[1:0]));
        endcase
      end
    end
  endtask
  initial begin
    #1; clk = 1; #1; clk = 0; rst_n = 1; #1;
    // 源组号全部四态组合包含补零组及未知索引，不限制公开输入格式。
    force u_ref.source_group = selected_group;
    force u_dut.source_group = selected_group;
    for (integer pattern = 0; pattern < 16; pattern++) begin
      fill_data(pattern);
      for (integer group_code = 0; group_code < (1 << (2*ROW_WIDTH)); group_code++) begin
        for (integer bit_index = 0; bit_index < ROW_WIDTH; bit_index++)
          selected_group[bit_index] = four_state(group_code >> (2*bit_index));
        for (integer format_code = 0; format_code < 4; format_code++) begin
          request_byte_output = four_state(format_code);
          #1; compare_outputs();
        end
      end
    end
    release u_ref.source_group;
    release u_dut.source_group;
    // 恢复实际内部状态更新，以同一序列驱动全部公开输入并逐半周期比较。
    for (integer cycle = 0; cycle < 4096; cycle++) begin
      clk = 0;
      rst_n = cycle % 97 != 0;
      random_state = next_random(random_state);
      request_address = random_state;
      request_bytes = COUNT_WIDTH'(random_state >> 8);
      request_valid = four_state(int'(random_state[1:0]));
      request_byte_output = four_state(int'(random_state[3:2]));
      request_coalesce = four_state(int'(random_state[5:4]));
      request_last = four_state(int'(random_state[7:6]));
      flush = four_state(int'(random_state[9:8]));
      wr_granted = four_state(int'(random_state[11:10]));
      src_wready = four_state(int'(random_state[13:12]));
      wr_done = four_state(int'(random_state[15:14]));
      wr_error = four_state(int'(random_state[17:16]));
      fill_data(cycle % 16);
      #1; compare_outputs();
      clk = 1;
      #1; compare_outputs();
      cycle_comparisons = cycle_comparisons + 1;
    end
    $display("VECTOR_SOURCE_SELECTION_PASS comparisons=%0d cycles=%0d", comparisons, cycle_comparisons);
    $finish;
  end
endmodule
`default_nettype wire
"""


def main():
    global ROOT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT,
                        help="包含待验证 RTL 和参考提交的仓库目录")
    parser.add_argument("--reference-rev", default="685a48415e1848e108552f1bea5072636fe0b9ad")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--reuse-passed", action="store_true",
                        help="仅复用源码、证明脚本与仿真源码完全一致的已通过配置")
    parser.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        from pyosys import libyosys as yosys
        yosys.run_pass("script " + shlex.quote(str(args.worker)))
        print("WORKER_USAGE " + json.dumps({
            "maximum_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "child_maximum_rss_kib": resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss}))
        return
    if args.out is None:
        parser.error("--out is required")
    ROOT = args.repo.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    commit = subprocess.check_output(
        ["git", "rev-parse", args.reference_rev + "^{commit}"], cwd=ROOT, text=True).strip()
    reference_bytes = subprocess.check_output(["git", "show", f"{commit}:{RTL}"], cwd=ROOT)
    reference = out / "reference.sv"
    candidate = ROOT / RTL
    candidate_bytes = candidate.read_bytes()
    sim_reference = out / "reference_sim.sv"
    sim_candidate = out / "candidate_sim.sv"
    if args.reuse_passed:
        assert reference.read_bytes() == reference_bytes
        assert sim_reference.read_bytes() == simulation_source(reference_bytes, reference=True)
        assert sim_candidate.read_bytes() == simulation_source(candidate_bytes)
    reference.write_bytes(reference_bytes)
    sim_reference.write_bytes(simulation_source(reference_bytes, reference=True))
    sim_candidate.write_bytes(simulation_source(candidate_bytes))
    results = []
    for tile, bus, coalesce, count_width in PROFILES:
        params = {"TILE": tile, "BUS_WIDTH": bus,
                  "p_coalesce_bytes_only": coalesce, "COUNT_WIDTH": count_width}
        folder = out / f"tile{tile}_bus{bus}_coalesce{coalesce}_count{count_width}"
        folder.mkdir(exist_ok=True)
        commands = []
        options = " ".join(f"-G{key}={value}" for key, value in params.items())
        for label, source in (("reference", reference), ("candidate", candidate)):
            commands += [
                f"read_slang --top vector_banked_writeback {options} {shlex.quote(str(source))}",
                "prep -top vector_banked_writeback -flatten",
                "memory_map", "async2sync", "opt_clean",
                f"rename vector_banked_writeback {label}", f"design -stash {label}",
            ]
        commands += [
            "design -copy-from reference -as reference reference",
            "design -copy-from candidate -as candidate candidate",
            "equiv_make reference candidate equivalent", "hierarchy -top equivalent",
            "equiv_simple -seq 1", "opt_clean", "equiv_induct -seq 4", "equiv_status -assert",
        ]
        script = folder / "equivalence.ys"
        tb = folder / "tb.sv"
        script_text = "\n".join(commands) + "\n"
        tb_text = simulation(tile, bus, coalesce, count_width)
        proof_log = folder / "equivalence.log"
        simulation_log = folder / "simulation.log"
        reuse = (args.reuse_passed and script.exists() and tb.exists() and
                 proof_log.exists() and simulation_log.exists() and
                 script.read_text() == script_text and tb.read_text() == tb_text and
                 re.search(r"Of those cells \d+ are proven and 0 are unproven",
                           proof_log.read_text()) is not None and
                 "WORKER_USAGE" in proof_log.read_text() and
                 "VECTOR_SOURCE_SELECTION_PASS" in simulation_log.read_text())
        if not reuse:
            script.write_text(script_text)
            execute([sys.executable, str(Path(__file__).resolve()), "--worker", str(script)],
                    proof_log)
        match = re.search(r"Of those cells (\d+) are proven and (\d+) are unproven",
                          (folder / "equivalence.log").read_text())
        assert match and int(match[2]) == 0, folder
        if not reuse:
            tb.write_text(tb_text)
            execute(["iverilog", "-g2012", "-s", "tb", "-o", str(folder / "simulation.vvp"),
                     str(sim_reference), str(sim_candidate), str(tb)], folder / "simulation_build.log")
            execute(["vvp", str(folder / "simulation.vvp")], simulation_log)
        sim = re.search(r"VECTOR_SOURCE_SELECTION_PASS comparisons=(\d+) cycles=(\d+)",
                        (folder / "simulation.log").read_text())
        assert sim, folder
        row = {"parameters": params, "passed": True, "proven_bits": int(match[1]),
               "unproven_bits": int(match[2]), "four_state_comparisons": int(sim[1]),
               "four_state_clock_cycles": int(sim[2]), "folder": str(folder),
               "reused_completed_configuration": bool(reuse),
               "input_sha256": {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                                for path in (script, tb)}}
        results.append(row)
        print(json.dumps(row), flush=True)
    assert candidate.read_bytes() == candidate_bytes
    report = {
        "passed": True, "source_repo": str(ROOT), "reference_commit": commit,
        "reference_path": str(RTL),
        "reference_sha256": hashlib.sha256(reference_bytes).hexdigest(),
        "candidate_path": str(candidate),
        "candidate_sha256": hashlib.sha256(candidate_bytes).hexdigest(),
        "test_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "formal_scope": "完整模块的全部公开输入无约束，比较可匹配状态及所有公开输出。",
        "four_state_scope": "两个完整模块实例比较全部公开输出。源选择遍历组号与格式的全部四态组合，随后使用实际内部状态更新比较自由输入序列。",
        "simulation_representation": "状态枚举按同一 2 位编码展开为逻辑类型和常量，所有控制表达式及条件运算保持原样。",
        "simulation_source_sha256": {
            str(path): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (sim_reference, sim_candidate)},
        "runs": results,
        "four_state_comparisons": sum(row["four_state_comparisons"] for row in results),
        "four_state_clock_cycles": sum(row["four_state_clock_cycles"] for row in results),
    }
    (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
