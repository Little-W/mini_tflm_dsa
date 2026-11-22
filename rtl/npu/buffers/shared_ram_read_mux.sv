// SPDX-License-Identifier: Apache-2.0
`default_nettype none
`timescale 1ns/1ps

// 按低位选择组内数据，再由高位选择对应组。
module shared_ram_read_mux #(
    parameter int p_width = 128,
    parameter int p_inputs = 7,
    parameter int p_select_width = $clog2(p_inputs)
) (
    input  wire logic [p_width-1:0] i_data [p_inputs],
    input  wire logic [p_select_width-1:0] i_select,
    output logic [p_width-1:0] o_data
);
    //! 0. 辅助定义
    //! -----------

    localparam int p_groups = (p_inputs <= 8) ? 2 : 4;

    //! 1. 选择存储返回数据
    //! -------------------

    if (p_inputs > 4 && p_inputs <= 16) begin : g_grouped
        logic [p_width-1:0] group_data [p_groups];
        logic [p_width-1:0] padded_data [4*p_groups];
        for (genvar bank = 0; bank < 4*p_groups; bank++) begin : g_pad
            if (bank < p_inputs) begin : g_present
                assign padded_data[bank] = i_data[bank];
            end else begin : g_unused
                assign padded_data[bank] = '0;
            end
        end
        for (genvar group_index = 0; group_index < p_groups; group_index++) begin : g_group
            // 二级二选一表达组内选择，组间只读取已选中的数据。
            assign group_data[group_index] = i_select[1] ?
                (i_select[0] ? padded_data[4*group_index+3] : padded_data[4*group_index+2]) :
                (i_select[0] ? padded_data[4*group_index+1] : padded_data[4*group_index]);
        end
        if (p_inputs <= 8) begin : g_eight
            assign o_data = group_data[i_select[2]];
        end else begin : g_sixteen
            assign o_data = group_data[i_select[3:2]];
        end
    end else begin : g_direct
        assign o_data = i_data[i_select];
    end
endmodule

`default_nettype wire
