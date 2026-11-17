// SPDX-License-Identifier: Apache-2.0
`ifndef SYNTHESIS
/* verilator lint_off DECLFILENAME */
module npu_controller_observer #(
  parameter int TB_IDLE=0,
  parameter int TB_IA_START=0,
  parameter int TB_IA_WAIT=0,
  parameter int TB_WAIT_DONE=0,
  parameter int TB_WEIGHT_START=0,
  parameter int TB_WEIGHT_WAIT=0
);


    bit       util_trace_en;
    bit       util_summary_en;
    logic     util_active;
wire util_start_event=(32'(npu_controller.current_state)==TB_IDLE) && npu_controller.calc_start;
wire util_finish_event=util_active && (32'(npu_controller.current_state)!=TB_IDLE) && (32'(npu_controller.next_state)==TB_IDLE);

    longint unsigned util_op_id;
    longint unsigned util_active_cycles;
    longint unsigned util_weight_start_cycles;
    longint unsigned util_weight_wait_cycles;
    longint unsigned util_ia_start_cycles;
    longint unsigned util_ia_wait_cycles;
    longint unsigned util_wait_done_cycles;
    longint unsigned util_stall_weight_tail_cycles;
    longint unsigned util_stall_weight_data_cycles;
    longint unsigned util_stall_weight_done_cycles;
    longint unsigned util_stall_ia_data_cycles;
    longint unsigned util_stall_bias_cycles;
    longint unsigned util_stall_quant_cycles;
    longint unsigned util_stall_fifo_cycles;
    longint unsigned util_stall_ia_done_cycles;
    longint unsigned util_tail_pending_cycles;
    longint unsigned util_tail_done_count;
    longint unsigned util_weight_trigger_count;
    longint unsigned util_ia_trigger_count;
    longint unsigned util_sum_active_cycles;
    longint unsigned util_sum_weight_start_cycles;
    longint unsigned util_sum_weight_wait_cycles;
    longint unsigned util_sum_ia_start_cycles;
    longint unsigned util_sum_ia_wait_cycles;
    longint unsigned util_sum_wait_done_cycles;
    longint unsigned util_sum_stall_weight_tail_cycles;
    longint unsigned util_sum_stall_weight_data_cycles;
    longint unsigned util_sum_stall_weight_done_cycles;
    longint unsigned util_sum_stall_ia_data_cycles;
    longint unsigned util_sum_stall_bias_cycles;
    longint unsigned util_sum_stall_quant_cycles;
    longint unsigned util_sum_stall_fifo_cycles;
    longint unsigned util_sum_stall_ia_done_cycles;
    longint unsigned util_sum_tail_pending_cycles;
    longint unsigned util_sum_tail_done_count;
    longint unsigned util_sum_weight_trigger_count;
    longint unsigned util_sum_ia_trigger_count;

    initial begin
        util_trace_en = 1'b0;
        util_summary_en = 1'b0;
        if ($test$plusargs("NPU_UTIL_TRACE")) util_trace_en = 1'b1;
        if ($test$plusargs("NPU_UTIL_SUMMARY")) util_summary_en = 1'b1;
    end

    always_ff @(posedge npu_controller.clk or negedge npu_controller.rst_n) begin
        if (!npu_controller.rst_n) begin
            util_active                   <= 1'b0;
            util_op_id                    <= '0;
            util_active_cycles            <= '0;
            util_weight_start_cycles      <= '0;
            util_weight_wait_cycles       <= '0;
            util_ia_start_cycles          <= '0;
            util_ia_wait_cycles           <= '0;
            util_wait_done_cycles           <= '0;
            util_stall_weight_tail_cycles <= '0;
            util_stall_weight_data_cycles <= '0;
            util_stall_weight_done_cycles <= '0;
            util_stall_ia_data_cycles     <= '0;
            util_stall_bias_cycles        <= '0;
            util_stall_quant_cycles       <= '0;
            util_stall_fifo_cycles        <= '0;
            util_stall_ia_done_cycles     <= '0;
            util_tail_pending_cycles      <= '0;
            util_tail_done_count          <= '0;
            util_weight_trigger_count     <= '0;
            util_ia_trigger_count         <= '0;
            util_sum_active_cycles            <= '0;
            util_sum_weight_start_cycles      <= '0;
            util_sum_weight_wait_cycles       <= '0;
            util_sum_ia_start_cycles          <= '0;
            util_sum_ia_wait_cycles           <= '0;
            util_sum_wait_done_cycles           <= '0;
            util_sum_stall_weight_tail_cycles <= '0;
            util_sum_stall_weight_data_cycles <= '0;
            util_sum_stall_weight_done_cycles <= '0;
            util_sum_stall_ia_data_cycles     <= '0;
            util_sum_stall_bias_cycles        <= '0;
            util_sum_stall_quant_cycles       <= '0;
            util_sum_stall_fifo_cycles        <= '0;
            util_sum_stall_ia_done_cycles     <= '0;
            util_sum_tail_pending_cycles      <= '0;
            util_sum_tail_done_count          <= '0;
            util_sum_weight_trigger_count     <= '0;
            util_sum_ia_trigger_count         <= '0;
        end else begin
            if (util_start_event) begin
                util_active                   <= 1'b1;
                util_op_id                    <= util_op_id + 1'b1;
                util_active_cycles            <= '0;
                util_weight_start_cycles      <= '0;
                util_weight_wait_cycles       <= '0;
                util_ia_start_cycles          <= '0;
                util_ia_wait_cycles           <= '0;
                util_wait_done_cycles           <= '0;
                util_stall_weight_tail_cycles <= '0;
                util_stall_weight_data_cycles <= '0;
                util_stall_weight_done_cycles <= '0;
                util_stall_ia_data_cycles     <= '0;
                util_stall_bias_cycles        <= '0;
                util_stall_quant_cycles       <= '0;
                util_stall_fifo_cycles        <= '0;
                util_stall_ia_done_cycles     <= '0;
                util_tail_pending_cycles      <= '0;
                util_tail_done_count          <= '0;
                util_weight_trigger_count     <= '0;
                util_ia_trigger_count         <= '0;
            end else if (util_active) begin
                util_active_cycles <= util_active_cycles + 1'b1;

                unique case (32'(npu_controller.current_state))
                    TB_WEIGHT_START: util_weight_start_cycles <= util_weight_start_cycles + 1'b1;
                    TB_WEIGHT_WAIT:  util_weight_wait_cycles  <= util_weight_wait_cycles + 1'b1;
                    TB_IA_START:     util_ia_start_cycles     <= util_ia_start_cycles + 1'b1;
                    TB_IA_WAIT:      util_ia_wait_cycles      <= util_ia_wait_cycles + 1'b1;
                    TB_WAIT_DONE:      util_wait_done_cycles      <= util_wait_done_cycles + 1'b1;
                    default: begin
                    end
                endcase

                if (32'(npu_controller.current_state) == TB_IA_START && !npu_controller.oa_calc_over && !npu_controller.input_tail_ready) begin
                    util_stall_weight_tail_cycles <= util_stall_weight_tail_cycles + 1'b1;
                end
                if (32'(npu_controller.current_state) == TB_WEIGHT_START && !npu_controller.oa_calc_over &&
                    !npu_controller.weight_data_valid) begin
                    util_stall_weight_data_cycles <= util_stall_weight_data_cycles + 1'b1;
                end
                if (32'(npu_controller.current_state) == TB_WEIGHT_WAIT && !npu_controller.weight_sending_done) begin
                    util_stall_weight_done_cycles <= util_stall_weight_done_cycles + 1'b1;
                end
                if (32'(npu_controller.current_state) == TB_IA_START && !npu_controller.ia_data_valid) begin
                    util_stall_ia_data_cycles <= util_stall_ia_data_cycles + 1'b1;
                end
                if (32'(npu_controller.current_state) == TB_IA_START && npu_controller.ia_data_valid && !npu_controller.bias_ready_for_compute) begin
                    util_stall_bias_cycles <= util_stall_bias_cycles + 1'b1;
                end
                if (32'(npu_controller.current_state) == TB_IA_START && npu_controller.ia_data_valid &&
                    npu_controller.bias_ready_for_compute && !npu_controller.quant_params_valid) begin
                    util_stall_quant_cycles <= util_stall_quant_cycles + 1'b1;
                end
                if (32'(npu_controller.current_state) == TB_IA_START && npu_controller.ia_data_valid &&
                    npu_controller.bias_ready_for_compute && npu_controller.quant_params_valid && npu_controller.fifo_full_flag) begin
                    util_stall_fifo_cycles <= util_stall_fifo_cycles + 1'b1;
                end
                if (32'(npu_controller.current_state) == TB_IA_WAIT && !npu_controller.ia_sending_done) begin
                    util_stall_ia_done_cycles <= util_stall_ia_done_cycles + 1'b1;
                end
                if (npu_controller.compute_tail_pending) begin
                    util_tail_pending_cycles <= util_tail_pending_cycles + 1'b1;
                end
                if (npu_controller.compute_tail_done) begin
                    util_tail_done_count <= util_tail_done_count + 1'b1;
                end
	                if (npu_controller.send_weight_trigger) begin
	                    util_weight_trigger_count <= util_weight_trigger_count + 1'b1;
	                end
	                if (npu_controller.send_ia_trigger) begin
	                    util_ia_trigger_count <= util_ia_trigger_count + 1'b1;
	                end
            end

            if (util_finish_event) begin
                util_sum_active_cycles            <= util_sum_active_cycles + util_active_cycles;
                util_sum_weight_start_cycles      <= util_sum_weight_start_cycles + util_weight_start_cycles;
                util_sum_weight_wait_cycles       <= util_sum_weight_wait_cycles + util_weight_wait_cycles;
                util_sum_ia_start_cycles          <= util_sum_ia_start_cycles + util_ia_start_cycles;
                util_sum_ia_wait_cycles           <= util_sum_ia_wait_cycles + util_ia_wait_cycles;
                util_sum_wait_done_cycles           <= util_sum_wait_done_cycles + util_wait_done_cycles;
                util_sum_stall_weight_tail_cycles <= util_sum_stall_weight_tail_cycles + util_stall_weight_tail_cycles;
                util_sum_stall_weight_data_cycles <= util_sum_stall_weight_data_cycles + util_stall_weight_data_cycles;
                util_sum_stall_weight_done_cycles <= util_sum_stall_weight_done_cycles + util_stall_weight_done_cycles;
                util_sum_stall_ia_data_cycles     <= util_sum_stall_ia_data_cycles + util_stall_ia_data_cycles;
                util_sum_stall_bias_cycles        <= util_sum_stall_bias_cycles + util_stall_bias_cycles;
                util_sum_stall_quant_cycles       <= util_sum_stall_quant_cycles + util_stall_quant_cycles;
                util_sum_stall_fifo_cycles        <= util_sum_stall_fifo_cycles + util_stall_fifo_cycles;
                util_sum_stall_ia_done_cycles     <= util_sum_stall_ia_done_cycles + util_stall_ia_done_cycles;
                util_sum_tail_pending_cycles      <= util_sum_tail_pending_cycles + util_tail_pending_cycles;
                util_sum_tail_done_count          <= util_sum_tail_done_count + util_tail_done_count;
                util_sum_weight_trigger_count     <= util_sum_weight_trigger_count + util_weight_trigger_count;
                util_sum_ia_trigger_count         <= util_sum_ia_trigger_count + util_ia_trigger_count;
                if (util_trace_en) begin
                    $display("[NPU_CTRL_UTIL] op=%0d active=%0d weight_start=%0d weight_wait=%0d ia_start=%0d ia_wait=%0d wait_done=%0d weight_tail_stall=%0d weight_data_stall=%0d weight_done_wait=%0d ia_data_stall=%0d bias_stall=%0d quant_stall=%0d fifo_stall=%0d ia_done_wait=%0d tail_pending=%0d tail_done=%0d weight_trig=%0d ia_trig=%0d",
                             util_op_id,
                             util_active_cycles,
                             util_weight_start_cycles,
                             util_weight_wait_cycles,
                             util_ia_start_cycles,
                             util_ia_wait_cycles,
                             util_wait_done_cycles,
                             util_stall_weight_tail_cycles,
                             util_stall_weight_data_cycles,
                             util_stall_weight_done_cycles,
                             util_stall_ia_data_cycles,
                             util_stall_bias_cycles,
                             util_stall_quant_cycles,
                             util_stall_fifo_cycles,
                             util_stall_ia_done_cycles,
                             util_tail_pending_cycles,
                             util_tail_done_count,
                             util_weight_trigger_count,
                             util_ia_trigger_count);
                end
                util_active <= 1'b0;
            end
	        end
	    end

    final begin
        if (util_summary_en) begin
            $display("[NPU_CTRL_UTIL_SUMMARY] ops=%0d active=%0d weight_start=%0d weight_wait=%0d ia_start=%0d ia_wait=%0d wait_done=%0d weight_tail_stall=%0d weight_data_stall=%0d weight_done_wait=%0d ia_data_stall=%0d bias_stall=%0d quant_stall=%0d fifo_stall=%0d ia_done_wait=%0d tail_pending=%0d tail_done=%0d weight_trig=%0d ia_trig=%0d",
                     util_op_id,
                     util_sum_active_cycles,
                     util_sum_weight_start_cycles,
                     util_sum_weight_wait_cycles,
                     util_sum_ia_start_cycles,
                     util_sum_ia_wait_cycles,
                     util_sum_wait_done_cycles,
                     util_sum_stall_weight_tail_cycles,
                     util_sum_stall_weight_data_cycles,
                     util_sum_stall_weight_done_cycles,
                     util_sum_stall_ia_data_cycles,
                     util_sum_stall_bias_cycles,
                     util_sum_stall_quant_cycles,
                     util_sum_stall_fifo_cycles,
                     util_sum_stall_ia_done_cycles,
                     util_sum_tail_pending_cycles,
                     util_sum_tail_done_count,
                     util_sum_weight_trigger_count,
                     util_sum_ia_trigger_count);
        end
    end

endmodule
bind npu_controller npu_controller_observer #(
  .TB_IDLE(32'(IDLE)),
  .TB_IA_START(32'(IA_START)),
  .TB_IA_WAIT(32'(IA_WAIT)),
  .TB_WAIT_DONE(32'(WAIT_DONE)),
  .TB_WEIGHT_START(32'(WEIGHT_START)),
  .TB_WEIGHT_WAIT(32'(WEIGHT_WAIT))
) tb_observer();
/* verilator lint_on DECLFILENAME */
`endif
