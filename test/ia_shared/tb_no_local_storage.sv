`timescale 1ns/1ps
`default_nettype none

module tb_no_local_storage;
    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic calc_start = 1'b0;
    logic done_ready = 1'b0;
    logic dataflow_mode = 1'b0;
    logic input_s16 = 1'b0;
    logic [31:0] ps_control = 32'd1;
    wire logic sa_ready, done_valid;
    wire logic [1:0] err_code;
    wire logic arvalid, awvalid, wvalid;
    integer checked_cycles = 0;
    integer completed_tasks = 0;

    always #5 clk = !clk;

    npu_top #(
        .SIZE(16), .BUS_WIDTH(64), .IA_COMPACT_ENABLE(1),
        .SHARED_IA_PS_ENABLE(0), .SHARED_BANK_BYTES(8192), .SHARED_BANK_COUNT(7),
        .ENABLE_VECTOR_ENGINE(0), .VECTOR_PE_COUNT(8)
    ) u_dut (
        .clk(clk), .rst_n(rst_n), .cfg_operand_fetch64(1'b0),
        .cfg_lhs_tile_packed(1'b0), .cfg_rhs_tile_packed(1'b0),
        .cfg_conv_enable(1'b0), .cfg_conv('0),
        .cfg_vector_enable(1'b0), .cfg_vector('0),
        .calc_start(calc_start), .cfg_16bits_ia(input_s16), .cfg_16x8(1'b0),
        .cfg_dataflow_mode(dataflow_mode), .cfg_ia_reuse_num(32'd1), .cfg_w_reuse_num(32'd1),
        .cfg_row_groups(32'd1), .cfg_row_tail_tiles(32'd1),
        .cfg_col_groups(32'd1), .cfg_col_tail_tiles(32'd1),
        .cfg_ps_control(ps_control), .cfg_shared_ia_banks(32'd1),
        .sa_ready(sa_ready), .done_valid(done_valid), .done_ready(done_ready), .err_code(err_code),
        .lhs_base(32'h1000), .rhs_base(32'h2000), .dst_base(32'h3000), .bias_base(32'd0),
        .lhs_zp(32'sd0), .rhs_zp(32'sd0), .dst_zp(32'sd0),
        .q_mult_pt(32'sh40000000), .q_shift_pt(32'sd0), .use_per_channel(1'b0),
        .k(32'd16), .n(32'd32), .m(32'd16),
        .lhs_row_stride_b(input_s16 ? 32'd64 : 32'd32),
        .rhs_col_stride_b(32'd32), .dst_row_stride_b(32'd16),
        .act_min(-32'sd128), .act_max(32'sd127),
        .m_axi_arvalid(arvalid), .m_axi_arready(1'b1), .m_axi_araddr(),
        .m_axi_arlen(), .m_axi_arsize(), .m_axi_arburst(),
        .m_axi_rvalid(1'b0), .m_axi_rready(), .m_axi_rdata(64'd0),
        .m_axi_rresp(2'd0), .m_axi_rlast(1'b0),
        .m_axi_awvalid(awvalid), .m_axi_awready(1'b1), .m_axi_awaddr(),
        .m_axi_awlen(), .m_axi_awsize(), .m_axi_awburst(),
        .m_axi_wvalid(wvalid), .m_axi_wready(1'b1), .m_axi_wdata(),
        .m_axi_wstrb(), .m_axi_wlast(), .m_axi_bvalid(1'b0),
        .m_axi_bready(), .m_axi_bresp(2'd0)
    );

    // 共享存储不可用时，配置错误必须在任何存储事务启动之前完成。
    always @(posedge clk) begin
        if (rst_n) begin
            checked_cycles <= checked_cycles + 1;
            assert (!arvalid && !awvalid && !wvalid)
                else $fatal(1, "Invalid storage configuration issued an AXI transaction");
            assert (!u_dut.u_matrix_engine.o_exec_dma_job_init &&
                    !u_dut.u_matrix_engine.frame_command_valid &&
                    !u_dut.u_matrix_engine.init_cfg_ia &&
                    !u_dut.u_matrix_engine.init_cfg_weight &&
                    !u_dut.u_matrix_engine.init_cfg_bias &&
                    !u_dut.u_matrix_engine.init_cfg_requant &&
                    !u_dut.u_matrix_engine.init_cfg_oa)
                else $fatal(1, "Invalid storage configuration initialized execution");
        end
    end

    initial begin : run_cases
        integer wait_cycles;
        repeat (5) @(negedge clk);
        rst_n = 1'b1;
        repeat (3) @(negedge clk);
        assert (!u_dut.SHARED_RAM_ENABLED && u_dut.FRAME_EXEC_ENABLED)
            else $fatal(1, "Test parameters do not cover both matrix schedulers");
        for (integer frame = 0; frame < 2; frame = frame + 1) begin
            for (integer mode = 0; mode < 2; mode = mode + 1) begin
                for (integer width = 0; width < 2; width = width + 1) begin
                    wait_cycles = 0;
                    while (!sa_ready && wait_cycles < 1000) begin
                        @(negedge clk);
                        wait_cycles = wait_cycles + 1;
                    end
                    assert (sa_ready) else $fatal(1, "NPU did not accept the next task");
                    dataflow_mode = 1'(mode);
                    input_s16 = 1'(width);
                    ps_control = frame != 0 ? 32'd3 : 32'd1;
                    calc_start = 1'b1;
                    @(negedge clk);
                    calc_start = 1'b0;
                    wait_cycles = 0;
                    while (!done_valid && wait_cycles < 1000) begin
                        @(negedge clk);
                        wait_cycles = wait_cycles + 1;
                    end
                    assert (done_valid && err_code == 2'b01)
                        else $fatal(1, "Storage error did not complete: frame=%0d mode=%0d width=%0d", frame, mode, width);
                    assert (u_dut.u_matrix_engine.o_frame_mode_q == 1'(frame))
                        else $fatal(1, "Selected scheduler was not exercised");
                    // 完成接收暂停期间，错误状态与完成有效信号必须保持。
                    repeat (5) begin
                        @(negedge clk);
                        assert (done_valid && err_code == 2'b01)
                            else $fatal(1, "Completion changed while the receiver was paused");
                    end
                    done_ready = 1'b1;
                    @(negedge clk);
                    done_ready = 1'b0;
                    repeat (4) @(negedge clk);
                    assert (!done_valid) else $fatal(1, "Completion handshake did not retire");
                    completed_tasks = completed_tasks + 1;
                end
            end
        end
        $display("NO_LOCAL_STORAGE_PASS tasks=%0d cycles=%0d", completed_tasks, checked_cycles);
        $finish;
    end
endmodule

`default_nettype wire
