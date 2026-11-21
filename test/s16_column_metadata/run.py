#!/usr/bin/env python3
"""验证 S16 FIFO 保存列有效位与末拍索引后的完整接口行为。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("rtl/npu/writeback/vec_s16_to_fifo.sv")
COMMON = Path("rtl/npu/writeback/vec_s8_to_fifo.sv")
ARITHMETIC = Path("rtl/common/parallel_prefix_add.sv")
PROFILES = [(2, 1, 16), (3, 2, 32), (4, 3, 64), (5, 3, 32),
            (8, 4, 32), (16, 4, 64), (16, 3, 32), (16, 4, 128)]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def observed_source(text, current, include_invariants=True):
    """保持真实控制过程，比较数据存储的完整读写接口。"""
    ports = """    output logic fifo_full_flag,
    input wire logic [VLEN*16-1:0] formal_read_data,
    output wire logic [VLEN*16-1:0] formal_write_data,
    output wire logic [31:0] formal_read_addr, formal_write_addr,
    output wire logic formal_read_enable, formal_write_enable
);"""
    text, count = re.subn(r"    output logic\s+fifo_full_flag\n\);", ports, text)
    if count != 1:
        raise ValueError("无法定位 FIFO 完整接口")
    interface = """assign ram_rd_data = formal_read_data;
    assign formal_write_data = in_vec_s16;
    assign formal_write_addr = 32'(ram_wr_addr);
    assign formal_read_addr = 32'(ram_rd_addr);
    assign formal_write_enable = in_valid && !write_bank_blocked;
    assign formal_read_enable = ram_read_en;"""
    text, count = re.subn(r"    vec_s8_fifo_row_ram\s*#\(.*?\)\s*u_ram\s*\(.*?\);",
                         interface, text, flags=re.S)
    if count != 1:
        raise ValueError("无法定位唯一的数据存储实例")
    columns = "valid_columns_q[column]" if current else "column < int'(output_col_count)"
    relations = f"""
    (* keep *) wire [COUNT_WIDTH-1:0] formal_last_beat = last_beat_idx_cur;
    (* keep *) wire [((1 << BEAT_WIDTH) * ELEMENTS_PER_BEAT)-1:0] formal_columns;
    for (genvar column = 0; column < ((1 << BEAT_WIDTH) * ELEMENTS_PER_BEAT); column++) begin : g_formal_columns
        assign formal_columns[column] = {columns};
    end
    localparam int p_formal_state_width = BANK_COUNT_WIDTH + COUNT_WIDTH +
        2*BANK_WIDTH + 2*PTR_WIDTH + BEAT_WIDTH + 4 + BANKS;
    (* keep *) wire [p_formal_state_width-1:0] formal_state = {{
        ready_bank_count_q, active_read_count_q, write_bank, read_bank,
        write_ptr, read_ptr, beat_idx, stream_active, data_valid,
        ram_read_valid_q, oa_fifo_req, bank_ready}};
    (* keep *) wire [BANKS*COUNT_WIDTH-1:0] formal_bank_counts;
    for (genvar bank = 0; bank < BANKS; bank++) begin : g_formal_bank_counts
        assign formal_bank_counts[bank*COUNT_WIDTH+:COUNT_WIDTH] = bank_count[bank];
    end
"""
    if include_invariants:
        relations += """
    always_comb begin
        assert (write_bank < BANKS);
        assert (read_bank < BANKS);
    end
