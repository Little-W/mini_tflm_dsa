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

// 二进制补码由当前位和低位非零条件形成，四位分组控制归并深度。
(* keep_hierarchy = "yes" *)
module pico_result_negation (
    input wire logic [31:0] i_value, // 需要变换符号的完整结果
    output logic [31:0] o_value // 输入结果的三十二位二进制补码
);
    (* keep = 1 *) logic [6:0] group_nonzero;
    logic [31:0] negated_value;
    for (genvar group_index = 0; group_index < 7; group_index++) begin : g_group
        assign group_nonzero[group_index] = |i_value[group_index*4+:4];
    end
    assign negated_value[0] = i_value[0];
    for (genvar bit_index = 1; bit_index < 32; bit_index++) begin : g_bit
        localparam int p_groups = bit_index/4;
        localparam int p_local = bit_index%4;
        logic lower_nonzero;
        if (p_groups == 0) begin : g_first
            assign lower_nonzero = |i_value[bit_index-1:0];
        end else if (p_local == 0) begin : g_boundary
            assign lower_nonzero = |group_nonzero[p_groups-1:0];
        end else begin : g_partial
            assign lower_nonzero = (|group_nonzero[p_groups-1:0]) ||
                (|i_value[p_groups*4+:p_local]);
        end
        assign negated_value[bit_index] = i_value[bit_index] ^ lower_nonzero;
    end
    always_comb begin
        case (^i_value)
            1'b0, 1'b1: o_value = negated_value;
            default: o_value = 32'd0 - i_value;
        endcase
    end
endmodule

`default_nettype wire
