`default_nettype none

// 在实际 NPU 中检查寄存错误上报、配置握手和任务完成优先级。
module npu_registered_fault_observer (
    input logic clk, rst_n,
    input logic i_error_event, i_reported_error, i_task_fault,
    input logic i_rvalid, i_rready, i_bvalid, i_bready,
    input logic [1:0] i_rresp, i_bresp,
    input logic i_calc_start, i_ready, i_vector_mode, i_config_start,
    input logic i_done, i_abort_pending
);
    logic expected_error;
    longint unsigned checked_cycles=0;
    longint unsigned error_events=0;
    longint unsigned read_error_beats=0;
    longint unsigned write_error_responses=0;
    longint unsigned configuration_accepts=0;
    longint unsigned completed_tasks=0;

    always_ff @(posedge clk) begin
        if (!rst_n) expected_error <= 1'b0;
        else expected_error <= i_error_event;
    end
    always @(posedge clk) begin
        if (rst_n) begin
            assert(i_reported_error == expected_error);
            // 原始错误事件出现的当前周期已停止接收新任务。
            if (i_error_event) assert(!i_ready);
            assert(!i_task_fault || !i_ready);
            assert(i_config_start == (i_calc_start && i_ready && !i_vector_mode));
            if (i_done && !i_abort_pending) assert(!i_error_event && !i_reported_error);
            checked_cycles++;
            error_events += 64'(i_error_event);
            read_error_beats += 64'(i_rvalid && i_rready && i_rresp[1]);
            write_error_responses += 64'(i_bvalid && i_bready && i_bresp[1]);
            configuration_accepts += 64'(i_calc_start && i_ready);
            completed_tasks += 64'(i_done);
        end
    end
    final $display("NPU_REGISTERED_FAULT_PASS cycles=%0d errors=%0d read_errors=%0d write_errors=%0d configurations=%0d completion_cycles=%0d",
        checked_cycles,error_events,read_error_beats,write_error_responses,
        configuration_accepts,completed_tasks);
endmodule

bind npu_top npu_registered_fault_observer u_registered_fault_observer (
    .clk(clk), .rst_n(core_rst_n),
    .i_error_event(u_block_dma_arbiter.bus_error_event), .i_reported_error(dma_bus_error),
    .i_rvalid(m_axi_rvalid), .i_rready(m_axi_rready), .i_rresp(m_axi_rresp),
    .i_bvalid(m_axi_bvalid), .i_bready(m_axi_bready), .i_bresp(m_axi_bresp),
    .i_task_fault(task_fault), .i_calc_start(calc_start), .i_ready(sa_ready),
    .i_vector_mode(cfg_vector_enable), .i_config_start(cfg_start_event),
    .i_done(done_valid), .i_abort_pending(abort_pending)
);

`default_nettype wire
