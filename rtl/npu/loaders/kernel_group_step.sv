// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 计算权重列组步长与复用次数的完整定宽乘积。
(* keep_hierarchy = "yes" *)
module kernel_group_step #(
    parameter int unsigned p_width = 32,
    parameter int unsigned p_count_width = 29
) (
    input wire logic [p_width-1:0] i_step, // 每个权重列组的地址步长
    input wire logic [p_count_width-1:0] i_reuse, // 权重列组复用次数
    (* use_dsp = "yes" *) output logic [p_width-1:0] o_product // 列组步长与复用次数之积
);
    logic [10:0] factor;
    always_comb begin
        case (i_reuse)
            p_count_width'(2): factor = 11'd2;
            p_count_width'(4): factor = 11'd4;
            p_count_width'(8): factor = 11'd8;
            p_count_width'(16): factor = 11'd16;
            p_count_width'(25): factor = 11'd25;
            p_count_width'(32): factor = 11'd32;
            p_count_width'(64): factor = 11'd64;
            p_count_width'(128): factor = 11'd128;
            p_count_width'(256): factor = 11'd256;
            p_count_width'(512): factor = 11'd512;
            p_count_width'(1024): factor = 11'd1024;
            default: factor = 11'd1;
        endcase
    end
    assign o_product = i_step * factor;
endmodule

`default_nettype wire
