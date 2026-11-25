#!/usr/bin/env python3
"""比较完整偏置缓冲区的公开输出、状态、存储内容及四态控制行为。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = "87c506be4d2efde77fd94946a3b98bcdd228d235"
BUFFER = Path("rtl/npu/loaders/bias_loader_buffer.sv")
HELPERS = tuple(Path("rtl/common") / name for name in (
    "parallel_prefix_add.sv", "parallel_unsigned_compare.sv", "add_equal.sv", "regfile.v"))
PROFILES = (
    dict(SIZE=16, BUS_WIDTH=64, REG_WIDTH=32, COUNT_WIDTH=29,
         GROUP_BLOCKS_MAX=16, p_share_load_index=1, p_register_current_range=1),
    dict(SIZE=16, BUS_WIDTH=64, REG_WIDTH=32, COUNT_WIDTH=29,
         GROUP_BLOCKS_MAX=16, p_share_load_index=0, p_register_current_range=1),
    dict(SIZE=16, BUS_WIDTH=64, REG_WIDTH=32, COUNT_WIDTH=29,
         GROUP_BLOCKS_MAX=16, p_share_load_index=0, p_register_current_range=0),
    dict(SIZE=4, BUS_WIDTH=32, REG_WIDTH=8, COUNT_WIDTH=1,
         GROUP_BLOCKS_MAX=1, p_share_load_index=1, p_register_current_range=1),
    dict(SIZE=4, BUS_WIDTH=32, REG_WIDTH=8, COUNT_WIDTH=2,
         GROUP_BLOCKS_MAX=1, p_share_load_index=0, p_register_current_range=1),
    dict(SIZE=16, BUS_WIDTH=64, REG_WIDTH=64, COUNT_WIDTH=64,
         GROUP_BLOCKS_MAX=16, p_share_load_index=1, p_register_current_range=1),
    dict(SIZE=8, BUS_WIDTH=32, REG_WIDTH=16, COUNT_WIDTH=8,
         GROUP_BLOCKS_MAX=3, p_share_load_index=0, p_register_current_range=1),
    dict(SIZE=16, BUS_WIDTH=128, REG_WIDTH=32, COUNT_WIDTH=32,
         GROUP_BLOCKS_MAX=32, p_share_load_index=1, p_register_current_range=1),
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ports(source):
    head = source[:source.index("\n);")]
    pattern = re.compile(
        r"^\s*(input|output)\s+(?:wire\s+)?logic\s+(signed\s+)?"
        r"(\[[^\]]+\]\s*)?(\w+)\s*(\[[^\]]+\])?\s*(?:=\s*[^,]+)?\s*,?\s*$", re.M)
    result = pattern.findall(head)
    if len(result) != len(re.findall(r"^\s*(?:input|output)\s", head, re.M)):
        raise RuntimeError("缓冲区端口未被完整读取")
    return result


def check_expression(name, expression):
    return (f'      if (u_reference.{expression} !== u_current.{expression})\n'
            f'        $fatal(1,"{name} differs sample=%0d phase=%0d",sample,phase);')


def bench(source, parameters, seed):
    declarations, instances, checks = [], [], []
    for direction, signed, width, name, array in ports(source):
        prefix = (signed or "") + (width or "")
        if direction == "input":
            declarations.append(f"  logic {prefix}{name}{array};")
        else:
            for label in ("reference", "current"):
                declarations.append(f"  wire {prefix}{label}_{name}{array};")
            index = "[lane]" if array else ""
            body = (f'      if (reference_{name}{index} !== current_{name}{index})\n'
                    f'        $fatal(1,"output {name} differs sample=%0d phase=%0d",sample,phase);')
            checks.append(f"    for(integer lane=0;lane<SIZE;lane++) begin\n{body}\n    end"
                          if array else body)
    for label in ("reference", "current"):
        connections = ",".join(f".{name}({name if direction == 'input' else label + '_' + name})"
                                for direction, _, _, name, _ in ports(source))
        options = ",".join(f".{name}({value})" for name, value in parameters.items())
        instances.append(f"  {label}_bias_loader_buffer #({options}) u_{label}({connections});")
    state = (
        "load_bank_q", "load_row_index_q", "load_row_high_zero_q", "load_word_col_base_q",
        "load_done_q", "scalar_word_base", "scalar_bank", "scalar_half_q", "ws_cache_valid",
        "ws_cache_bank", "ws_cache_block", "ws_loading", "ws_busy", "ws_issue_count",
        "ws_response_valid", "ws_response_index", "ws_read_base", "storage_i_wr_en",
        "storage_i_wr_addr", "storage_i_rd_addr", "storage_i_wr_data",
        "storage_i_wr_mask", "storage_o_rd_data", "u_storage.read_accept",
    )
    checks.extend(check_expression(name, name) for name in state)
    for name, size in (("bank_loaded", "2"), ("bank_block_idx", "2"), ("bank_end_q", "2"),
                       ("load_word_valid_q", "BUS_WIDTH/8"), ("load_word_data_q", "BUS_WIDTH/8"),
                       ("ws_cache_pair", "READS_PER_BLOCK"), ("u_storage.mem", "RAM_DEPTH")):
        checks.append(f"    for(integer item=0;item<{size};item++) begin\n" +
                      check_expression(name, name + "[item]") + "\n    end")
    if parameters["p_register_current_range"]:
        checks.append(check_expression("resident_bank", "g_registered_current.resident_bank"))
    header = "\n".join(f"  localparam {name}={value};" for name, value in parameters.items())
    return "module tb;\n" + header + "\n" + "\n".join(declarations + instances) + f"""
  localparam DATA_WIDTH=32, DMA_DATA_WIDTH=8;
  localparam READS_PER_BLOCK=(SIZE+1)/2;
  localparam BANK_ADDR_W=(GROUP_BLOCKS_MAX*READS_PER_BLOCK>1)?
      $clog2(GROUP_BLOCKS_MAX*READS_PER_BLOCK):1;
  localparam RAM_DEPTH=2*(1<<BANK_ADDR_W);
  integer seed={seed}, sample=-1, phase=0, checks=0, cycles=0;
  integer simultaneous_load=0, clear_unknown=0, reset_unknown=0;
  integer collision_checks=0, accepted_reads=0, held_reads=0, known_hold_checks=0;
  logic next_rst_n;
  task check;
    begin
      checks++;
      if(u_reference.u_storage.accepted_write===1'b1 &&
         u_reference.read_enable===1'b1 &&
         u_reference.storage_i_rd_addr===u_reference.storage_i_wr_addr) collision_checks++;
      if(u_reference.u_storage.read_accept===1'b1) accepted_reads++;
      if(u_reference.u_storage.read_accept===1'b0) held_reads++;
      if(u_reference.u_storage.read_accept===1'b0 &&
         (^u_reference.storage_o_rd_data===1'b0 ||
          ^u_reference.storage_o_rd_data===1'b1)) known_hold_checks++;
{chr(10).join(checks)}
    end
  endtask
  task cycle;
    begin
      #1; check(); #4; clk=1; #1; check(); #4; clk=0; cycles++;
    end
  endtask
  initial begin
    clk=0; rst_n=0; init_cfg=0; load_start=0; load_bank=0; load_block_idx=0;
    load_blocks_count=0; group_blocks_needed=0; load_word_row=0; load_word_col_base=0;
    load_done=0; active_bank=0; current_block_idx=0; i_current_block_idx_nxt=0;
    i_group_blocks_needed_nxt=0; is_mode=0; group_read_start=0; group_read_idx=0;
    for(integer lane=0;lane<BUS_WIDTH/8;lane++) begin
      load_word_valid[lane]=0; load_word_data[lane]=0;
    end
    cycle(); cycle();
    for(sample=0;sample<8192;sample++) begin
      phase=sample%128;
      next_rst_n=(sample%257)!=0; init_cfg=($random(seed)&31)==0;
      load_start=($random(seed)&7)==0; load_bank=$random(seed);
      load_block_idx={{$random(seed),$random(seed)}};
      load_blocks_count={{$random(seed),$random(seed)}};
      group_blocks_needed={{$random(seed),$random(seed)}};
      load_word_row={{$random(seed),$random(seed)}};
      load_word_col_base=$random(seed); load_done=$random(seed);
      active_bank=$random(seed); current_block_idx={{$random(seed),$random(seed)}};
      i_current_block_idx_nxt={{$random(seed),$random(seed)}};
      i_group_blocks_needed_nxt={{$random(seed),$random(seed)}};
      is_mode=$random(seed); group_read_start=$random(seed); group_read_idx=$random(seed);
      for(integer lane=0;lane<BUS_WIDTH/8;lane++) begin
        load_word_valid[lane]=$random(seed); load_word_data[lane]=$random(seed);
      end
      // 连续装载、完成通知和分组读取覆盖存储内容与银行状态的更新。
      if(phase<80) begin
        next_rst_n=phase!=0; init_cfg=phase==1; load_start=phase==2;
        load_bank=(sample/128)%2; active_bank=load_bank;
        load_block_idx=0; load_blocks_count=GROUP_BLOCKS_MAX; group_blocks_needed=1;
        current_block_idx=0; i_current_block_idx_nxt=0; i_group_blocks_needed_nxt=1;
        load_word_row=((phase/4)%GROUP_BLOCKS_MAX);
        load_word_col_base=(phase*8)%(SIZE*4); load_done=phase==61;
        is_mode=(sample/256)%2; group_read_start=phase==64;
        group_read_idx=phase-64;
        for(integer lane=0;lane<BUS_WIDTH/8;lane++) begin
          load_word_valid[lane]=phase>2 && phase<61;
          load_word_data[lane]=8'(sample+lane*17);
        end
      end
      // 先写入完整数据，再读取并同址更新，检查已有读结果的保持行为。
      if(phase>=32 && phase<56) begin
        load_bank=0; active_bank=0; load_word_row=0;
        load_word_col_base=(BUS_WIDTH==32)?(phase%2)*4:0;
        is_mode=1; group_read_start=0; group_read_idx=0;
        for(integer lane=0;lane<BUS_WIDTH/8;lane++)
          load_word_valid[lane]=phase<40 || phase>=48;
      end
      // 全宽随机输入及 X/Z 控制包含初始化、装载和完成同拍的情况。
      if(phase>=96) begin
        case(phase%16)
          0:init_cfg=1'bx; 1:init_cfg=1'bz;
          2:next_rst_n=1'bx; 3:next_rst_n=1'bz;
          4:load_start=1'bx; 5:load_done=1'bz;
          6:load_bank=1'bx; 7:active_bank=1'bz;
          8:i_current_block_idx_nxt[0]=1'bx;
          9:i_group_blocks_needed_nxt[0]=1'bz;
          10:load_block_idx[0]=1'bx; 11:load_blocks_count[0]=1'bz;
          12:is_mode=1'bx; 13:group_read_start=1'bz;
          14:group_read_idx[0]=1'bx;
          15:begin load_word_valid[0]=1'bz; load_word_data[0][0]=1'bx; end
        endcase
      end
      if(phase==83) begin load_start=1; load_done=1; simultaneous_load++; end
      if(init_cfg===1'bx || init_cfg===1'bz) clear_unknown++;
      if(next_rst_n===1'bx || next_rst_n===1'bz) reset_unknown++;
      // 组合输入先稳定，再施加异步复位事件，随后检查两个时钟相位。
      #1; rst_n=next_rst_n;
      cycle();
    end
    if(collision_checks==0 || accepted_reads==0 || held_reads==0 || known_hold_checks==0)
      $fatal(1,"read collision and hold coverage incomplete");
    $display("BUFFER_FOUR_STATE_PASS cycles=%0d checks=%0d simultaneous_load=%0d clear_unknown=%0d reset_unknown=%0d collision_checks=%0d accepted_reads=%0d held_reads=%0d known_hold_checks=%0d",
        cycles,checks,simultaneous_load,clear_unknown,reset_unknown,collision_checks,accepted_reads,held_reads,known_hold_checks);
    $finish;
  end
endmodule
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--reference", default=REFERENCE)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    revision = subprocess.check_output(["git", "rev-parse", args.reference + "^{commit}"],
                                       cwd=ROOT, text=True).strip()
    originals = {"reference": subprocess.check_output(
        ["git", "show", f"{revision}:{BUFFER}"], cwd=ROOT), "current": (root / BUFFER).read_bytes()}
    models, hashes = [], {}
    for label, data in originals.items():
        text = data.decode()
        for module in re.findall(r"^module\s+(\w+)\b", text, re.M):
            text = re.sub(r"\b" + module + r"\b", label + "_" + module, text)
        model = out / (label + ".sv")
        model.write_text(text)
        models.append(model)
        hashes[label] = hashlib.sha256(data).hexdigest()
        (out / (label + "_source.sv")).write_bytes(data)
    helper_hashes = {}
    for relative in HELPERS:
        data = (root / relative).read_bytes()
        if data != subprocess.check_output(["git", "show", f"{revision}:{relative}"], cwd=ROOT):
            raise RuntimeError(f"公共依赖在两侧不同：{relative}")
        target = out / relative.name
        target.write_bytes(data)
        models.append(target)
        helper_hashes[str(relative)] = digest(target)
    records = []
    for index, parameters in enumerate(PROFILES):
        folder = out / f"profile_{index}"
        folder.mkdir(exist_ok=True)
        testbench = folder / "tb.sv"
        testbench.write_text(bench(originals["reference"].decode(), parameters, 20261125 + index))
        simulation = folder / "simulation.vvp"
        command = ["iverilog", "-g2012", "-DXILINX_FPGA=1", "-s", "tb", "-o", str(simulation),
                   *map(str, models), str(testbench)]
        with (folder / "compile.log").open("w") as stream:
            subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, check=True)
        result = subprocess.run(["vvp", str(simulation)], text=True, capture_output=True, timeout=300)
        log = folder / "run.log"
        log.write_text(result.stdout + result.stderr)
        match = re.search(r"BUFFER_FOUR_STATE_PASS cycles=(\d+) checks=(\d+) simultaneous_load=(\d+) "
                          r"clear_unknown=(\d+) reset_unknown=(\d+) collision_checks=(\d+) "
                          r"accepted_reads=(\d+) held_reads=(\d+) known_hold_checks=(\d+)", result.stdout)
        if result.returncode or match is None:
            raise RuntimeError(str(log))
        record = dict(parameters=parameters, seed=20261125 + index, passed=True,
                      **dict(zip(("cycles", "checks", "simultaneous_load", "clear_unknown",
                                  "reset_unknown", "collision_checks", "accepted_reads", "held_reads",
                                  "known_hold_checks"),
                                 map(int, match.groups()))),
                      testbench_sha256=digest(testbench), run_log_sha256=digest(log))
        records.append(record)
        print(json.dumps(record), flush=True)
    if digest(root / BUFFER) != hashes["current"]:
        raise RuntimeError("验证期间缓冲区源文件发生变化")
    report = dict(passed=True, strict_four_state_equivalence=True, reference_commit=revision,
                  source_sha256=hashes, helper_sha256=helper_hashes, profiles=records,
                  compared="全部公开输出、全部状态寄存器、同步存储内容、写入端口及实际读取资格",
                  internal_state_assumptions=[], runner_sha256=digest(Path(__file__)))
    (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
