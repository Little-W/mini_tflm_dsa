// SPDX-License-Identifier: Apache-2.0
`ifndef SYNTHESIS
module npu_output_pipeline_observer #(
  parameter int TB_FIFO_VLEN=16,
  parameter int TB_FIFO_BUS_WIDTH=64,
  parameter int TB_FIFO_BANKS=32,
  parameter int TB_FIFO_TRANSPOSE=1
);

// 在实际 NPU 输入上并联默认存储布局，逐周期比较完整输出接口。
if (TB_FIFO_VLEN == 16 && TB_FIFO_TRANSPOSE != 0) begin : g_fifo_compare
    wire ref_req, ref_valid, ref_switch, ref_full;
    wire [TB_FIFO_BUS_WIDTH-1:0] ref_data;
    wire [TB_FIFO_BUS_WIDTH/8-1:0] ref_mask;
    logic active_mode;
    logic active_seen;
    logic configured_mode, configuration_seen;
    longint unsigned compared_cycles=0, coalesce_cycles=0, frame_cycles=0;
    longint unsigned ws_coalesce_cycles=0, is_coalesce_cycles=0;
    longint unsigned ws_to_is=0, is_to_ws=0, configuration_count=0, recovery_resets=0;
    vec_s8_to_fifo #(
        .VLEN(TB_FIFO_VLEN), .BANKS(TB_FIFO_BANKS), .BUS_WIDTH(TB_FIFO_BUS_WIDTH),
        .ENABLE_TRANSPOSE(TB_FIFO_TRANSPOSE), .p_cyclic_storage(1'b0)
    ) u_reference (
        .clk(npu_top.clk), .rst_n(npu_top.core_rst_n),
        .in_valid(npu_top.u_matrix_engine.u_output_pipeline.requant_out_valid && !npu_top.u_matrix_engine.run_16x8),
        .in_tile_done(npu_top.u_matrix_engine.u_output_pipeline.requant_out_tile_done && !npu_top.u_matrix_engine.run_16x8),
        .in_vec_s8(npu_top.u_matrix_engine.u_output_pipeline.in_vec_s8), .oa_fifo_req(ref_req),
        .transpose_mode(npu_top.is_mode), .coalesce_enable(npu_top.u_matrix_engine.u_output_pipeline.oa_row_coalesce),
        .coalesce_group_start(npu_top.u_matrix_engine.u_output_pipeline.oa_coalesce_group_start),
        .coalesce_rows(32'(npu_top.u_matrix_engine.u_output_pipeline.oa_coalesce_rows)),
        .coalesce_cols(32'(npu_top.u_matrix_engine.u_output_pipeline.oa_coalesce_cols)),
        .reserve_banks(npu_top.u_matrix_engine.output_reserve_banks),
        .i_ready_bank_threshold(32'(npu_top.u_matrix_engine.output_s8_ready_threshold)),
        .vec_valid_num_col(npu_top.u_matrix_engine.u_output_pipeline.fifo_vec_valid_num_col),
        .vec_valid_num_row(npu_top.u_matrix_engine.u_output_pipeline.fifo_vec_valid_num_row),
        .output_valid(ref_valid), .output_ready(npu_top.u_matrix_engine.u_output_pipeline.fifo_output_ready && !npu_top.u_matrix_engine.run_16x8),
        .output_row_switch(ref_switch), .output_mask(ref_mask), .output_data(ref_data),
        .fifo_full_flag(ref_full)
    );
    wire read_active=npu_top.u_matrix_engine.u_output_pipeline.u_vec_s8_to_fifo.g_full.u_full.co_active ||
        npu_top.u_matrix_engine.u_output_pipeline.u_vec_s8_to_fifo.g_full.u_full.stream_active;
    always @(posedge npu_top.clk) begin
        if (!npu_top.core_rst_n) begin
            active_seen<=0;
            active_mode<=0;
            configured_mode<=0;
            configuration_seen<=0;
            if (npu_top.rst_n) recovery_resets++;
        end else begin
            compared_cycles++;
            if (npu_top.u_matrix_engine.u_output_pipeline.oa_row_coalesce && read_active) begin
                coalesce_cycles++;
                if (npu_top.is_mode) is_coalesce_cycles++;
                else ws_coalesce_cycles++;
            end
            if (npu_top.frame_mode_q && read_active) frame_cycles++;
            assert ({npu_top.u_matrix_engine.u_output_pipeline.fifo_s8_output_req,npu_top.u_matrix_engine.u_output_pipeline.fifo_s8_output_valid,
                     npu_top.u_matrix_engine.u_output_pipeline.fifo_s8_output_switch_row,npu_top.u_matrix_engine.u_output_pipeline.fifo_s8_output_mask,
                     npu_top.u_matrix_engine.u_output_pipeline.fifo_s8_output_data,npu_top.u_matrix_engine.u_output_pipeline.fifo_s8_full_flag} ===
                    {ref_req,ref_valid,ref_switch,ref_mask,ref_data,ref_full})
                else $fatal(1,"NPU S8 FIFO interface differs between storage layouts");
            if (read_active) begin
                if (active_seen) assert(npu_top.is_mode==active_mode)
                    else $fatal(1,"NPU output mode changed during FIFO reading");
                active_mode<=npu_top.is_mode;
            end
            active_seen<=read_active;
            if (npu_top.cfg_stage2_fire) begin
                configuration_count++;
                if (configuration_seen) begin
                    if (!configured_mode && npu_top.u_matrix_engine.u_task_configuration.configuration.is_mode) ws_to_is++;
                    if (configured_mode && !npu_top.u_matrix_engine.u_task_configuration.configuration.is_mode) is_to_ws++;
                end
                configured_mode<=npu_top.u_matrix_engine.u_task_configuration.configuration.is_mode;
                configuration_seen<=1;
                assert(!read_active && npu_top.u_matrix_engine.u_output_pipeline.u_vec_s8_to_fifo.g_full.skid_count==0 &&
                       npu_top.u_matrix_engine.u_output_pipeline.u_vec_s8_to_fifo.g_full.u_full.bank_ready=='0 &&
                       !npu_top.u_matrix_engine.u_output_pipeline.u_vec_s8_to_fifo.g_full.u_full.ram_read_en)
                    else $fatal(1,"NPU accepted output configuration before FIFO drain");
            end
            if (npu_top.u_matrix_engine.oa_calc_over && !npu_top.u_matrix_engine.run_16x8) begin
                assert(!read_active && npu_top.u_matrix_engine.u_output_pipeline.u_vec_s8_to_fifo.g_full.skid_count==0)
                    else $fatal(1,"NPU output completion preceded FIFO drain");
            end
            if (npu_top.frame_mode_q && read_active)
                assert(!npu_top.u_matrix_engine.u_output_pipeline.oa_row_coalesce)
                    else $fatal(1,"Frame output unexpectedly uses row coalescing");
        end
    end
    final $display("NPU_FIFO_COMPARE_PASS cycles=%0d coalesce_cycles=%0d frame_cycles=%0d ws_coalesce_cycles=%0d is_coalesce_cycles=%0d ws_to_is=%0d is_to_ws=%0d configurations=%0d recovery_resets=%0d",
        compared_cycles,coalesce_cycles,frame_cycles,ws_coalesce_cycles,is_coalesce_cycles,
        ws_to_is,is_to_ws,configuration_count,recovery_resets);
end

endmodule

bind npu_output_pipeline npu_output_pipeline_observer #(
  .TB_FIFO_VLEN(p_size),
  .TB_FIFO_BUS_WIDTH(p_bus_width),
  .TB_FIFO_BANKS(p_oa_fifo_banks),
  .TB_FIFO_TRANSPOSE(p_enable_is_mode)
) u_fifo_compare_observer();
`endif