"""
    return text.replace("endmodule", relations + "\nendmodule", 1)


def four_state_bench(vlen, banks, bus):
    return f"""module tb;
    localparam VLEN={vlen}, BANKS={banks}, BUS_WIDTH={bus};
    logic clk=0, rst_n=0, in_valid=0, in_tile_done=0, output_ready=0;
    logic [VLEN*16-1:0] in_vec_s16=0, formal_read_data=0;
    logic [31:0] reserve_banks=0, i_ready_bank_threshold=0;
    logic [$clog2(VLEN)-1:0] vec_valid_num_col=0;
    wire [1:0] oa_fifo_req, output_valid, output_row_switch, fifo_full_flag;
    wire [BUS_WIDTH/8-1:0] output_mask[2];
    wire [BUS_WIDTH-1:0] output_data[2];
    wire [VLEN*16-1:0] formal_write_data[2];
    wire [31:0] formal_read_addr[2], formal_write_addr[2];
    wire [1:0] formal_read_enable, formal_write_enable;
    logic [31:0] random_state=32'h19d4ba63;
    integer cycle, bit_index;
    task automatic advance;
        random_state = random_state ^ (random_state << 13);
        random_state = random_state ^ (random_state >> 17);
        random_state = random_state ^ (random_state << 5);
    endtask
    function automatic logic symbol(input logic [4:0] value);
        case (value)
            5'd0: symbol=1'bx;
            5'd1: symbol=1'bz;
            default: symbol=value[0];
        endcase
    endfunction
    reference_fifo #(.VLEN(VLEN),.BANKS(BANKS),.BUS_WIDTH(BUS_WIDTH)) u_reference (
        .clk,.rst_n,.in_valid,.in_tile_done,.in_vec_s16,.reserve_banks,.i_ready_bank_threshold,
        .vec_valid_num_col,.output_ready,.formal_read_data,
        .oa_fifo_req(oa_fifo_req[0]),.output_valid(output_valid[0]),
        .output_row_switch(output_row_switch[0]),.output_mask(output_mask[0]),
        .output_data(output_data[0]),.fifo_full_flag(fifo_full_flag[0]),
        .formal_write_data(formal_write_data[0]),.formal_write_addr(formal_write_addr[0]),
        .formal_read_addr(formal_read_addr[0]),.formal_write_enable(formal_write_enable[0]),
        .formal_read_enable(formal_read_enable[0]));
    current_fifo #(.VLEN(VLEN),.BANKS(BANKS),.BUS_WIDTH(BUS_WIDTH)) u_current (
        .clk,.rst_n,.in_valid,.in_tile_done,.in_vec_s16,.reserve_banks,.i_ready_bank_threshold,
        .vec_valid_num_col,.output_ready,.formal_read_data,
        .oa_fifo_req(oa_fifo_req[1]),.output_valid(output_valid[1]),
        .output_row_switch(output_row_switch[1]),.output_mask(output_mask[1]),
        .output_data(output_data[1]),.fifo_full_flag(fifo_full_flag[1]),
        .formal_write_data(formal_write_data[1]),.formal_write_addr(formal_write_addr[1]),
        .formal_read_addr(formal_read_addr[1]),.formal_write_enable(formal_write_enable[1]),
        .formal_read_enable(formal_read_enable[1]));
    task automatic compare_outputs;
        if ({{oa_fifo_req[0],output_valid[0],output_row_switch[0],output_mask[0],output_data[0],
              fifo_full_flag[0],formal_write_data[0],formal_write_addr[0],formal_read_addr[0],
              formal_write_enable[0],formal_read_enable[0]}} !==
            {{oa_fifo_req[1],output_valid[1],output_row_switch[1],output_mask[1],output_data[1],
              fifo_full_flag[1],formal_write_data[1],formal_write_addr[1],formal_read_addr[1],
              formal_write_enable[1],formal_read_enable[1]}})
            $fatal(1,"S16 interface mismatch at cycle %0d",cycle);
    endtask
    initial begin
        #2; clk=1; #2; clk=0; compare_outputs();
        for (cycle=0;cycle<20000;cycle++) begin
            advance(); rst_n=(cycle%127)!=0;
            in_valid=symbol(random_state[4:0]); in_tile_done=symbol(random_state[9:5]);
            output_ready=symbol(random_state[14:10]);
            reserve_banks=random_state[19:15]; i_ready_bank_threshold=random_state[24:20];
            for (bit_index=0;bit_index<$clog2(VLEN);bit_index++) begin
                advance(); vec_valid_num_col[bit_index]=symbol(random_state[4:0]);
            end
            for (bit_index=0;bit_index<VLEN*16;bit_index++) begin
                advance(); in_vec_s16[bit_index]=symbol(random_state[4:0]);
                formal_read_data[bit_index]=symbol(random_state[9:5]);
            end
            #2; compare_outputs(); clk=1; #2; compare_outputs(); clk=0;
        end
        $display("PASS S16 four-state cycles=%0d checks=%0d",cycle,2*cycle+1);
        $finish;
    end
