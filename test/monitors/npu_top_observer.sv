// SPDX-License-Identifier: Apache-2.0
`ifndef SYNTHESIS
/* verilator lint_off DECLFILENAME */
module npu_top_observer #(
  parameter int TB_AB_DONE=0,
  parameter int TB_AB_RESET=0,
  parameter int TB_FRAME_EXEC_ENABLED=0,
  parameter int TB_VECTOR_ENGINE_CAPABLE=0
);

wire [31:0] conv_hits_raw=npu_top.u_block_dma_arbiter.tb_observer.conv_stat_hits;
wire [31:0] conv_misses_raw=npu_top.u_block_dma_arbiter.tb_observer.conv_stat_misses;
wire [31:0] conv_read_bytes_raw=npu_top.u_block_dma_arbiter.tb_observer.conv_stat_read_bytes;

// 帧模式资格自配置相位三起保持一致，容量检查与调度器使用同一结果。
always @(posedge npu_top.clk) begin
  if (npu_top.core_rst_n && npu_top.cfg_valid_q[2] &&
      npu_top.u_matrix_engine.u_task_configuration.cfg_capacity_phase >= 3'd3) begin
    assert (npu_top.u_matrix_engine.use_frame_commands_s2 ===
        (TB_FRAME_EXEC_ENABLED && (!npu_top.u_matrix_engine.u_task_configuration.ps_long_capacity_fits ||
         !npu_top.u_matrix_engine.u_task_configuration.legacy_window_shape_s2 || npu_top.ps_control_q[1])))
      else $fatal(1, "Frame mode differs at configuration consumption phase");
  end
end

// 配置提交后的输出预留计数必须与当前运行模式及复用数一致。
wire [31:0] expected_s8_reserve = npu_top.u_matrix_engine.direct_final_stream ?
    (32'(npu_top.ia_reuse_num_eff) + 32'(npu_top.u_matrix_engine.u_task_configuration.DIRECT_OUTPUT_EXTRA_BANKS)) :
    32'(npu_top.ia_reuse_num_eff);
always @(posedge npu_top.clk) begin
  if (npu_top.core_rst_n && !npu_top.cfg_valid_q[2]) begin
    assert (32'(npu_top.u_matrix_engine.output_reserve_banks) ===
        (expected_s8_reserve >= 32'(npu_top.u_matrix_engine.OA_FIFO_BANKS) ?
         32'(npu_top.u_matrix_engine.OA_FIFO_BANKS) : expected_s8_reserve))
      else $fatal(1, "Output reserve differs after configuration submission");
    assert (32'(npu_top.u_matrix_engine.output_s16_reserve_banks) ===
        (32'(npu_top.ia_reuse_num_eff) >= 32'(npu_top.u_matrix_engine.OA_S16_FIFO_BANKS) ?
         32'(npu_top.u_matrix_engine.OA_S16_FIFO_BANKS) : 32'(npu_top.ia_reuse_num_eff)))
      else $fatal(1, "INT16 output reserve differs after configuration submission");
  end
  if (npu_top.core_rst_n && npu_top.operand_loader_flush_q) begin
    assert (!npu_top.u_matrix_engine.init_cfg_ia && !npu_top.u_matrix_engine.init_cfg_weight &&
        !npu_top.u_matrix_engine.send_ia_trigger && !npu_top.u_matrix_engine.send_weight_trigger && !npu_top.u_matrix_engine.weight_commit)
      else $fatal(1, "Operand cache clear overlaps operand initialization or transfer");
  end
end


logic conv_count_active,conv_stats_started;
logic [31:0] conv_stat_hits,conv_stat_misses,conv_stat_read_bytes,conv_stat_cycles;
always @(posedge npu_top.clk or negedge npu_top.rst_n)begin
  if(!npu_top.rst_n)begin
    conv_stat_hits<=0;conv_stat_misses<=0;conv_stat_read_bytes<=0;conv_stat_cycles<=0;
    conv_count_active<=0;conv_stats_started<=0;
  end else begin
    if(npu_top.calc_start && npu_top.sa_ready)begin
      conv_stats_started<=0;
      if((npu_top.cfg_conv_enable && !npu_top.cfg_vector_enable) || (npu_top.cfg_vector_enable && npu_top.cfg_vector.op<=4'd3))begin
        conv_stat_hits<=0;conv_stat_misses<=0;conv_stat_read_bytes<=0;conv_stat_cycles<=0;conv_count_active<=1;
      end
    end
            if (conv_count_active) begin
                conv_stat_cycles <= conv_stat_cycles + 32'd1;
                if (conv_stats_started && 32'(npu_top.abort_state) != TB_AB_RESET && 32'(npu_top.abort_state) != TB_AB_DONE) begin
                    conv_stat_hits <= conv_hits_raw;
                    conv_stat_misses <= conv_misses_raw;
                    conv_stat_read_bytes <= conv_read_bytes_raw;
                end
            end
            if ((npu_top.u_matrix_engine.init_cfg_ia && npu_top.run_conv) || (npu_top.run_vector && npu_top.vector_dma_cfg_valid && npu_top.conv_cfg_ready))
                conv_stats_started <= 1'b1;
            if (npu_top.done_valid) conv_count_active <= 1'b0;
  end
end

    function automatic longint unsigned util_bp(
        input longint unsigned numerator,
        input longint unsigned denominator
    );
        begin
            util_bp = (denominator == 0) ? 0 : ((numerator * 10000) / denominator);
        end
    endfunction

    bit top_util_trace_en;
    logic top_util_active;
    longint unsigned top_util_op_id;
    longint unsigned top_util_active_cycles;
    longint unsigned top_util_ia_row_cycles;
    longint unsigned top_util_acc_valid_cycles;
    longint unsigned top_util_requant_valid_cycles;
    longint unsigned top_util_fifo_valid_cycles;
    longint unsigned top_util_fifo_full_cycles;
    longint unsigned top_util_store_weight_cycles;
    longint unsigned top_util_send_weight_count;
    longint unsigned top_util_send_ia_count;
    longint unsigned top_util_tile_start_count;
    longint unsigned top_util_tile_over_count;
    longint unsigned top_util_partial_over_count;
    longint unsigned top_util_ia_l1_switch_count;
    longint unsigned top_util_ia_dma_busy_cycles;
    longint unsigned top_util_kernel_dma_busy_cycles;
    longint unsigned top_util_bias_dma_busy_cycles;
    longint unsigned top_util_quant_dma_busy_cycles;
    longint unsigned top_util_oa_dma_busy_cycles;
    longint unsigned top_util_axi_ar_cycles;
    longint unsigned top_util_axi_r_cycles;
    longint unsigned top_util_axi_aw_cycles;
    longint unsigned top_util_axi_w_cycles;
    longint unsigned top_util_axi_b_cycles;

    initial begin
        top_util_trace_en = 1'b0;
        if ($test$plusargs("NPU_UTIL_TRACE")) top_util_trace_en = 1'b1;
    end

    wire top_util_start_event = npu_top.calc_start && npu_top.sa_ready;
    wire top_util_finish_event = top_util_active && npu_top.done_valid && npu_top.done_ready;

    always_ff @(posedge npu_top.clk or negedge npu_top.core_rst_n) begin
        if (!npu_top.core_rst_n) begin
            top_util_active                 <= 1'b0;
            top_util_op_id                  <= '0;
            top_util_active_cycles          <= '0;
            top_util_ia_row_cycles          <= '0;
            top_util_acc_valid_cycles       <= '0;
            top_util_requant_valid_cycles   <= '0;
            top_util_fifo_valid_cycles      <= '0;
            top_util_fifo_full_cycles       <= '0;
            top_util_store_weight_cycles    <= '0;
            top_util_send_weight_count      <= '0;
            top_util_send_ia_count          <= '0;
            top_util_tile_start_count       <= '0;
            top_util_tile_over_count        <= '0;
            top_util_partial_over_count     <= '0;
            top_util_ia_l1_switch_count     <= '0;
            top_util_ia_dma_busy_cycles     <= '0;
            top_util_kernel_dma_busy_cycles <= '0;
            top_util_bias_dma_busy_cycles   <= '0;
            top_util_quant_dma_busy_cycles  <= '0;
            top_util_oa_dma_busy_cycles     <= '0;
            top_util_axi_ar_cycles          <= '0;
            top_util_axi_r_cycles           <= '0;
            top_util_axi_aw_cycles          <= '0;
            top_util_axi_w_cycles           <= '0;
            top_util_axi_b_cycles           <= '0;
        end else begin
            if (top_util_start_event) begin
                top_util_active                 <= 1'b1;
                top_util_op_id                  <= top_util_op_id + 1'b1;
                top_util_active_cycles          <= '0;
                top_util_ia_row_cycles          <= '0;
                top_util_acc_valid_cycles       <= '0;
                top_util_requant_valid_cycles   <= '0;
                top_util_fifo_valid_cycles      <= '0;
                top_util_fifo_full_cycles       <= '0;
                top_util_store_weight_cycles    <= '0;
                top_util_send_weight_count      <= '0;
                top_util_send_ia_count          <= '0;
                top_util_tile_start_count       <= '0;
                top_util_tile_over_count        <= '0;
                top_util_partial_over_count     <= '0;
                top_util_ia_l1_switch_count     <= '0;
                top_util_ia_dma_busy_cycles     <= '0;
                top_util_kernel_dma_busy_cycles <= '0;
                top_util_bias_dma_busy_cycles   <= '0;
                top_util_quant_dma_busy_cycles  <= '0;
                top_util_oa_dma_busy_cycles     <= '0;
                top_util_axi_ar_cycles          <= '0;
                top_util_axi_r_cycles           <= '0;
                top_util_axi_aw_cycles          <= '0;
                top_util_axi_w_cycles           <= '0;
                top_util_axi_b_cycles           <= '0;
            end else if (top_util_active) begin
                top_util_active_cycles <= top_util_active_cycles + 1'b1;

                if (npu_top.u_matrix_engine.ia_row_valid) begin
                    top_util_ia_row_cycles <= top_util_ia_row_cycles + 1'b1;
                end
                if (npu_top.u_matrix_engine.acc_data_valid) begin
                    top_util_acc_valid_cycles <= top_util_acc_valid_cycles + 1'b1;
                end
                if (npu_top.u_matrix_engine.u_output_pipeline.requant_out_valid) begin
                    top_util_requant_valid_cycles <= top_util_requant_valid_cycles + 1'b1;
                end
                if (npu_top.u_matrix_engine.u_output_pipeline.fifo_output_valid) begin
                    top_util_fifo_valid_cycles <= top_util_fifo_valid_cycles + 1'b1;
                end
                if (npu_top.u_matrix_engine.fifo_full_flag) begin
                    top_util_fifo_full_cycles <= top_util_fifo_full_cycles + 1'b1;
                end
                if (npu_top.u_matrix_engine.store_weight_req) begin
                    top_util_store_weight_cycles <= top_util_store_weight_cycles + 1'b1;
                end
                if (npu_top.u_matrix_engine.send_weight_trigger) begin
                    top_util_send_weight_count <= top_util_send_weight_count + 1'b1;
                end
                if (npu_top.u_matrix_engine.send_ia_trigger) begin
                    top_util_send_ia_count <= top_util_send_ia_count + 1'b1;
                end
                if (npu_top.u_matrix_engine.ia_tile_start) begin
                    top_util_tile_start_count <= top_util_tile_start_count + 1'b1;
                end
                if (npu_top.u_matrix_engine.tile_calc_over) begin
                    top_util_tile_over_count <= top_util_tile_over_count + 1'b1;
                end
                if (npu_top.u_matrix_engine.partial_sum_calc_over) begin
                    top_util_partial_over_count <= top_util_partial_over_count + 1'b1;
                end
                if (npu_top.u_matrix_engine.ia_l1_switch) begin
                    top_util_ia_l1_switch_count <= top_util_ia_l1_switch_count + 1'b1;
                end
                if (npu_top.ia_dma_busy) begin
                    top_util_ia_dma_busy_cycles <= top_util_ia_dma_busy_cycles + 1'b1;
                end
                if (npu_top.kernel_dma_busy) begin
                    top_util_kernel_dma_busy_cycles <= top_util_kernel_dma_busy_cycles + 1'b1;
                end
                if (npu_top.bias_dma_busy) begin
                    top_util_bias_dma_busy_cycles <= top_util_bias_dma_busy_cycles + 1'b1;
                end
                if (npu_top.quant_dma_busy) begin
                    top_util_quant_dma_busy_cycles <= top_util_quant_dma_busy_cycles + 1'b1;
                end
                if (npu_top.oa_dma_busy) begin
                    top_util_oa_dma_busy_cycles <= top_util_oa_dma_busy_cycles + 1'b1;
                end
                if (npu_top.m_axi_arvalid && npu_top.m_axi_arready) begin
                    top_util_axi_ar_cycles <= top_util_axi_ar_cycles + 1'b1;
                end
                if (npu_top.m_axi_rvalid && npu_top.m_axi_rready) begin
                    top_util_axi_r_cycles <= top_util_axi_r_cycles + 1'b1;
                end
                if (npu_top.m_axi_awvalid && npu_top.m_axi_awready) begin
                    top_util_axi_aw_cycles <= top_util_axi_aw_cycles + 1'b1;
                end
                if (npu_top.m_axi_wvalid && npu_top.m_axi_wready) begin
                    top_util_axi_w_cycles <= top_util_axi_w_cycles + 1'b1;
                end
                if (npu_top.m_axi_bvalid && npu_top.m_axi_bready) begin
                    top_util_axi_b_cycles <= top_util_axi_b_cycles + 1'b1;
                end
            end

            if (top_util_finish_event) begin
                if (top_util_trace_en) begin
                    $display("[NPU_UTIL] op=%0d active=%0d ia_row=%0d ia_row_util_bp=%0d acc_valid=%0d acc_util_bp=%0d requant_valid=%0d fifo_valid=%0d fifo_full=%0d store_weight=%0d send_weight=%0d send_ia=%0d tile_start=%0d tile_over=%0d partial_over=%0d l1_switch=%0d dma_busy_ia=%0d dma_busy_kernel=%0d dma_busy_bias=%0d dma_busy_quant=%0d dma_busy_oa=%0d axi_ar=%0d axi_r=%0d axi_aw=%0d axi_w=%0d axi_b=%0d",
                             top_util_op_id,
                             top_util_active_cycles,
                             top_util_ia_row_cycles,
                             util_bp(top_util_ia_row_cycles, top_util_active_cycles),
                             top_util_acc_valid_cycles,
                             util_bp(top_util_acc_valid_cycles, top_util_active_cycles),
                             top_util_requant_valid_cycles,
                             top_util_fifo_valid_cycles,
                             top_util_fifo_full_cycles,
                             top_util_store_weight_cycles,
                             top_util_send_weight_count,
                             top_util_send_ia_count,
                             top_util_tile_start_count,
                             top_util_tile_over_count,
                             top_util_partial_over_count,
                             top_util_ia_l1_switch_count,
                             top_util_ia_dma_busy_cycles,
                             top_util_kernel_dma_busy_cycles,
                             top_util_bias_dma_busy_cycles,
                             top_util_quant_dma_busy_cycles,
                             top_util_oa_dma_busy_cycles,
                             top_util_axi_ar_cycles,
                             top_util_axi_r_cycles,
                             top_util_axi_aw_cycles,
                             top_util_axi_w_cycles,
                             top_util_axi_b_cycles);
                end
                top_util_active <= 1'b0;
            end
        end
    end

wire [31:0] vector_stat_cycles,vector_stat_compute,vector_stat_dma_wait;
if(TB_VECTOR_ENGINE_CAPABLE)begin:g_vector_stats
assign vector_stat_cycles=npu_top.g_vector_engine.u_engine.tb_observer.stat_cycles;
assign vector_stat_compute=npu_top.g_vector_engine.u_engine.tb_observer.stat_compute;
assign vector_stat_dma_wait=npu_top.g_vector_engine.u_engine.tb_observer.stat_dma_wait;
end else begin:g_no_vector_stats
assign vector_stat_cycles=0;assign vector_stat_compute=0;assign vector_stat_dma_wait=0;
end
wire [31:0] frame_stat_commands,frame_stat_pressure_events,frame_stat_early_finish_frames;
wire [31:0] ps_stat_commands=(npu_top.frame_mode_q && !npu_top.run_vector) ? frame_stat_commands : 32'd0;
wire [31:0] ps_stat_pressure_events=(npu_top.frame_mode_q && !npu_top.run_vector) ? frame_stat_pressure_events : 32'd0;
wire [31:0] ps_stat_early_finish_frames=(npu_top.frame_mode_q && !npu_top.run_vector) ? frame_stat_early_finish_frames : 32'd0;
if(TB_FRAME_EXEC_ENABLED)begin:g_frame_stats
assign frame_stat_commands=npu_top.u_matrix_engine.g_frame_schedule.u_scheduler.tb_observer.stat_commands;
assign frame_stat_pressure_events=npu_top.u_matrix_engine.g_frame_schedule.u_scheduler.tb_observer.stat_pressure_events;
assign frame_stat_early_finish_frames=npu_top.u_matrix_engine.g_frame_schedule.u_scheduler.tb_observer.stat_early_finish_frames;
end else begin:g_no_frame_stats
assign frame_stat_commands=0;assign frame_stat_pressure_events=0;assign frame_stat_early_finish_frames=0;
end


endmodule
bind npu_top npu_top_observer #(
  .TB_AB_DONE(32'(AB_DONE)),
  .TB_AB_RESET(32'(AB_RESET)),
  .TB_FRAME_EXEC_ENABLED(32'(FRAME_EXEC_ENABLED)),
  .TB_VECTOR_ENGINE_CAPABLE(32'(VECTOR_ENGINE_CAPABLE))
) tb_observer();
/* verilator lint_on DECLFILENAME */
`endif
