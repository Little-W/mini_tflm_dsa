// SPDX-License-Identifier: Apache-2.0
module weight_prefetch_npu_observer #(parameter int p_size=16);
    integer loaded_rows=0, burst_rows=0;
    longint unsigned commits=0, stores=0, bursts=0, frame_starts=0, resident_starts=0;
    logic resident=0, controller_active=0;

    always @(posedge npu_top.clk) begin
        if (!npu_top.core_rst_n) begin
            loaded_rows <= 0;
            burst_rows <= 0;
            controller_active <= 0;
        end else begin
            if (npu_top.ctrl_sa_ready || npu_top.cfg_stage2_fire)
                controller_active <= 0;
            if (npu_top.cfg_stage2_fire) begin
                loaded_rows <= 0;
                burst_rows <= 0;
            end else begin
                if (npu_top.u_matrix_engine.weight_commit) begin
                    assert(loaded_rows >= p_size)
                        else $fatal(1,"Weight commit requires complete coverage");
                    loaded_rows <= npu_top.u_matrix_engine.store_weight_req ? 1 : 0;
                    commits <= commits+1;
                end else if (npu_top.u_matrix_engine.store_weight_req) begin
                    if (loaded_rows < p_size) loaded_rows <= loaded_rows+1;
                end
                if (npu_top.u_matrix_engine.store_weight_req) stores <= stores+1;
                if (npu_top.u_matrix_engine.u_kernel_loader.buf_weight_sending_done) begin
                    assert(npu_top.u_matrix_engine.u_kernel_loader.buf_store_weight_req && burst_rows==p_size-1)
                        else $fatal(1,"Kernel buffer burst length differs");
                    burst_rows <= 0;
                    bursts <= bursts+1;
                end else if (npu_top.u_matrix_engine.u_kernel_loader.buf_store_weight_req) begin
                    assert(burst_rows < p_size-1);
                    burst_rows <= burst_rows+1;
                end
            end
            if (npu_top.u_matrix_engine.ctrl_calc_start && npu_top.ctrl_sa_ready) begin
                if (!npu_top.cfg_stage2_fire) begin
                    assert(!npu_top.u_matrix_engine.u_kernel_loader.u_buf.send_active &&
                           !npu_top.u_matrix_engine.u_kernel_loader.u_buf.send_pending &&
                           !npu_top.u_matrix_engine.u_kernel_loader.u_buf.send_prefetch &&
                           !npu_top.u_matrix_engine.u_kernel_loader.buf_store_weight_req &&
                           !npu_top.u_matrix_engine.store_weight_req &&
                           !npu_top.u_matrix_engine.u_npu_controller.shadow_inflight)
                        else $fatal(1,"Frame control starts while weights are being emitted");
                    frame_starts <= frame_starts+1;
                end
            end
            // INIT 边沿完成任务配置，随后 WEIGHT_START 使用当前驻留模式。
            if (npu_top.u_matrix_engine.u_npu_controller.current_state == 4'b0001) begin
                resident <= npu_top.frame_mode_q && npu_top.u_matrix_engine.frame_stationary_hit;
                controller_active <= 1;
                if (npu_top.frame_mode_q && npu_top.u_matrix_engine.frame_stationary_hit)
                    resident_starts <= resident_starts+1;
            end else if (controller_active && !npu_top.ctrl_sa_ready && !npu_top.cfg_stage2_fire) begin
                assert(resident == (npu_top.frame_mode_q && npu_top.u_matrix_engine.frame_stationary_hit))
                    else $fatal(1,"Resident weight mode changed during execution");
            end
        end
    end
    final $display("WEIGHT_PREFETCH_NPU_PASS commits=%0d stores=%0d bursts=%0d frame_starts=%0d resident_starts=%0d",
                   commits,stores,bursts,frame_starts,resident_starts);
endmodule

module weight_prefetch_array_observer #(parameter int p_size=16, parameter int p_width=16);
    logic signed [p_width-1:0] active_reference[p_size][p_size];
    logic signed [p_width-1:0] prefetch_reference[p_size][p_size];
    longint unsigned valid_rows=0, row_commit_overlaps=0, simultaneous_store_commit=0;

    for (genvar row=0;row<p_size;row++) begin:g_row
        for (genvar column=0;column<p_size;column++) begin:g_column
            // 交换式权重寄存器作为逐周期参考，提交和装载使用实际阵列的控制信号。
            always @(posedge compute_core.clk) begin
                if (compute_core.u_systolic_array.gen_row[row].row_commit_weight)
                    active_reference[row][column] <= prefetch_reference[row][column];
                if (compute_core.u_systolic_array.store_weight_req_col[column] &&
                    compute_core.u_systolic_array.gen_row[row].row_load_enable) begin
                    if (row==0) prefetch_reference[row][column] <= compute_core.weight_in[column];
                    else prefetch_reference[row][column] <= prefetch_reference[row-1][column];
                end else if (compute_core.u_systolic_array.gen_row[row].row_commit_weight) begin
                    prefetch_reference[row][column] <= active_reference[row][column];
                end
                if (compute_core.rst_n && compute_core.row_valid_pipe[row]) begin
                    assert(compute_core.u_systolic_array.gen_row[row].gen_col[column].ws_cell.selected_weight ==
                           active_reference[row][column])
                        else $fatal(1,"Valid array weight differs row=%0d column=%0d",row,column);
                end
            end
        end
    end
    always @(posedge compute_core.clk) if (compute_core.rst_n) begin
        for (int row=0;row<p_size;row++) begin
            if (compute_core.row_valid_pipe[row]) valid_rows=valid_rows+1;
        end
        if (compute_core.weight_commit && |compute_core.row_valid_pipe)
            row_commit_overlaps <= row_commit_overlaps+1;
        if (compute_core.weight_commit && compute_core.store_weight_req)
            simultaneous_store_commit <= simultaneous_store_commit+1;
    end
    final $display("WEIGHT_PREFETCH_ARRAY_PASS valid_rows=%0d weight_checks=%0d row_commit_overlaps=%0d simultaneous_store_commit=%0d",
                   valid_rows,valid_rows*p_size,row_commit_overlaps,simultaneous_store_commit);
endmodule

bind npu_top weight_prefetch_npu_observer #(.p_size(SIZE)) u_weight_prefetch_control_observer();
bind compute_core weight_prefetch_array_observer #(.p_size(SIZE),.p_width(WEIGHT_WIDTH)) u_weight_prefetch_array_observer();
