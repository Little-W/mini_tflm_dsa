/*
 *  PicoRV32 -- A Small RISC-V (RV32I) Processor Core
 *
 *  Copyright (C) 2015  Claire Xenia Wolf <claire@yosyshq.com>
 *
 *  Permission to use, copy, modify, and/or distribute this software for any
 *  purpose with or without fee is hereby granted, provided that the above
 *  copyright notice and this permission notice appear in all copies.
 *
 *  THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
 *  WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
 *  MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
 *  ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
 *  WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
 *  ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
 *  OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
 *
 */

`timescale 1 ns / 1 ps
`default_nettype none

// 完整操作数的关系按三层三路归并形成，保持原有四态比较语义。
(* keep_hierarchy = "yes" *)
module pico_operand_comparison (
    input wire logic [31:0] i_a, // 第一个完整操作数
    input wire logic [31:0] i_b, // 第二个完整操作数
    output logic o_unsigned_less, // 第一个操作数无符号小于第二个操作数
    output logic o_signed_less // 第一个操作数有符号小于第二个操作数
);
    (* keep = 1 *) logic [10:0] leaf_less, leaf_equal;
    (* keep = 1 *) logic [3:0] first_less, first_equal;
    (* keep = 1 *) logic [1:0] second_less, second_equal;
    logic unsigned_less, signed_less;
    for (genvar group_index = 0; group_index < 11; group_index++) begin : g_leaf
        localparam int p_first = group_index*3;
        localparam int p_width = group_index == 10 ? 2 : 3;
        assign leaf_less[group_index] = i_a[p_first+:p_width] < i_b[p_first+:p_width];
        assign leaf_equal[group_index] = i_a[p_first+:p_width] == i_b[p_first+:p_width];
    end
    for (genvar group_index = 0; group_index < 4; group_index++) begin : g_first
        localparam int p_first = group_index*3;
        if (group_index == 3) begin : g_two
            assign first_less[group_index] = leaf_less[10] || (leaf_equal[10] && leaf_less[9]);
            assign first_equal[group_index] = &leaf_equal[10:9];
        end else begin : g_three
            assign first_less[group_index] = leaf_less[p_first+2] ||
                (leaf_equal[p_first+2] && leaf_less[p_first+1]) ||
                ((&leaf_equal[p_first+2:p_first+1]) && leaf_less[p_first]);
            assign first_equal[group_index] = &leaf_equal[p_first+:3];
        end
    end
    assign second_less[0] = first_less[2] || (first_equal[2] && first_less[1]) ||
        ((&first_equal[2:1]) && first_less[0]);
    assign second_equal[0] = &first_equal[2:0];
    assign second_less[1] = first_less[3];
    assign second_equal[1] = first_equal[3];
    assign unsigned_less = second_less[1] || (second_equal[1] && second_less[0]);
    assign signed_less = i_a[31] != i_b[31] ? i_a[31] : unsigned_less;
    always_comb begin
        case (^{i_a, i_b})
            1'b0, 1'b1: begin
                o_unsigned_less = unsigned_less;
                o_signed_less = signed_less;
            end
            default: begin
                o_unsigned_less = i_a < i_b;
                o_signed_less = $signed(i_a) < $signed(i_b);
            end
        endcase
    end
endmodule

`default_nettype wire
