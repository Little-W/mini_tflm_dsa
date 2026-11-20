#!/usr/bin/env python3
"""证明实际三写端口来源表的逐行状态关系，并运行四状态仿真。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "rtl/npu/dma/cache/conv_read_cache.sv"


def audit_integration(current, reference):
    """核对来源表的全部连接，并比较来源存储以外的模块文本。"""
    bindings = """    assign rank_source_i_clear_en = rst_n && metadata_enable && clearing;
    assign rank_source_i_hit_valid = hit_update && (windowed_q || hint_valid);
    assign rank_source_i_read_en = !select_stage_valid;
"""
    if bindings not in current:
        raise ValueError("Rank-table event bindings require verification")
    current = current.replace(bindings, "").replace(
        "    logic rank_source_i_clear_en, rank_source_i_hit_valid, rank_source_i_read_en;\n", "")
    current = current.replace(".i_clear_en(rank_source_i_clear_en)", ".i_clear_en(rst_n && metadata_enable && clearing)")
    current = current.replace(".i_hit_valid(rank_source_i_hit_valid)", ".i_hit_valid(hit_update && (windowed_q || hint_valid))")
    current = current.replace(".i_read_en(rank_source_i_read_en)", ".i_read_en(!select_stage_valid)")
    reference_read = re.search(r"    always_ff @\(posedge clk\) begin\n"
        r"      if \(!select_stage_valid\) begin\n"
        r"        rank_source_q <= rank_source\[candidate_set\];\n"
        r"      end\n    end\n", reference).group(0)
    instance_start = current.index("    // 三个写入来源保留独立端口")
    instance_end = current.index("    );\n", instance_start) + len("    );\n")
    instance = current[instance_start:instance_end]
    expected = """    // 三个写入来源保留独立端口，同步读取组合后的来源编码。
    conv_cache_rank_table #(.p_depth(SETS), .p_addr_width(SI)) u_rank_source (
      .clk(clk), .i_clear_en(rst_n && metadata_enable && clearing), .i_clear_addr(clear_set),
      .i_write_en(rst_n), .i_fill_valid(fill_update), .i_fill_addr(fill_set),
      .i_hint_valid(hint_update), .i_hint_addr(hint_set),
      .i_hit_valid(hit_update && (windowed_q || hint_valid)), .i_hit_addr(lookup_set),
      .i_read_en(!select_stage_valid), .i_read_addr(candidate_set), .o_read_data(rank_source_q)
    );
