// SPDX-License-Identifier: Apache-2.0
`ifndef SYNTHESIS
/* verilator lint_off DECLFILENAME */
module kernel_loader_observer #(
    parameter int p_count_width = 87
);
    logic [p_count_width-1:0] issued_ref, loaded_ref, sent_ref;
    wire [p_count_width-1:0] waiting_loads = issued_ref - loaded_ref;
    wire [p_count_width-1:0] waiting_sends = issued_ref - sent_ref;
    logic configuration_cleared, command_mode_seen, command_mode_saved;
    logic [1:0] dma_slots;
    longint unsigned checked_cycles = 0;
    longint unsigned initialization_count = 0;
    longint unsigned managed_initialization_count = 0;
    longint unsigned dma_request_count = 0;
    longint unsigned dma_completion_count = 0;
    longint unsigned prefetch_count = 0;
    longint unsigned cache_hit_count = 0;
    longint unsigned flush_count = 0;

    // 参考计数独立保存全部累计值，逐周期检查二位差值计数的对应关系。
    always_ff @(posedge kernel_loader.clk or negedge kernel_loader.rst_n) begin
        if (!kernel_loader.rst_n) begin
            issued_ref <= '0;
            loaded_ref <= '0;
            sent_ref <= '0;
        end else if (!kernel_loader.cache_flush) begin
            if (kernel_loader.u_ctrl.state == 0 && kernel_loader.cfg_valid) begin
                issued_ref <= '0;
                loaded_ref <= '0;
                sent_ref <= '0;
            end else if (kernel_loader.u_ctrl.state == 2) begin
                if (kernel_loader.ctrl_dma_start) issued_ref <= issued_ref + 1'b1;
                if (kernel_loader.dma_done) loaded_ref <= loaded_ref + 1'b1;
                if (kernel_loader.weight_sending_done) sent_ref <= sent_ref + 1'b1;
            end
        end
    end

    // 配置清空和 DMA 返回直接取自实例接口，测试模型不修改这些事件。
    always_ff @(posedge kernel_loader.clk or negedge kernel_loader.rst_n) begin
        if (!kernel_loader.rst_n) begin
            configuration_cleared <= 1'b1;
            command_mode_seen <= 1'b0;
            command_mode_saved <= 1'b0;
            dma_slots <= '0;
        end else begin
            if (kernel_loader.cache_flush) begin
                configuration_cleared <= 1'b1;
                command_mode_seen <= 1'b0;
            end else if (kernel_loader.init_cfg) begin
                configuration_cleared <= 1'b0;
                command_mode_seen <= 1'b1;
                command_mode_saved <= kernel_loader.cfg_command_mode;
            end
            if (kernel_loader.ext_dma_done)
                dma_slots[kernel_loader.ext_dma_wr_slot] <= 1'b0;
            if (kernel_loader.ext_dma_start)
                dma_slots[kernel_loader.ext_dma_slot_id] <= 1'b1;
        end
    end

    always @(posedge kernel_loader.clk) begin
        if (kernel_loader.rst_n) begin
            checked_cycles <= checked_cycles + 1;
            assert (kernel_loader.u_ctrl.issued_count == issued_ref);
            assert (kernel_loader.u_ctrl.loaded_count == loaded_ref);
            assert (kernel_loader.u_ctrl.sent_count == sent_ref);
            if (kernel_loader.u_ctrl.state == 2 && !kernel_loader.cache_flush) begin
                assert (waiting_loads <= 2 && waiting_sends <= 3);
                assert (waiting_loads <= waiting_sends);
                if (kernel_loader.ctrl_dma_start)
                    assert (waiting_loads < 2 && waiting_sends < 3);
                if (kernel_loader.dma_done) assert (waiting_loads != 0);
                if (kernel_loader.weight_sending_done)
                    assert (waiting_sends > waiting_loads);
            end
            if (command_mode_seen && !kernel_loader.cache_flush)
                assert (kernel_loader.cfg_command_mode == command_mode_saved);
            if (kernel_loader.init_cfg && !kernel_loader.cache_flush) begin
                initialization_count <= initialization_count + 1;
                if (kernel_loader.cfg_command_mode)
                    managed_initialization_count <= managed_initialization_count + 1;
                assert (kernel_loader.top_state == 0);
                if (!configuration_cleared)
                    assert (waiting_loads == 0 && waiting_sends == 0);
                assert (!kernel_loader.u_buf.send_active && !kernel_loader.u_buf.send_pending &&
                        !kernel_loader.u_buf.send_prefetch && !kernel_loader.buf_weight_sending_done &&
                        !kernel_loader.weight_sending_done);
            end
            if (kernel_loader.ext_dma_start) begin
                dma_request_count <= dma_request_count + 1;
                assert (!dma_slots[kernel_loader.ext_dma_slot_id] ||
                        (kernel_loader.ext_dma_done &&
                         kernel_loader.ext_dma_wr_slot == kernel_loader.ext_dma_slot_id));
            end
            if (kernel_loader.ext_dma_done) begin
                dma_completion_count <= dma_completion_count + 1;
                assert (dma_slots[kernel_loader.ext_dma_wr_slot]);
            end
            if (kernel_loader.prefetch_dma_start) prefetch_count <= prefetch_count + 1;
            if (kernel_loader.cache_hit_fire) cache_hit_count <= cache_hit_count + 1;
            if (kernel_loader.cache_flush) flush_count <= flush_count + 1;
        end
    end

    final $display("KERNEL_PENDING_PROTOCOL_PASS cycles=%0d init=%0d managed=%0d requests=%0d completions=%0d prefetch=%0d hits=%0d flush=%0d",
        checked_cycles, initialization_count, managed_initialization_count,
        dma_request_count, dma_completion_count, prefetch_count, cache_hit_count, flush_count);
endmodule
bind kernel_loader kernel_loader_observer #(
    .p_count_width(3 * ((COUNT_WIDTH < 1) ? 1 : COUNT_WIDTH))
) tb_pending_observer();

`ifdef NPU_SIM_ASSERT
module npu_kernel_pending_environment_observer;
    // 实际顶层的新配置只在旧 DMA 描述符结束后清空权重缓存。
    always @(posedge npu_top.clk) begin
        if (npu_top.core_rst_n) begin
            if (npu_top.cfg_stage2_fire) begin
                assert (!npu_top.u_matrix_engine.u_kernel_loader.ext_dma_busy);
                assert (npu_top.u_matrix_engine.u_kernel_loader.tb_pending_observer.dma_slots == 0);
            end
            // 普通卷积可保存两条 DMA 描述符，图像任务与线性返回互斥。
            if (npu_top.u_block_dma_arbiter.conv_job_q)
                assert (npu_top.u_block_dma_arbiter.rd_pending_count <= 2);
            if (npu_top.u_block_dma_arbiter.u_dma.conv_active)
                assert (!npu_top.u_block_dma_arbiter.u_dma.linear_finish);
        end
    end
endmodule
bind npu_top npu_kernel_pending_environment_observer tb_kernel_pending_environment();
`endif
/* verilator lint_on DECLFILENAME */
`endif
