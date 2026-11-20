`default_nettype none

// 先预留完整输出组，再接收阵列行；预留覆盖阵列、缓存和量化流水中的全部结果。
module requant_group_buffer #(
    parameter int unsigned p_lanes = 16,
    parameter int unsigned p_rows = 512
) (
    input  wire logic clk,
    input  wire logic rst_n,
    input  wire logic i_clear,
    input  wire logic i_group_start,
    input  wire logic [31:0] i_group_rows,
    output logic o_group_ready,
    input  wire logic i_row_valid,
    input  wire logic i_row_tile_done,
    input  wire logic signed [31:0] i_row_data [p_lanes],
    output logic o_row_valid,
    output logic o_row_tile_done,
    output logic signed [31:0] o_row_data [p_lanes],
    input  wire logic i_row_ready,
    input  wire logic i_output_valid
);
    localparam int p_addr_width = (p_rows <= 1) ? 1 : $clog2(p_rows);
    localparam int p_count_width = (p_rows <= 1) ? 1 : $clog2(p_rows + 1);
    localparam int p_row_width = 32 * p_lanes + 1;

    logic [p_addr_width-1:0] write_addr_q, read_addr_q;
    logic [p_count_width-1:0] stored_rows_q;
    logic [p_count_width-1:0] expected_rows_q, pending_rows_q;
    logic head_valid_q;
    logic push_row, read_row, consume_row;
    logic storage_i_wr_en, storage_i_rd_en, storage_i_wr_mask;
    logic [p_addr_width-1:0] storage_i_wr_addr, storage_i_rd_addr;
    logic [p_row_width-1:0] storage_i_wr_data, storage_o_rd_data;

    assign o_group_ready = pending_rows_q == '0;
    assign push_row = i_row_valid && !i_clear;
    assign consume_row = head_valid_q && i_row_ready && !i_clear;
    assign read_row = !i_clear && (stored_rows_q != '0) &&
        (!head_valid_q || consume_row);
    assign o_row_valid = head_valid_q;
    assign o_row_tile_done = storage_o_rd_data[p_row_width-1];
    assign storage_i_wr_en = push_row;
    assign storage_i_wr_addr = write_addr_q;
    assign storage_i_wr_mask = 1'b1;
    assign storage_i_wr_data[p_row_width-1] = i_row_tile_done;
    assign storage_i_rd_en = read_row;
    assign storage_i_rd_addr = read_addr_q;
    for (genvar lane = 0; lane < p_lanes; lane++) begin : g_row_word
        assign storage_i_wr_data[32*lane +: 32] = i_row_data[lane];
        assign o_row_data[lane] = $signed(storage_o_rd_data[32*lane +: 32]);
    end

`ifdef ASIC_SRAM
    // 每行数据和完成标志共用地址，128 行宏按宽度与深度扩展。
    // 读取使能控制宏输出保持，最后一批发射时可同步读取下一行。
    smic40_sram_1r1w #(
        .DATA_WIDTH(p_row_width), .DEPTH(p_rows), .ADDR_WIDTH(p_addr_width),
        .MACRO_DEPTH(128)
    ) u_rows (
        .clk(clk),
        .write_enable(storage_i_wr_en), .write_address(storage_i_wr_addr),
        .write_data(storage_i_wr_data), .write_mask({p_row_width{storage_i_wr_mask}}),
        .read_enable(storage_i_rd_en), .read_address(storage_i_rd_addr),
        .read_data(storage_o_rd_data)
    );
`else
    regfile #(
        .p_data_width(p_row_width), .p_depth(p_rows), .p_addr_width(p_addr_width),
        .p_write_unit(p_row_width), .p_sync_read(1'b1)
    ) u_rows (
        .clk(clk),
        .i_wr_en(storage_i_wr_en), .i_wr_addr(storage_i_wr_addr),
        .i_wr_data(storage_i_wr_data), .i_wr_mask(storage_i_wr_mask),
        .i_rd_en(storage_i_rd_en), .i_rd_addr(storage_i_rd_addr),
        .o_rd_data(storage_o_rd_data)
    );
`endif

    // 读端保持整行供各批次运算共用，最后一批发射边沿可同步读取下一行。
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            write_addr_q <= '0;
            read_addr_q <= '0;
            stored_rows_q <= '0;
            head_valid_q <= 1'b0;
        end else if (i_clear) begin
            write_addr_q <= '0;
            read_addr_q <= '0;
            stored_rows_q <= '0;
            head_valid_q <= 1'b0;
        end else begin
            if (push_row) begin
                write_addr_q <= (write_addr_q == p_addr_width'(p_rows-1)) ?
                    '0 : write_addr_q + 1'b1;
            end
            if (read_row) begin
                read_addr_q <= (read_addr_q == p_addr_width'(p_rows-1)) ?
                    '0 : read_addr_q + 1'b1;
            end
            case ({push_row, read_row})
                2'b10: stored_rows_q <= stored_rows_q + 1'b1;
                2'b01: stored_rows_q <= stored_rows_q - 1'b1;
                default: begin end
            endcase
            if (read_row) head_valid_q <= 1'b1;
            else if (consume_row) head_valid_q <= 1'b0;
        end
    end

    // 整行输出才释放预留；阵列尚未产生的行同样占用已预留容量。
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            expected_rows_q <= '0;
            pending_rows_q <= '0;
        end else if (i_clear) begin
            expected_rows_q <= '0;
            pending_rows_q <= '0;
        end else begin
            if (i_group_start) begin
                expected_rows_q <= p_count_width'(i_group_rows) - p_count_width'(push_row);
                pending_rows_q <= p_count_width'(i_group_rows);
            end else begin
                if (push_row) expected_rows_q <= expected_rows_q - 1'b1;
                if (i_output_valid) pending_rows_q <= pending_rows_q - 1'b1;
            end
        end
    end

`ifndef SYNTHESIS
    always_ff @(posedge clk) begin
        if (rst_n && !i_clear) begin
            if (i_group_start) begin
                assert(o_group_ready && i_group_rows != 0 && i_group_rows <= p_rows);
                assert(stored_rows_q == 0 && !head_valid_q && !i_output_valid);
            end
            if (push_row) begin
                assert(i_group_start || expected_rows_q != 0);
                assert(stored_rows_q < p_rows || read_row);
            end
            if (i_output_valid) assert(pending_rows_q != 0);
        end
    end
`endif
endmodule

`default_nettype wire
