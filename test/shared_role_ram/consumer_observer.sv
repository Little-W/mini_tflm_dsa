// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 检查生产消费者仅在本次存储配置已完成相应读取后使用 IA 或部分和返回数据。
module shared_role_consumer_observer #(
    parameter bit p_enabled = 1'b0,
    parameter bit p_vector_enabled = 1'b0
);
    if (p_enabled) begin : g_shared
        logic [1:0] ia_read_seen = '0;
        logic [3:0] ps_read_seen = '0;
        longint unsigned configurations = 0, ia_consumptions = 0, ps_consumptions = 0;
        longint unsigned weight_consumptions = 0, quant_consumptions = 0, quant_held_cycles = 0;

        initial begin
            assert (npu_top.g_shared_ia_ps.g_channels.u_ram.p_independent_read_data)
                else $fatal(1, "Independent shared RAM response mode is required");
        end
        always @(posedge npu_top.clk) begin
            if (!npu_top.core_rst_n || npu_top.g_shared_ia_ps.ram_i_cfg_valid) begin
                ia_read_seen <= '0;
                ps_read_seen <= '0;
                if (npu_top.g_shared_ia_ps.ram_i_cfg_valid) configurations++;
            end else if (npu_top.g_shared_ia_ps.g_channels.u_ram.memory_access_enabled) begin
                ia_read_seen <= ia_read_seen | npu_top.g_shared_ia_ps.ram_i_ia_read_en;
                ps_read_seen <= ps_read_seen | npu_top.g_shared_ia_ps.ram_i_ps_read_en;
            end
            if (npu_top.core_rst_n && !npu_top.abort_pending) begin
                if (npu_top.u_matrix_engine.u_ia_loader.u_cache_mgr.read_metadata_q[1].valid) begin
                    assert (!npu_top.g_shared_ia_ps.ram_i_cfg_valid && ia_read_seen[0] &&
                        (npu_top.u_matrix_engine.u_ia_loader.u_cache_mgr.read_metadata_q[1].compact || ia_read_seen[1]))
                        else $fatal(1, "Input row consumed before a read in the current configuration");
                    ia_consumptions++;
                end
                if (npu_top.u_matrix_engine.u_compute_core.u_ps_buffer.g_compressed.u_store.decoded_i_wr_en) begin
                    assert (!npu_top.g_shared_ia_ps.ram_i_cfg_valid && (&ps_read_seen))
                        else $fatal(1, "Partial sums consumed before a read in the current configuration");
                    ps_consumptions++;
                end
            end
        end
        if (p_vector_enabled) begin : g_vector
            always @(posedge npu_top.clk) begin
                if (npu_top.core_rst_n && !npu_top.abort_pending) begin
                    if (npu_top.g_vector_engine.u_engine.u_operand_store.g_shared_weights.return_matches) begin
                        assert (!npu_top.g_shared_ia_ps.ram_i_cfg_valid && ia_read_seen[0])
                            else $fatal(1, "Vector weights consumed before a read in the current configuration");
                        weight_consumptions++;
                    end
                    if (npu_top.g_vector_engine.u_engine.dw_quant_start ||
                        (!npu_top.g_vector_engine.u_engine.SHARED_QUANT_ENABLE &&
                         npu_top.g_vector_engine.u_engine.dw_quant_input_active &&
                         npu_top.g_vector_engine.u_engine.q_issue<npu_top.g_vector_engine.u_engine.q_count)) begin
                        assert (!npu_top.g_shared_ia_ps.ram_i_cfg_valid && (&ps_read_seen))
                            else $fatal(1, "Vector quantization consumed before a read in the current configuration");
                        quant_consumptions++;
                        if (!npu_top.g_vector_engine.u_engine.i_ps_read_valid) quant_held_cycles++;
                    end
                end
            end
        end
        final begin
            $display("SHARED_ROLE_CONSUMER_PASS configurations=%0d ia=%0d ps=%0d weights=%0d quant=%0d held_quant=%0d",
                configurations,ia_consumptions,ps_consumptions,weight_consumptions,quant_consumptions,quant_held_cycles);
        end
    end
endmodule

bind npu_top shared_role_consumer_observer #(
    .p_enabled(SHARED_RAM_ENABLED && p_fixed_ps_channels),
    .p_vector_enabled(VECTOR_ENGINE_CAPABLE)
) u_shared_role_consumer_observer();

`default_nettype wire
