`default_nettype none

// 先预留完整输出组，再接收阵列行；预留覆盖阵列、缓存和量化流水中的全部结果。
module requant_group_buffer #(
    parameter int unsigned p_lanes = 16,
    parameter int unsigned p_rows = 512
) (
    input  wire logic clk /* 工作时钟 */,
    input  wire logic rst_n /* 低有效复位 */,
    input  wire logic i_clear /* 清除当前缓存占用和分组预留状态 */,
    input  wire logic i_group_start /* 为新的输出分组预留完整缓存空间 */,
    input  wire logic [31:0] i_group_rows /* 新输出分组需要保存的结果行数 */,
    output logic o_group_ready /* 缓存可为下一完整输出分组预留空间 */,
    input  wire logic i_row_valid /* 阵列提供的当前结果行有效 */,
    input  wire logic i_row_tile_done /* 当前输入结果行为矩阵块结束行 */,
    input  wire logic signed [31:0] i_row_data [p_lanes] /* 阵列提供的完整32 位累加结果行 */,
    output logic o_row_valid /* 缓存向量化通路提供有效结果行 */,
    output logic o_row_tile_done /* 当前输出结果行为矩阵块结束行 */,
    output logic signed [31:0] o_row_data [p_lanes] /* 缓存送入量化通路的完整结果行 */,
    input  wire logic i_row_ready /* 量化通路可接收当前缓存结果行 */,
    input  wire logic i_output_valid /* 一行结果已完成后续输出，可释放对应预留 */
);
    localparam int p_addr_width = (p_rows <= 1) ? 1 : $clog2(p_rows);
    localparam int p_count_width = (p_rows <= 1) ? 1 : $clog2(p_rows + 1);
    localparam int p_row_width = 32 * p_lanes + 1;

    logic [p_addr_width-1:0] write_addr_q, read_addr_q;
    logic [p_count_width-1:0] stored_rows_q;
    logic [p_count_width-1:0] stored_rows_next;
    logic [p_count_width-1:0] pending_rows_q;
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
    // 各位独立准备加一与减一的翻转条件，读写事件只选择最终计数位。
    for (genvar bit_index = 0; bit_index < p_count_width; bit_index++) begin : g_stored_count
        logic increase_toggle, decrease_toggle;
        if (bit_index == 0) begin : g_low_bit
            assign increase_toggle = 1'b1;
            assign decrease_toggle = 1'b1;
        end else begin : g_upper_bit
            assign increase_toggle = &stored_rows_q[bit_index-1:0];
            assign decrease_toggle = ~|stored_rows_q[bit_index-1:0];
        end
        always_comb begin
            stored_rows_next[bit_index] = stored_rows_q[bit_index];
            case ({push_row, read_row})
                2'b10: stored_rows_next[bit_index] = stored_rows_q[bit_index] ^ increase_toggle;
                2'b01: stored_rows_next[bit_index] = stored_rows_q[bit_index] ^ decrease_toggle;
                default: begin end
            endcase
        end
    end
    for (genvar lane = 0; lane < p_lanes; lane++) begin : g_row_word
        assign storage_i_wr_data[32*lane +: 32] = i_row_data[lane];
        assign o_row_data[lane] = $signed(storage_o_rd_data[32*lane +: 32]);
    end

`ifdef ASIC_SRAM
    // 每行数据和完成标志共用地址，包装模块按逻辑深度选择存储尺寸。
    // 读取使能控制宏输出保持，最后一批发射时可同步读取下一行。
    smic40_sram_1r1w #(
        .DATA_WIDTH(p_row_width), .DEPTH(p_rows), .ADDR_WIDTH(p_addr_width)
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
            stored_rows_q <= stored_rows_next;
            if (read_row) head_valid_q <= 1'b1;
            else if (consume_row) head_valid_q <= 1'b0;
        end
    end

    // 整行输出才释放预留；阵列尚未产生的行同样占用已预留容量。
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            pending_rows_q <= '0;
        end else if (i_clear) begin
            pending_rows_q <= '0;
        end else if (i_group_start) begin
            pending_rows_q <= p_count_width'(i_group_rows);
        end else if (i_output_valid) begin
            pending_rows_q <= pending_rows_q - 1'b1;
        end
    end

endmodule

`default_nettype wire