"""
    if instance != expected:
        raise ValueError("Rank-table connections require verification")
    old_start = reference.index("    for(genvar metadata_set=0;")
    old_end = reference.index("  end\n\n  always_ff", old_start)
    old_rows = reference[old_start:old_end]
    new_start = current.index("`ifdef NPU_SIM_ASSERT\n    for (genvar metadata_set=0;")
    new_end = current.index("  end\n\n  always_ff", new_start)
    new_rows = current[new_start:new_end]
    old_assertion = old_rows[old_rows.index("      initial forever"):old_rows.index("`endif")]
    new_assertion = new_rows[new_rows.index("      initial forever"):new_rows.index("    end\n`endif")]
    if old_assertion != new_assertion:
        raise ValueError("Valid metadata checks changed")
    normalized = current.replace(instance, reference_read).replace(new_rows, old_rows)
    normalized = normalized.replace("`ifdef NPU_SIM_ASSERT\n    wire [1:0] rank_source [SETS];\n`endif\n",
                                    "    logic [1:0] rank_source [SETS];\n")
    table_start = normalized.index("// 三个存储体的异或值表示替换来源")
    table_end = normalized.index("/* verilator lint_on DECLFILENAME */", table_start)
    normalized = normalized[:table_start] + normalized[table_end:]
    if normalized != reference:
        raise ValueError("Additional cache changes require verification")
    return dict(remaining_module_body_identical=True, storage_connections_checked=True,
                valid_metadata_assertions_identical=True,
                reference_sha256=hashlib.sha256(reference.encode()).hexdigest())


def audit_named_connections(current, reference):
    """展开具名组合连接，逐字检查其对应的完整缓存逻辑。"""
    normalized = current
    for line in (
        "    logic rank_source_i_clear_en, rank_source_i_hit_valid, rank_source_i_read_en;\n",
        "    assign rank_source_i_clear_en = rst_n && metadata_enable && clearing;\n",
        "    assign rank_source_i_hit_valid = hit_update && (windowed_q || hint_valid);\n",
        "    assign rank_source_i_read_en = !select_stage_valid;\n",
        "  logic bank_i_wr_mask;\n  logic [2:0] bank_i_rd_en;\n\n",
        "  assign bank_i_wr_mask = 1'b1;\n  assign bank_i_rd_en = 3'b111;\n",
    ):
        if normalized.count(line) != 1:
            raise ValueError("Named connection definition requires verification")
        normalized = normalized.replace(line, "")
    for name, value in (
        ("rank_source_i_clear_en", "rst_n && metadata_enable && clearing"),
        ("rank_source_i_hit_valid", "hit_update && (windowed_q || hint_valid)"),
        ("rank_source_i_read_en", "!select_stage_valid"),
        ("bank_i_wr_mask", "1'b1"), ("bank_i_rd_en", "3'b111"),
    ):
        normalized = normalized.replace("(" + name + ")", "(" + value + ")")
    if normalized != reference:
        raise ValueError("Named connection expansion differs from the reference logic")
    return dict(passed=True, remaining_module_body_identical=True,
                reference_sha256=hashlib.sha256(reference.encode()).hexdigest())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--iverilog", default="iverilog")
    parser.add_argument("--vvp", default="vvp")
    parser.add_argument("--reference-ref", default="24d2fdf6")
    parser.add_argument("--connection-reference-ref")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = SOURCE.read_text()
    reference = subprocess.check_output(["git", "show", args.reference_ref + ":" +
        str(SOURCE.relative_to(ROOT))], cwd=ROOT, text=True)
    integration = audit_integration(current, reference)
    connection_comparison = None
    if args.connection_reference_ref:
        connection_reference = subprocess.check_output(["git", "show", args.connection_reference_ref + ":" +
            str(SOURCE.relative_to(ROOT))], cwd=ROOT, text=True)
        connection_comparison = audit_named_connections(current, connection_reference)
        connection_comparison["reference_ref"] = args.connection_reference_ref
    table = current[current.index("module conv_cache_rank_table #("):]
    table = table[:table.index("endmodule") + len("endmodule")]
    if "  assign bank_i_wr_mask = 1'b1;\n  assign bank_i_rd_en = 3'b111;" not in table:
        raise ValueError("Rank-table storage enables require verification")
    for connection in (".i_wr_mask(bank_i_wr_mask)", ".i_rd_en(bank_i_rd_en)",
                       ".i_wr_addr(bank_i_wr_addr[bank])", ".i_wr_data(bank_i_wr_data[bank])",
                       ".i_rd_addr(bank_i_rd_addr[bank])", ".o_rd_data(bank_o_rd_data[bank])"):
        if connection not in table:
            raise ValueError("Rank-table storage connection requires verification: " + connection)
    declaration_end = re.search(r"^\);", table, re.M).end()
    prelude = table[declaration_end:table.index("  for (genvar bank=0;")]
    model = out / "rank_banks_proof.sv"
    model.write_text("""module rank_banks_proof #(
parameter integer p_depth=128,p_addr_width=$clog2(p_depth)
) (
input logic i_clear_en,i_write_en,i_fill_valid,i_hint_valid,i_hit_valid,
input logic [p_addr_width-1:0] i_clear_addr,i_fill_addr,i_hint_addr,i_hit_addr,i_read_addr,
input logic [2:0][p_depth-1:0][1:0] storage,
output logic equivalent
);
""" + prelude + """
logic [p_depth-1:0] row_equal;
for(genvar bank=0;bank<3;bank++) begin:g_read_bank
  for(genvar port_index=0;port_index<3;port_index++) begin:g_read_port
    assign bank_o_rd_data[bank][port_index]=storage[bank][bank_i_rd_addr[bank][port_index]];
  end
