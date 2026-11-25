`default_nettype none

module kernel_loader_buffer #(
    parameter int unsigned DATA_WIDTH = 8,
    parameter int unsigned SIZE = 4
) (
    input  wire logic clk,
    input  wire logic rst_n,
    input  wire logic cache_flush = 1'b0,
    input  wire logic discard_head = 1'b0,
    input  wire logic load_start,
    output logic load_slot_id,
    input  wire logic row_valid,
    input  wire logic row_slot,
    input  wire logic [$clog2(SIZE)-1:0] row_idx,
    input  wire logic signed [DATA_WIDTH-1:0] row_data [SIZE],
    input  wire logic load_done,
    input  wire logic done_slot,
    input  wire logic send_start,
    output logic load_ready,
    output logic load_commit,
    output logic load_commit_slot,
    output logic discard_ready,
    output logic weight_data_valid,
    output logic weight_sending_done,
    output logic store_weight_req,
    output logic signed [DATA_WIDTH-1:0] weight_out [SIZE]
);
    //! 0. 常量与内部信号
    //! --------------------

    localparam int p_slot_count = 2;
    localparam int p_storage_slots = 3;
    localparam int p_index_width = (SIZE <= 1) ? 1 : $clog2(SIZE);
    localparam int p_valid_width = $clog2(SIZE + 1);
    localparam int p_row_width = DATA_WIDTH * SIZE;
    localparam int p_depth = p_storage_slots * SIZE;
    localparam int p_addr_width = $clog2(p_depth);

    logic wr_slot, rd_slot;
    logic [p_slot_count-1:0] slot_reserved, slot_loaded;
    logic [p_valid_width-1:0] load_valid_cols [p_slot_count];
    logic [p_valid_width-1:0] slot_valid_cols [p_slot_count];
    logic [p_valid_width-1:0] send_valid_cols;
    logic [p_index_width-1:0] emit_col_idx;
    logic [p_index_width-1:0] output_column_q;
    logic [SIZE-1:0] output_lane_valid_q;
    logic send_active, send_pending, send_prefetch;
    logic row_valid_q, row_slot_q, load_done_q, done_slot_q;
    logic [p_index_width-1:0] row_idx_q;
    logic [p_row_width-1:0] row_data_vec, row_data_vec_q;
    logic [1:0] slot_storage [p_slot_count];
    logic [1:0] active_storage;
    logic load_fire, send_fire, discard_fire, emit_fire, send_complete_event;
    logic [p_valid_width-1:0] row_count_nxt;
    logic [p_index_width-1:0] read_column;
    logic [p_index_width:0] read_row_ext [SIZE];
    logic [p_index_width-1:0] read_row [SIZE];
    logic [p_index_width:0] output_bank_ext [SIZE];
    logic [p_index_width-1:0] output_bank [SIZE];
    logic [DATA_WIDTH-1:0] output_column_data [SIZE];

    logic column_i_wr_en, column_i_rd_en;
    logic [p_addr_width-1:0] column_i_wr_addr;
    logic [p_addr_width-1:0] column_i_rd_addr [SIZE];
    logic [DATA_WIDTH-1:0] column_i_wr_data [SIZE];
    logic column_i_wr_mask;
    logic [DATA_WIDTH-1:0] column_o_rd_data [SIZE];

    //! 1. 输入与发送地址
    //! --------------------

    assign load_fire = load_start && load_ready;
    assign discard_fire = discard_head && discard_ready;
    assign send_fire = send_start && weight_data_valid && !discard_fire;
    assign emit_fire = !send_pending && (send_active || send_prefetch);
    assign send_complete_event = emit_fire && ((SIZE == 1) || (!send_prefetch && emit_col_idx == '0));
    assign row_count_nxt = row_valid_q && ((p_valid_width'(row_idx_q) + p_valid_width'(1)) > load_valid_cols[row_slot_q]) ?
        (p_valid_width'(row_idx_q) + p_valid_width'(1)) : load_valid_cols[row_slot_q];
    assign read_column = send_prefetch ? p_index_width'(SIZE - 1) : emit_col_idx;

    // 每列存储器使用一个同步读端口和一个写端口，完整行并行写入各列。
    // 输出列号与同步读取同时更新，生成阵列要求的对角排列。
    assign column_i_wr_en = row_valid_q && slot_reserved[row_slot_q] && !cache_flush;
    assign column_i_wr_addr = p_addr_width'(slot_storage[row_slot_q] * SIZE) + p_addr_width'(row_idx_q);
    assign column_i_wr_mask = 1'b1;
    assign column_i_rd_en = rst_n && !cache_flush && emit_fire;
    for (genvar column = 0; column < SIZE; column++) begin : g_column_address
        assign row_data_vec[column*DATA_WIDTH+:DATA_WIDTH] = row_data[column];
        assign column_i_wr_data[column] = row_data_vec_q[column*DATA_WIDTH+:DATA_WIDTH];
        assign read_row_ext[column] = (read_column <= p_index_width'(column)) ?
            ((p_index_width+1)'(column) - {1'b0, read_column}) :
            ((p_index_width+1)'(column + SIZE) - {1'b0, read_column});
        assign read_row[column] = read_row_ext[column][p_index_width-1:0];
        assign column_i_rd_addr[column] = p_addr_width'(active_storage * SIZE) + p_addr_width'(read_row[column]);
        assign output_bank_ext[column] = {1'b0, output_column_q} + (p_index_width+1)'(column);
        assign output_bank[column] = (output_bank_ext[column] >= (p_index_width+1)'(SIZE)) ?
            p_index_width'(output_bank_ext[column] - (p_index_width+1)'(SIZE)) :
            p_index_width'(output_bank_ext[column]);
        assign weight_out[column] = output_lane_valid_q[column] ?
            $signed(output_column_data[column]) : '0;
    end

    if ((SIZE & (SIZE - 1)) == 0) begin : g_output_rotation
        localparam int p_stages = (p_index_width + 1) / 2;
        logic [DATA_WIDTH-1:0] rotated_data [p_stages+1][SIZE];
        // 每级并行选择四种固定距离，复用前一级的完整通道结果。
        for (genvar column = 0; column < SIZE; column++) begin : g_input
            assign rotated_data[0][column] = column_o_rd_data[column];
        end
        for (genvar stage = 0; stage < p_stages; stage++) begin : g_stage
            localparam int p_low_bit = (p_index_width > 2 * stage + 1) ?
                p_index_width - 2 * stage - 2 : 0;
            localparam int p_select_bits = (p_index_width > 2 * stage + 1) ? 2 : 1;
            for (genvar column = 0; column < SIZE; column++) begin : g_column
                kernel_column_select4 #(.p_width(DATA_WIDTH)) u_select (
                    .i_select(2'(output_column_q[p_low_bit +: p_select_bits])),
                    .i_data0(rotated_data[stage][column]),
                    .i_data1(rotated_data[stage][(column + (1 << p_low_bit)) % SIZE]),
                    .i_data2(rotated_data[stage][(column + (2 << p_low_bit)) % SIZE]),
                    .i_data3(rotated_data[stage][(column + (3 << p_low_bit)) % SIZE]),
                    .o_data(rotated_data[stage+1][column])
                );
            end
        end
        for (genvar column = 0; column < SIZE; column++) begin : g_output
            always_comb begin
                case (^output_column_q)
                    1'b0, 1'b1: output_column_data[column] = rotated_data[p_stages][column];
                    // 未知列号按照数组索引规则传播到所选数据。
                    default: output_column_data[column] = column_o_rd_data[output_bank[column]];
                endcase
            end
        end
    end else begin : g_output_index
        for (genvar column = 0; column < SIZE; column++) begin : g_column
            assign output_column_data[column] = column_o_rd_data[output_bank[column]];
        end
    end

    //! 2. 输入寄存与槽位管理
    //! ------------------------

    always_ff @(posedge clk) begin
        if (!rst_n || cache_flush) begin
            row_valid_q <= 1'b0;
            row_slot_q <= 1'b0;
            row_idx_q <= '0;
            row_data_vec_q <= '0;
            load_done_q <= 1'b0;
            done_slot_q <= 1'b0;
        end else begin
            row_valid_q <= row_valid;
            row_slot_q <= row_slot;
            row_idx_q <= row_idx;
            row_data_vec_q <= row_data_vec;
            load_done_q <= load_done;
            done_slot_q <= done_slot;
        end
    end

    // 两个逻辑槽位用于预取，第三个物理槽位保存正在发送的权重。
    // send_pending 周期交换物理槽位，释放的逻辑槽位可立即接收下一块权重。
    always_ff @(posedge clk) begin
        if (!rst_n || cache_flush) begin
            wr_slot <= 1'b0;
            rd_slot <= 1'b0;
            slot_reserved <= '0;
            slot_loaded <= '0;
            slot_storage[0] <= 2'd0;
            slot_storage[1] <= 2'd1;
            active_storage <= 2'd2;
            load_commit <= 1'b0;
            load_commit_slot <= 1'b0;
            for (int slot = 0; slot < p_slot_count; slot++) begin
                load_valid_cols[slot] <= '0;
                slot_valid_cols[slot] <= '0;
            end
        end else begin
            load_commit <= 1'b0;
            if (load_fire) begin
                slot_reserved[wr_slot] <= 1'b1;
                slot_loaded[wr_slot] <= 1'b0;
                load_valid_cols[wr_slot] <= '0;
                wr_slot <= ~wr_slot;
            end
            if (row_valid_q) begin
                load_valid_cols[row_slot_q] <= row_count_nxt;
            end
            // 完成指示与最后一行可以同时到达，行数使用本周期更新值。
            if (load_done_q) begin
                load_commit <= 1'b1;
                load_commit_slot <= done_slot_q;
                slot_loaded[done_slot_q] <= 1'b1;
                slot_valid_cols[done_slot_q] <= (row_valid_q && row_slot_q == done_slot_q) ?
                    row_count_nxt : load_valid_cols[done_slot_q];
            end
            if (discard_fire) begin
                slot_reserved[rd_slot] <= 1'b0;
                slot_loaded[rd_slot] <= 1'b0;
                rd_slot <= ~rd_slot;
            end
            if (send_pending) begin
                slot_reserved[rd_slot] <= 1'b0;
                slot_loaded[rd_slot] <= 1'b0;
                active_storage <= slot_storage[rd_slot];
                slot_storage[rd_slot] <= active_storage;
            end
            if (send_complete_event) begin
                rd_slot <= ~rd_slot;
            end
        end
    end

    // 接收发送请求后的第二个周期输出首组权重，后续每周期输出一组。
    always_ff @(posedge clk) begin
        if (!rst_n || cache_flush) begin
            send_valid_cols <= '0;
            emit_col_idx <= '0;
            send_active <= 1'b0;
            send_pending <= 1'b0;
            send_prefetch <= 1'b0;
            store_weight_req <= 1'b0;
            weight_sending_done <= 1'b0;
            output_column_q <= '0;
            output_lane_valid_q <= '0;
        end else begin
            store_weight_req <= 1'b0;
            weight_sending_done <= 1'b0;
            if (send_fire) begin
                send_pending <= 1'b1;
                send_valid_cols <= slot_valid_cols[rd_slot];
            end
            if (send_pending) begin
                send_pending <= 1'b0;
                send_prefetch <= 1'b1;
            end else if (emit_fire) begin
                send_prefetch <= 1'b0;
                send_active <= !send_complete_event;
                store_weight_req <= 1'b1;
                weight_sending_done <= send_complete_event;
                output_column_q <= read_column;
                for (int column = 0; column < SIZE; column++) begin
                    output_lane_valid_q[column] <= p_valid_width'(column) < send_valid_cols;
                end
                if (!send_complete_event) begin
                    emit_col_idx <= send_prefetch ? p_index_width'(SIZE - 2) : (emit_col_idx - 1'b1);
                end
            end
        end
    end

    //! 3. 输出与权重存储器
    //! ----------------------

    assign load_slot_id = wr_slot;
    assign load_ready = !cache_flush && !slot_reserved[wr_slot];
    assign weight_data_valid = !cache_flush && slot_loaded[rd_slot] && !send_active && !send_pending && !send_prefetch;
    assign discard_ready = weight_data_valid;

    generate if (1) begin : g_column_storage
        for (genvar column = 0; column < SIZE; column++) begin : g_column_ram
            regfile #(
                .p_data_width(DATA_WIDTH),
                .p_depth(p_depth),
                .p_addr_width(p_addr_width),
                .p_write_unit(DATA_WIDTH),
                .p_sync_read(1'b1),
                .p_ram_style("block"),
                .p_asic_force_sram(SIZE == 16 && DATA_WIDTH == 16)
            ) u_column (
                .clk(clk),
                .i_wr_en(column_i_wr_en),
                .i_wr_addr(column_i_wr_addr),
                .i_wr_data(column_i_wr_data[column]),
                .i_wr_mask(column_i_wr_mask),
                .i_rd_en(column_i_rd_en),
                .i_rd_addr(column_i_rd_addr[column]),
                .o_rd_data(column_o_rd_data[column])
            );
        end
    end endgenerate

endmodule

// 一个通道内完成四路数据选择，分组边界保存共享的中间排列。
(* keep_hierarchy = "yes" *)
module kernel_column_select4 #(
    parameter int unsigned p_width = 16
) (
    input wire logic [1:0] i_select,
    input wire logic [p_width-1:0] i_data0, i_data1, i_data2, i_data3,
    output logic [p_width-1:0] o_data
);
    assign o_data = i_select[1] ? (i_select[0] ? i_data3 : i_data2) :
        (i_select[0] ? i_data1 : i_data0);
endmodule

`default_nettype wire
