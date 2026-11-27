`default_nettype none

// 按小端字节顺序保存和输出 TFLM 的 INT16 激活数据。
module vec_s16_to_fifo #(
    parameter int unsigned VLEN  = 16,
    parameter int unsigned BANKS = 16,
    parameter int unsigned BUS_WIDTH = 32,
    parameter bit p_precomputed_watermark = 1'b0
) (
    input  wire logic                         clk /* 工作时钟 */,
    input  wire logic                         rst_n /* 低有效复位 */,
    input  wire logic                         in_valid /* 当前输入结果行有效 */,
    input  wire logic                         in_tile_done /* 当前输入结果行结束一个矩阵块 */,
    input  wire logic [VLEN*16-1:0]           in_vec_s16 /* 当前行的16 位有符号结果向量 */,
    output logic                         oa_fifo_req /* 已有完整结果块可供写回 */,
    input  wire logic [31:0]                  reserve_banks /* 当前计算分组需要预留的结果存储体数 */,
    input  wire logic [31:0]                  i_ready_bank_threshold /* 允许接收下一计算组的已完成存储体数量阈值 */,
    input  wire logic [$clog2(VLEN)-1:0]      vec_valid_num_col /* 当前矩阵块最后一个有效列的编号 */,
    output logic                         output_valid /* 当前输出数据拍有效 */,
    input  wire logic                         output_ready /* 下游可接收当前输出数据拍 */,
    output logic                         output_row_switch /* 当前输出数据拍结束一行 */,
    output logic [BUS_WIDTH/8-1:0]       output_mask /* 当前输出拍的有效字节掩码 */,
    output logic [BUS_WIDTH-1:0]         output_data /* 当前输出拍的总线数据 */,
    output logic                         fifo_full_flag /* 结果存储余量不足以接收下一计算组 */,
    input wire logic i_full_select = 1'b1, // 当前任务选择十六位输出缓冲。
    input wire logic i_output_pending = 1'b1, // 当前计算分组需要生成最终输出。
    input wire logic i_other_full = 1'b0, // 八位输出缓冲的容量阻塞状态。
    output logic o_issue_full // 所选输出缓冲需要暂停当前输入分组。
);

    localparam int PTR_WIDTH = (VLEN <= 1) ? 1 : $clog2(VLEN);
    localparam int COUNT_WIDTH = $clog2(VLEN + 1);
    localparam int ELEMENTS_PER_BEAT = BUS_WIDTH / 16;
    localparam int ELEMENT_SHIFT = $clog2(ELEMENTS_PER_BEAT);
    localparam int ROW_BEATS = (VLEN + ELEMENTS_PER_BEAT - 1) / ELEMENTS_PER_BEAT;
    localparam int BEAT_WIDTH = (ROW_BEATS <= 1) ? 1 : $clog2(ROW_BEATS);
    localparam int BANK_WIDTH = (BANKS <= 1) ? 1 : $clog2(BANKS);
    localparam int BANK_COUNT_WIDTH = (BANKS <= 1) ? 1 : $clog2(BANKS + 1);
    localparam int MEM_DEPTH = BANKS * VLEN;
    localparam int MEM_ADDR_W = (MEM_DEPTH <= 1) ? 1 : $clog2(MEM_DEPTH);
    localparam int p_column_mask_width = (1 << BEAT_WIDTH) * ELEMENTS_PER_BEAT;

    logic [COUNT_WIDTH-1:0] bank_count[0:BANKS-1];
    logic [BANKS-1:0] bank_ready;
    logic [BANK_COUNT_WIDTH-1:0] ready_bank_count_q;
    logic [COUNT_WIDTH-1:0] active_read_count_q;
    logic [BANK_WIDTH-1:0] write_bank;
    logic [BANK_WIDTH-1:0] read_bank;
    logic [PTR_WIDTH-1:0] write_ptr;
    logic [PTR_WIDTH-1:0] read_ptr;
    logic [BEAT_WIDTH-1:0] beat_idx;
    logic [COUNT_WIDTH-1:0] configured_col_count;
    logic [COUNT_WIDTH-1:0] configured_last_beat;
    logic [COUNT_WIDTH-1:0] last_beat_idx_q;
    logic [p_column_mask_width-1:0] configured_columns;
    logic [p_column_mask_width-1:0] valid_columns_q;
    logic stream_active;
    logic data_valid;
    logic ram_read_valid_q;
    logic [VLEN*16-1:0] ram_rd_data;
    (* keep = 1 *) logic [BUS_WIDTH-1:0] selected_read_data;
    (* keep = 1 *) logic [BUS_WIDTH/8-1:0] selected_read_mask;
    logic [MEM_ADDR_W-1:0] ram_wr_addr;
    logic [MEM_ADDR_W-1:0] ram_rd_addr;
    logic [PTR_WIDTH-1:0] next_read_row;
    logic write_bank_blocked_q, next_write_bank_blocked_q;
    logic partial_write_q;
    logic [BANK_WIDTH-1:0] candidate_write_bank [3];
    logic [2:0] candidate_blocked;
    logic [1:0] selected_blocked;
    logic [PTR_WIDTH-1:0] write_ptr_step;

    function automatic logic [BANK_WIDTH-1:0] next_bank(
        input logic [BANK_WIDTH-1:0] bank
    );
        if (bank == BANK_WIDTH'(BANKS - 1)) next_bank = '0;
        else next_bank = bank + 1'b1;
    endfunction

    wire write_bank_blocked = write_bank_blocked_q;
    wire next_write_bank_blocked = next_write_bank_blocked_q;
    wire finish_write_bank = in_valid && in_tile_done;
    wire [COUNT_WIDTH-1:0] write_rows_next =
        in_valid ? COUNT_WIDTH'(write_ptr + 1'b1) : COUNT_WIDTH'(write_ptr);
    wire read_bank_ready = bank_ready[read_bank] && (bank_count[read_bank] != '0);
    wire start_stream = !stream_active && read_bank_ready;
    // 接收列配置时保存各列有效位和末拍索引，输出阶段只选择当前拍。
    assign configured_col_count = COUNT_WIDTH'(vec_valid_num_col) + COUNT_WIDTH'(1);
    assign configured_last_beat = (configured_col_count == '0) ? '0 :
        ((configured_col_count - 1'b1) >> ELEMENT_SHIFT);
    for (genvar column = 0; column < p_column_mask_width; column++) begin : g_column_mask
        assign configured_columns[column] = column < int'(configured_col_count);
    end
    wire [COUNT_WIDTH-1:0] last_beat_idx_cur = last_beat_idx_q;
    wire output_fire = output_ready && output_valid;
    wire last_beat_in_row = output_fire &&
        (COUNT_WIDTH'(beat_idx) == last_beat_idx_cur);
    wire last_row_in_bank = last_beat_in_row &&
        ((COUNT_WIDTH'(read_ptr) + 1'b1) >= active_read_count_q);
    wire read_next_row = last_beat_in_row && !last_row_in_bank;
    wire ram_read_en = start_stream || read_next_row;

    assign output_valid = stream_active && data_valid;
    assign output_row_switch = last_beat_in_row;

    logic [31:0] watermark_i_reserve;
    logic [BANK_COUNT_WIDTH-1:0] watermark_i_ready_banks;
    logic watermark_i_partial_write, watermark_o_full;
    assign watermark_i_reserve = reserve_banks;
    assign watermark_i_ready_banks = ready_bank_count_q;
    assign watermark_i_partial_write = partial_write_q;
    assign fifo_full_flag = write_bank_blocked || next_write_bank_blocked || watermark_o_full;
    fifo_bank_watermark #(.p_banks(BANKS), .p_count_width(BANK_COUNT_WIDTH),
        .p_precomputed_threshold(p_precomputed_watermark)) u_watermark (
        .i_reserve(watermark_i_reserve), .i_ready_banks(watermark_i_ready_banks),
        .i_partial_write(watermark_i_partial_write),
        .i_ready_threshold(BANK_COUNT_WIDTH'(i_ready_bank_threshold)), .o_full(watermark_o_full)
    );
    if (p_precomputed_watermark) begin : g_issue_full
        fifo_s16_issue_full #(.p_count_width(BANK_COUNT_WIDTH)) u_full (
            .i_ready(ready_bank_count_q),
            .i_threshold(BANK_COUNT_WIDTH'(i_ready_bank_threshold)),
            .i_partial(partial_write_q), .i_write_blocked(write_bank_blocked_q),
            .i_next_blocked(next_write_bank_blocked_q), .i_selected(i_full_select),
            .i_output_pending(i_output_pending), .i_other_full(i_other_full),
            .o_full(o_issue_full)
        );
    end else begin : g_issue_reserve
        assign o_issue_full = (i_full_select ? fifo_full_flag : i_other_full) && i_output_pending;
    end

    always_comb begin
        next_read_row = start_stream ? '0 : (read_ptr + 1'b1);
        ram_wr_addr = MEM_ADDR_W'((int'(write_bank) * VLEN) + int'(write_ptr));
        ram_rd_addr = MEM_ADDR_W'((int'(read_bank) * VLEN) + int'(next_read_row));

        // 当前拍的数据和字节使能并行选择，输出资格在选择完成后合并。
        selected_read_data = ram_rd_data[int'(beat_idx)*BUS_WIDTH +: BUS_WIDTH];
        for (int lane = 0; lane < ELEMENTS_PER_BEAT; ++lane) begin
            selected_read_mask[lane*2+:2] =
                {2{valid_columns_q[int'(beat_idx)*ELEMENTS_PER_BEAT + lane]}};
        end
        output_data = '0;
        output_mask = '0;
        if (stream_active && data_valid) begin
            output_data = selected_read_data;
            output_mask = selected_read_mask;
        end
    end

    vec_s8_fifo_row_ram #(
        .DATA_WIDTH(VLEN * 16),
        .DEPTH(MEM_DEPTH),
        .ADDR_WIDTH(MEM_ADDR_W),
        .p_ram_style("block")
    ) u_ram (
        .clk(clk),
        .wr_en(in_valid && !write_bank_blocked),
        .wr_addr(ram_wr_addr),
        .wr_data(in_vec_s16),
        .rd_en(ram_read_en),
        .rd_addr(ram_rd_addr),
        .rd_data(ram_rd_data)
    );

    // 当前及后续两个写入银行并行计算下一状态，完成写入只选择需要保存的结果。
    // 同拍释放具有较高优先级，与银行有效位和行数的更新顺序一致。
    assign candidate_write_bank[0] = write_bank;
    assign candidate_write_bank[1] = next_bank(write_bank);
    assign candidate_write_bank[2] = next_bank(candidate_write_bank[1]);
    for (genvar candidate = 0; candidate < 3; candidate++) begin : g_write_blocked
        always_comb begin
            candidate_blocked[candidate] = bank_ready[candidate_write_bank[candidate]];
            if (last_row_in_bank && read_bank == candidate_write_bank[candidate]) begin
                candidate_blocked[candidate] = 1'b0;
            end else if (finish_write_bank && !write_bank_blocked &&
                         write_bank == candidate_write_bank[candidate]) begin
                candidate_blocked[candidate] = 1'b1;
            end
        end
    end
    always_comb begin
        selected_blocked = candidate_blocked[1:0];
        if (finish_write_bank && !write_bank_blocked) begin
            selected_blocked = candidate_blocked[2:1];
        end
    end
    assign write_ptr_step = write_ptr + 1'b1;
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            write_bank_blocked_q <= 1'b0;
            next_write_bank_blocked_q <= 1'b0;
            partial_write_q <= 1'b0;
        end else begin
            write_bank_blocked_q <= selected_blocked[0];
            next_write_bank_blocked_q <= selected_blocked[1];
            if (finish_write_bank && !write_bank_blocked) begin
                partial_write_q <= 1'b0;
            end else if (in_valid && !write_bank_blocked) begin
                partial_write_q <= write_ptr_step != '0;
            end
        end
    end

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            write_bank <= '0;
            read_bank <= '0;
            write_ptr <= '0;
            read_ptr <= '0;
            beat_idx <= '0;
            last_beat_idx_q <= '0;
            valid_columns_q <= {{(p_column_mask_width-1){1'b0}}, 1'b1};
            stream_active <= 1'b0;
            data_valid <= 1'b0;
            ram_read_valid_q <= 1'b0;
            oa_fifo_req <= 1'b0;
            bank_ready <= '0;
            ready_bank_count_q <= '0;
            active_read_count_q <= '0;
            for (int bank_idx = 0; bank_idx < BANKS; bank_idx++) begin
                bank_count[bank_idx] <= '0;
            end
        end else begin
            oa_fifo_req <= read_bank_ready && !stream_active;
            ram_read_valid_q <= ram_read_en;

            if (finish_write_bank && !write_bank_blocked) begin
                bank_count[write_bank] <= write_rows_next;
                bank_ready[write_bank] <= 1'b1;
                write_ptr <= '0;
                write_bank <= next_bank(write_bank);
                if (!last_row_in_bank) ready_bank_count_q <= ready_bank_count_q + 1'b1;

            end else if (in_valid && !write_bank_blocked) begin
                write_ptr <= write_ptr_step;
            end

            if (start_stream) begin
                stream_active <= 1'b1;
                data_valid <= 1'b0;
                read_ptr <= '0;
                beat_idx <= '0;
                active_read_count_q <= bank_count[read_bank];
                last_beat_idx_q <= configured_last_beat;
                valid_columns_q <= configured_columns;

            end else if (stream_active && !data_valid && ram_read_valid_q) begin
                data_valid <= 1'b1;
            end else if (stream_active && (read_ptr == '0) &&
                         (beat_idx == '0) && !output_ready) begin
                // 首拍等待期间继续接收该输出块的列配置，首拍接收后保持整行配置。
                last_beat_idx_q <= configured_last_beat;
                valid_columns_q <= configured_columns;
            end else if (output_fire) begin
                if (last_row_in_bank) begin
                    stream_active <= 1'b0;
                    data_valid <= 1'b0;
                    read_ptr <= '0;
                    beat_idx <= '0;
                    active_read_count_q <= '0;
                    bank_ready[read_bank] <= 1'b0;
                    bank_count[read_bank] <= '0;
                    read_bank <= next_bank(read_bank);
                    if (!(finish_write_bank && !write_bank_blocked)) begin
                        ready_bank_count_q <= ready_bank_count_q - 1'b1;
                    end
                end else if (last_beat_in_row) begin
                    beat_idx <= '0;
                    read_ptr <= read_ptr + 1'b1;
                end else begin
                    beat_idx <= beat_idx + 1'b1;
                end
            end
        end
    end

endmodule

`default_nettype wire
