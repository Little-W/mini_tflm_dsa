// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 输出 AXI 突发长度的低八位，独立完成列数与数据宽度的组合编码。
module kernel_burst_encode #(
    parameter int p_width = 32,
    parameter int p_size = 16,
    parameter int p_bus_width = 64
) (
    input  wire logic [p_width-1:0] i_columns,
    input  wire logic i_use16,
    input  wire logic i_tile_packed,
    output logic [7:0] o_length_m1
);
    localparam int p_elements_s8 = p_bus_width / 8;
    localparam int p_elements_s16 = p_bus_width / 16;
    localparam int p_shift_s8 = $clog2(p_elements_s8);
    localparam int p_shift_s16 = $clog2(p_elements_s16);
    logic [p_width-1:0] packed_beats;
    logic [7:0] column_length_m1;

    assign packed_beats = p_width'(p_size/p_elements_s8) << (i_use16 ? 1 : 0);
    if (p_width >= 8+p_shift_s8 && p_elements_s8 > 0 && p_elements_s16 > 0 &&
        (p_elements_s8 & (p_elements_s8-1)) == 0 &&
        (p_elements_s16 & (p_elements_s16-1)) == 0) begin : g_count_encoding
        logic [p_width-1:0] columns_m1;
        assign columns_m1 = i_columns - 1'b1;
        assign column_length_m1 = i_use16 ?
            8'(columns_m1 >> p_shift_s16) : 8'(columns_m1 >> p_shift_s8);
    end else begin : g_narrow_width
        logic [p_width-1:0] beats;
        assign beats = i_use16 ?
            ((i_columns+p_width'(p_elements_s16-1)) >> p_shift_s16) :
            ((i_columns+p_width'(p_elements_s8-1)) >> p_shift_s8);
        assign column_length_m1 = 8'(beats-1);
    end
    assign o_length_m1 = i_tile_packed ? 8'(packed_beats-1) :
        ((i_columns == '0) ? 8'd0 : column_length_m1);
endmodule

`default_nettype wire
