// SPDX-License-Identifier: Apache-2.0
module requant_configuration_npu_observer #(
    parameter bit p_serial = 1'b0
);
    if (p_serial) begin : g_serial
        logic group_active_q = 1'b0;
        logic [137:0] group_configuration_q = '0;
        wire [137:0] current_configuration = {
            vec_requant_full.s16_mode,
            vec_requant_full.serial_per_channel_q,
            vec_requant_full.is_mode_r,
            vec_requant_full.activation_min_r,
            vec_requant_full.activation_max_r,
            vec_requant_full.dst_offset_r,
            vec_requant_full.pt_product_multiplier_r,
            vec_requant_full.pt_product_amount_r
        };
        longint unsigned configurations = 0;
        longint unsigned groups = 0;
        longint unsigned pending_cycles = 0;

        // 正常命令须先排空整组输出；中止由 core_rst_n 清除整组状态。
        always @(posedge vec_requant_full.clk) begin
            if (!vec_requant_full.rst_n) begin
                group_active_q <= 1'b0;
            end else if (vec_requant_full.init_cfg) begin
                assert(vec_requant_full.g_serial_arithmetic.u_group_buffer.pending_rows_q == 0);
                assert(!vec_requant_full.i_group_start);
                group_active_q <= 1'b0;
                configurations <= configurations + 1;
            end else if (vec_requant_full.i_group_start) begin
                assert(vec_requant_full.o_group_ready);
                group_configuration_q <= current_configuration;
                group_active_q <= 1'b1;
                groups <= groups + 1;
            end else if (vec_requant_full.g_serial_arithmetic.u_group_buffer.pending_rows_q != 0) begin
                assert(group_active_q && current_configuration == group_configuration_q);
                pending_cycles <= pending_cycles + 1;
            end else begin
                group_active_q <= 1'b0;
            end
        end
        final $display("REQUANT_CONFIGURATION_NPU_PASS configurations=%0d groups=%0d pending_cycles=%0d",
                       configurations, groups, pending_cycles);
    end
endmodule

bind vec_requant_full requant_configuration_npu_observer #(
    .p_serial(p_compute_lanes < VLEN)
) u_requant_configuration_observer();
