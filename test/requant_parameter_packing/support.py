"""从实际量化模块提取移位量存储，保留生产逻辑和存储接口。"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
RTL = Path("rtl/npu/writeback/vec_requant.sv")


def amount_storage(source, name="amount_storage"):
    first = source.index("begin : gen_is_parameter_bank")
    last = source.index("  // 连续 DMA 字", first)
    body = source[first:last]
    parameters = "\n".join(re.findall(r"    localparam int (?:BANK_ADDR_W|p_amount_\w+) = .*?;", body))
    declarations = "\n".join(line for line in body.splitlines()
                             if line.strip().startswith("logic ") and
                             ("product_amount_i_" in line or
                              "amount_pair_low;" in line or "amount_read_half;" in line))
    assignments = "\n".join(re.findall(
        r"    assign (?:product_amount_i_\w+|ch_product_amount_is_read\[bank\])\s*=\s*.*?;",
        body, re.S))
    assignments = assignments.replace("ch_product_amount_is_read[bank]", "o_amount")
    state = ""
    if "amount_pair_low" in body:
        begin = body.index("    always_ff", body.index("assign ch_product_amount_is_read[bank]"))
        end = body.index("    // 观察接口", begin)
        state = body[begin:end]
    memory = next(block for block in re.findall(r"    regfile #\(.*?\n    \);", body, re.S)
                  if ") u_product_amount (" in block)
    return f"""module {name} #(parameter int BANK_DEPTH=256) (
    input logic clk,rst_n,init_cfg,
    input logic shift_i_wr_en,write_last,
    input logic [((BANK_DEPTH<=1)?1:$clog2(BANK_DEPTH))-1:0] write_addr,
    input logic [6:0] write_product_amount,
    input logic [((BANK_DEPTH<=1)?1:$clog2(BANK_DEPTH))-1:0] product_multiplier_i_rd_addr,
    output logic [6:0] o_amount
);
{parameters}
{declarations}
{assignments}
{state}
{memory}
endmodule
"""