end
for(genvar row=0;row<p_depth;row++) begin:g_row
  wire [1:0] bank0_next=bank_i_wr_en[0] && bank_i_wr_addr[0]==p_addr_width'(row) ?
    bank_i_wr_data[0] : storage[0][row];
  wire [1:0] bank1_next=bank_i_wr_en[1] && bank_i_wr_addr[1]==p_addr_width'(row) ?
    bank_i_wr_data[1] : storage[1][row];
  wire [1:0] bank2_next=bank_i_wr_en[2] && bank_i_wr_addr[2]==p_addr_width'(row) ?
    bank_i_wr_data[2] : storage[2][row];
  wire [1:0] current_value=storage[0][row]^storage[1][row]^storage[2][row];
  wire [1:0] reference_next=(i_clear_en && i_clear_addr==p_addr_width'(row)) ? 2'd0 :
    (!i_clear_en && i_write_en && i_fill_valid && i_fill_addr==p_addr_width'(row)) ? 2'd0 :
    (!i_clear_en && i_write_en && i_hint_valid && i_hint_addr==p_addr_width'(row)) ? 2'd1 :
    (!i_clear_en && i_write_en && i_hit_valid && i_hit_addr==p_addr_width'(row)) ? 2'd2 : current_value;
  assign row_equal[row]=(bank0_next^bank1_next^bank2_next)==reference_next;
end
assign equivalent=&row_equal;
endmodule
""")
    cases = []
    for depth in (2, 8, 128):
        script = out / f"depth{depth}.ys"
        script.write_text(f"read_slang --top rank_banks_proof -Gp_depth={depth} " + shlex.quote(str(model)) +
                          "\nprep -top rank_banks_proof -flatten\nsat -verify -prove equivalent 1\n")
        log = out / f"depth{depth}.log"
        with log.open("w") as stream:
            subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"), "--worker", str(script)],
                           cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
        if "SAT proof finished - no model found: SUCCESS!" not in log.read_text():
            raise RuntimeError("Rank table proof incomplete")
        cases.append(dict(depth=depth, compared_bits=2*depth, passed=True,
                          log_sha256=hashlib.sha256(log.read_bytes()).hexdigest()))
        print(json.dumps(cases[-1]), flush=True)
    binary = out / "four_state"
    bench = ROOT / "test/cache_storage/tb_rank_banks.sv"
    command = [args.iverilog, "-g2012", "-s", "tb_rank_banks", "-o", str(binary),
               str(bench), str(SOURCE), str(ROOT / "rtl/common/REGFILE.v")]
    with (out / "compile.log").open("w") as log:
        subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    run = subprocess.run([args.vvp, str(binary)], cwd=ROOT, capture_output=True, text=True)
    log = out / "four_state.log"
    log.write_text(run.stdout + run.stderr)
    run.check_returncode()
    passed = re.search(r"RANK_BANK_FOUR_STATE_PASS cycles=(\d+) state_bits=(\d+)", run.stdout)
    if passed is None:
        raise RuntimeError("Four-state comparison incomplete")
    if current != SOURCE.read_text():
        raise RuntimeError("Cache changed during verification")
    report = dict(passed=True, source_sha256=hashlib.sha256(current.encode()).hexdigest(),
        reference_ref=args.reference_ref, integration=integration,
        named_connections=connection_comparison,
        table_sha256=hashlib.sha256(table.encode()).hexdigest(), inputs_constrained=False,
        formal_cases=cases, formal_compared_bits=sum(case["compared_bits"] for case in cases),
        model_sha256=hashlib.sha256(model.read_bytes()).hexdigest(),
        four_state=dict(cycles=int(passed[1]),state_bits=int(passed[2]),
                        bench_sha256=hashlib.sha256(bench.read_bytes()).hexdigest(),
                        log_sha256=hashlib.sha256(log.read_bytes()).hexdigest()))
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
