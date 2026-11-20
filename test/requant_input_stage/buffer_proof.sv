// SPDX-License-Identifier: Apache-2.0
// 完整组预留同时覆盖生产者寄存、行缓存和量化流水。
module requant_input_stage_proof #(
    parameter int p_rows = 512
) (
    input logic clk, rst_n, i_clear,
    input logic i_group_start, i_source_valid, i_row_ready, i_output_valid,
    input logic [31:0] i_group_rows,
    input logic i_data, i_tile_done
);
    localparam int p_count_width = (p_rows <= 1) ? 1 : $clog2(p_rows+1);
    logic [p_count_width-1:0] source_expected_q, issued_rows_q;
    logic source_valid_q, source_data_q, source_tile_done_q;
    logic group_ready, row_valid, row_tile_done, consume_row;
    logic signed [31:0] row_data [1], output_data [1];

    assign row_data[0] = {31'd0, source_data_q};
    assign consume_row = row_valid && i_row_ready;

    // 输入数据与两个标志共同经过一个边沿，取消同时清除待接收行。
    always_ff @(posedge clk) begin
        if (!rst_n || i_clear) begin
            source_valid_q <= 1'b0;
            source_data_q <= 1'b0;
            source_tile_done_q <= 1'b0;
        end else begin
            source_valid_q <= i_source_valid;
            source_data_q <= i_data;
            source_tile_done_q <= i_tile_done;
        end
    end

    requant_group_buffer #(.p_lanes(1), .p_rows(p_rows)) u_buffer (
        .clk(clk), .rst_n(rst_n), .i_clear(i_clear),
        .i_group_start(i_group_start), .i_group_rows(i_group_rows),
        .o_group_ready(group_ready),
        .i_row_valid(source_valid_q), .i_row_tile_done(source_tile_done_q), .i_row_data(row_data),
        .o_row_valid(row_valid), .o_row_tile_done(row_tile_done), .o_row_data(output_data),
        .i_row_ready(i_row_ready), .i_output_valid(i_output_valid)
    );

    always_comb begin
        if (rst_n && !i_clear) begin
            assume(!i_group_start || (group_ready && i_group_rows > 0 && i_group_rows <= p_rows));
            assume(!i_source_valid || i_group_start || source_expected_q != 0);
            assume(!i_output_valid || issued_rows_q != 0);
        end
    end

    always_ff @(posedge clk) begin
        if (!rst_n || i_clear) begin
            source_expected_q <= '0;
            issued_rows_q <= '0;
        end else begin
            if (i_group_start)
                source_expected_q <= p_count_width'(i_group_rows) - p_count_width'(i_source_valid);
            else if (i_source_valid)
                source_expected_q <= source_expected_q - 1'b1;
            case ({consume_row, i_output_valid})
                2'b10: issued_rows_q <= issued_rows_q + 1'b1;
                2'b01: issued_rows_q <= issued_rows_q - 1'b1;
                default: begin end
            endcase
        end
    end

    always_comb begin
        if (rst_n) begin
            assert(u_buffer.pending_rows_q <= p_rows);
            assert(u_buffer.expected_rows_q <= p_rows);
            assert(u_buffer.stored_rows_q <= p_rows);
            assert(source_expected_q <= p_rows);
            assert(issued_rows_q <= p_rows);
            assert(32'(u_buffer.expected_rows_q) == 32'(source_expected_q) + 32'(source_valid_q));
            assert(32'(u_buffer.pending_rows_q) == 32'(source_expected_q) + 32'(source_valid_q) +
                32'(u_buffer.stored_rows_q) + 32'(row_valid) + 32'(issued_rows_q));
            if (group_ready) begin
                assert(source_expected_q == 0 && !source_valid_q);
                assert(u_buffer.stored_rows_q == 0 && !row_valid && issued_rows_q == 0);
            end
            if (u_buffer.read_row) assert(u_buffer.stored_rows_q != 0);
            if (u_buffer.push_row && !i_group_start) assert(u_buffer.stored_rows_q < p_rows);
            assert(u_buffer.write_addr_q < p_rows && u_buffer.read_addr_q < p_rows);
        end
    end
endmodule
