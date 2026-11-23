// SPDX-License-Identifier: Apache-2.0
`ifndef SYNTHESIS
`default_nettype none

// 检查完整组预留、输入容量和输出释放，复位或清空期间暂停检查。
module requant_group_buffer_observer #(
    parameter int unsigned p_rows = 512
);
    localparam int p_count_width = (p_rows <= 1) ? 1 : $clog2(p_rows + 1);
    logic [p_count_width-1:0] expected_rows_q;

    // 观察器独立记录已预留、尚未到达的输入行。
    always_ff @(posedge requant_group_buffer.clk or negedge requant_group_buffer.rst_n) begin
        if (!requant_group_buffer.rst_n) expected_rows_q <= '0;
        else if (requant_group_buffer.i_clear) expected_rows_q <= '0;
        else if (requant_group_buffer.i_group_start)
            expected_rows_q <= p_count_width'(requant_group_buffer.i_group_rows) -
                               p_count_width'(requant_group_buffer.push_row);
        else if (requant_group_buffer.push_row) expected_rows_q <= expected_rows_q - 1'b1;
    end

    always_ff @(posedge requant_group_buffer.clk) begin
        if (requant_group_buffer.rst_n && !requant_group_buffer.i_clear) begin
            if (requant_group_buffer.i_group_start) begin
                assert(requant_group_buffer.o_group_ready &&
                       requant_group_buffer.i_group_rows != 0 &&
                       requant_group_buffer.i_group_rows <= p_rows);
                assert(requant_group_buffer.stored_rows_q == 0 &&
                       !requant_group_buffer.head_valid_q &&
                       !requant_group_buffer.i_output_valid);
            end
            if (requant_group_buffer.push_row) begin
                assert(requant_group_buffer.i_group_start || expected_rows_q != 0);
                assert(requant_group_buffer.stored_rows_q < p_rows || requant_group_buffer.read_row);
            end
            if (requant_group_buffer.i_output_valid) assert(requant_group_buffer.pending_rows_q != 0);
        end
    end
endmodule

bind requant_group_buffer requant_group_buffer_observer #(.p_rows(p_rows)) tb_observer();

`default_nettype wire
`endif
