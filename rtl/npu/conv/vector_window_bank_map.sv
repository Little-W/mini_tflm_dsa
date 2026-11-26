// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 并行计算八个窗口存储分区的循环起点与来源通道编号。
// 三位进位和借位直接展开，保留按八取模的完整加减法及四态结果。
(* keep_hierarchy = "yes" *)
module vector_window_bank_map (
    input wire logic [2:0] i_base, // 输入存储起点对应的分区编号
    input wire logic [2:0] i_column, // 本拍返回列号除以八的余数
    output logic [2:0] o_first, // 本拍第一项写入的分区编号
    output logic [7:0][2:0] o_source // 每个目标分区选择的返回通道编号
);
    logic [2:0] first_binary, first_reference;
    logic carry1, carry2;
    logic [7:0][2:0] source_binary, source_reference;

    // 低两位并行形成最高位的进位，最高位溢出由定宽模运算舍弃。
    assign carry1 = i_base[0] & i_column[0];
    assign carry2 = (i_base[1] & i_column[1]) |
        ((i_base[1] | i_column[1]) & carry1);
    assign first_binary = {
        i_base[2] ^ i_column[2] ^ carry2,
        i_base[1] ^ i_column[1] ^ carry1,
        i_base[0] ^ i_column[0]
    };
    assign first_reference = i_base + i_column;

    for (genvar bank = 0; bank < 8; bank++) begin : g_bank
        localparam logic [2:0] p_bank = 3'(bank);
        logic borrow1, borrow2;

        // 固定目标编号减去循环起点，结果直接给出该分区的数据来源。
        assign borrow1 = (~p_bank[0]) & first_binary[0];
        assign borrow2 = ((~p_bank[1]) & first_binary[1]) |
            (((~p_bank[1]) | first_binary[1]) & borrow1);
        assign source_binary[bank] = {
            p_bank[2] ^ first_binary[2] ^ borrow2,
            p_bank[1] ^ first_binary[1] ^ borrow1,
            p_bank[0] ^ first_binary[0]
        };
        assign source_reference[bank] = p_bank - first_reference;
    end

    // 未知输入沿用定宽算术的传播结果，二态实现仅保留展开表达式。
    always_comb begin
        case (^{i_base, i_column})
            1'b0, 1'b1: begin
                o_first = first_binary;
                o_source = source_binary;
            end
            default: begin
                o_first = first_reference;
                o_source = source_reference;
            end
        endcase
    end
endmodule

`default_nettype wire