endmodule
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference", default="0097b66e")
    parser.add_argument("--four-state", action="store_true")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = (ROOT / SOURCE).read_text()
    reference = subprocess.check_output(
        ["git", "show", f"{args.reference}:{SOURCE.as_posix()}"], cwd=ROOT, text=True)
    helpers = (ROOT / COMMON).read_text()
    watermark = re.search(r"module fifo_bank_watermark\b.*?endmodule", helpers, re.S)[0]
    common = out / "watermark.sv"
    common.write_text(watermark + "\n")
    sources = {}
    for label, text in (("reference", reference), ("current", current)):
        transformed = observed_source(text, label == "current", not args.four_state)
        if args.four_state:
            transformed = transformed.replace("module vec_s16_to_fifo", f"module {label}_fifo", 1)
        sources[label] = out / (label + ".sv")
        sources[label].write_text(transformed)
    report = {"reference": args.reference, "source_sha256": digest(ROOT / SOURCE),
              "reference_sha256": hashlib.sha256(reference.encode()).hexdigest(),
              "common_source_sha256": digest(ROOT / COMMON),
              "arithmetic_source_sha256": digest(ROOT / ARITHMETIC),
              "functional_inputs_constrained": False, "initial_reset_cycle": 1,
              "memory_read_data_constrained": False, "method": "four_state" if args.four_state else "inductive_equivalence",
              "proven_state_invariants": ["write_bank < BANKS", "read_bank < BANKS"],
              "comparison": "全部公开输出、数据存储读写端口及配置计算关系", "runs": []}
    for vlen, banks, bus in PROFILES:
        folder = out / f"v{vlen}_n{banks}_b{bus}"
        folder.mkdir(exist_ok=True)
        log = folder / "result.log"
        row = {"vlen": vlen, "banks": banks, "bus_width": bus}
        if args.four_state:
            bench = folder / "tb.sv"
            bench.write_text(four_state_bench(vlen, banks, bus))
            binary = folder / "simulation"
            with log.open("w") as stream:
                subprocess.run(["iverilog", "-g2012", "-s", "tb", "-o", str(binary),
                                *map(str, sources.values()), str(common), str(ROOT / ARITHMETIC), str(bench)],
                               stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=60)
                subprocess.run(["vvp", str(binary)], stdout=stream, stderr=subprocess.STDOUT,
                               check=True, timeout=120)
            result = log.read_text()
            if "PASS S16 four-state cycles=20000 checks=40001" not in result or re.search(r"ERROR:|FATAL:", result):
                raise RuntimeError("四态接口检查未完成")
            row.update(cycles=20000, four_state_checks=40001)
        else:
            commands = []
            for label, path in sources.items():
                commands += [f"read_slang --top vec_s16_to_fifo -GVLEN={vlen} -GBANKS={banks} "
                             f"-GBUS_WIDTH={bus} " + shlex.join([str(path), str(common), str(ROOT / ARITHMETIC)]),
                             "prep -top vec_s16_to_fifo -flatten", "async2sync", "memory_map", "opt -full",
                             "expose vec_s16_to_fifo/w:formal_columns vec_s16_to_fifo/w:formal_last_beat "
                             "vec_s16_to_fifo/w:formal_state vec_s16_to_fifo/w:formal_bank_counts",
                             "rename vec_s16_to_fifo " + label, "design -stash " + label]
            commands += ["design -copy-from reference -as reference reference",
                         "design -copy-from current -as current current",
                         "miter -equiv -make_assert reference current comparison",
                         "prep -top comparison -flatten", "opt -full", "check -assert",
                         "sat -seq 2 -prove-skip 1 -prove-asserts -verify -set-def-inputs "
                         "-set-init-def -set-at 1 in_rst_n 0",
                         "sat -seq 1 -tempinduct-inductonly -tempinduct-def -maxsteps 4 -prove-asserts "
                         "-verify -set-def-inputs -set-init-def"]
            script = folder / "formal.ys"
            script.write_text("\n".join(commands) + "\n")
            with log.open("w") as stream:
                subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                                "--worker", str(script)], stdout=stream, stderr=subprocess.STDOUT,
                               cwd=ROOT, check=True, timeout=300)
            result = log.read_text()
            if ("SAT proof finished - no model found: SUCCESS!" not in result or
                    "Induction step proven: SUCCESS!" not in result):
                raise RuntimeError("完整接口与状态证明未完成")
            row.update(reset_base_case_passed=True, unbounded_induction_passed=True)
        row.update(passed=True, log_sha256=digest(log))
        report["runs"].append(row)
        print(json.dumps(row), flush=True)
    if (report["source_sha256"] != digest(ROOT / SOURCE) or
            report["common_source_sha256"] != digest(ROOT / COMMON) or
            report["arithmetic_source_sha256"] != digest(ROOT / ARITHMETIC)):
        raise RuntimeError("检查期间源文件发生变化")
    report["passed"] = True
    (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
