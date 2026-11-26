// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 根据帧行数计算尾组分块数，保留三十二位加法回绕和配置移位量。
// 二的幂分块尺寸通过高位条件加一形成结果，低位余数直接产生加一使能。
module npu_frame_row_tiles #(
    parameter int unsigned p_tile_size = 16,
    parameter int unsigned p_tile_shift = 4
) (
    input wire logic [31:0] i_rows, // 当前帧的完整行数
    output logic [31:0] o_tiles // 加入分块余量并移位后的分块数
);
    logic [31:0] reference_tiles;
    assign reference_tiles = (i_rows+32'(p_tile_size-1)) >> p_tile_shift;
    if (p_tile_size > 1 && (p_tile_size & (p_tile_size-1)) == 0 &&
        p_tile_shift == $clog2(p_tile_size) && p_tile_shift < 32) begin : g_power_two
        localparam int unsigned p_high_width = 32-p_tile_shift;
        logic [p_high_width-1:0] high_tiles;
        conditional_increment #(.p_width(p_high_width)) u_high (
            .i_value(i_rows[31:p_tile_shift]),
            .i_enable(|i_rows[p_tile_shift-1:0]), .o_result(high_tiles)
        );
        // 未知输入采用完整算术表达式，保持原有四态传播。
        always_comb begin
            case (^i_rows)
                1'b0, 1'b1: o_tiles = {{p_tile_shift{1'b0}}, high_tiles};
                default: o_tiles = reference_tiles;
            endcase
        end
    end else begin : g_general
        assign o_tiles = reference_tiles;
    end
endmodule

`default_nettype wire
