// SPDX-License-Identifier: Apache-2.0
`ifndef SYNTHESIS
`default_nettype none

// 检查完整组预留、输入容量和输出释放，复位或清空期间暂停检查。
module requant_group_buffer_observer #(
    parameter int unsigned p_rows = 512
);
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
                assert(requant_group_buffer.i_group_start || requant_group_buffer.expected_rows_q != 0);
                assert(requant_group_buffer.stored_rows_q < p_rows || requant_group_buffer.read_row);
            end
            if (requant_group_buffer.i_output_valid) assert(requant_group_buffer.pending_rows_q != 0);
        end
    end
endmodule

bind requant_group_buffer requant_group_buffer_observer #(.p_rows(p_rows)) tb_observer();

`default_nettype wire
`endif
