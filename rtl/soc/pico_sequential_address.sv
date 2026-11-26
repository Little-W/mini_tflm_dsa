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

// 顺序地址增加二或四，地址高位的传播条件按四位分组并行计算。
(* keep_hierarchy = "yes" *)
module pico_sequential_address (
    input wire logic [31:0] i_address, // 当前指令地址
    input wire logic i_compressed, // 当前指令采用十六位压缩编码
    output logic [31:0] o_address // 按指令长度推进的顺序地址
);
    (* keep = 1 *) logic [6:0] group_propagate;
    logic [31:0] next_address;
    logic carry_into_two;
    assign carry_into_two = !i_compressed || i_address[1];
    assign next_address[0] = i_address[0];
    assign next_address[1] = i_address[1] ^ i_compressed;
    assign next_address[2] = i_address[2] ^ carry_into_two;
    for (genvar group_index = 0; group_index < 7; group_index++) begin : g_group
        assign group_propagate[group_index] = &i_address[2+group_index*4+:4];
    end
    for (genvar bit_index = 3; bit_index < 32; bit_index++) begin : g_bit
        localparam int p_groups = (bit_index-2)/4;
        localparam int p_local = (bit_index-2)%4;
        logic carry_into_bit;
        if (p_groups == 0) begin : g_first
            assign carry_into_bit = carry_into_two && (&i_address[bit_index-1:2]);
        end else if (p_local == 0) begin : g_boundary
            assign carry_into_bit = carry_into_two && (&group_propagate[p_groups-1:0]);
        end else begin : g_partial
            assign carry_into_bit = carry_into_two && (&group_propagate[p_groups-1:0]) &&
                (&i_address[2+p_groups*4+:p_local]);
        end
        assign next_address[bit_index] = i_address[bit_index] ^ carry_into_bit;
    end
    always_comb begin
        case (^{i_address, i_compressed})
            1'b0, 1'b1: o_address = next_address;
            default: o_address = i_address + (i_compressed ? 32'd2 : 32'd4);
        endcase
    end
endmodule

`default_nettype wire
