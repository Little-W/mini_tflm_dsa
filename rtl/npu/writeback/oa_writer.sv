`default_nettype none

module oa_writer #(
    parameter int unsigned VLEN       = 16,
    parameter int unsigned DATA_WIDTH = 8,
    parameter int unsigned REG_WIDTH  = 32,
    parameter int unsigned BUS_WIDTH  = 32,
    parameter int unsigned COUNT_WIDTH = REG_WIDTH,
    parameter int unsigned ENABLE_IS_MODE = 1
) (
    input wire logic clk,
    input wire logic rst_n,

    input  wire logic init_cfg,
    output logic write_oa_req,
    input  wire logic write_oa_granted,

    input wire logic [REG_WIDTH-1:0] dst_base,
    input wire logic [REG_WIDTH-1:0] dst_row_stride_b,
    input wire logic [REG_WIDTH-1:0] k,
    input wire logic [REG_WIDTH-1:0] m,
    input wire logic [REG_WIDTH-1:0] ia_reuse_num,
    input wire logic                 is_mode,
    input wire logic                 output_16bits,
    input wire logic                 coalesce_enable,
    input wire logic [4:0]           coalesce_cols,
    output logic                coalesce_group_start,
    output logic [4:0]          coalesce_row_tiles,

    input  wire logic                    oa_fifo_req,
    output logic [$clog2(VLEN)-1:0] vec_valid_num_col,
    output logic [$clog2(VLEN)-1:0] vec_valid_num_row,

    input  wire logic                   output_valid,
    input  wire logic                   switch_row,
    output logic                   output_ready,
    input  wire logic [BUS_WIDTH/8-1:0] output_mask,
    input  wire logic [BUS_WIDTH-1:0]   output_data,

    output logic                        dma_start,
    output logic                        dma_is_write,
    output logic                        dma_linear_read_mode,
    output logic [REG_WIDTH-1:0]        dma_base_addr,
    output logic [REG_WIDTH-1:0]        dma_row_stride,
    output logic [REG_WIDTH-1:0]        dma_rows_to_read,
    output logic [7:0]                  dma_burst_len_m1,
    output logic                        dma_slot_id,
    output logic                        dma_use_16bits,
    output logic signed [REG_WIDTH-1:0] dma_lhs_zp,
    output logic [BUS_WIDTH-1:0]        dma_src_wdata,
    output logic [BUS_WIDTH/8-1:0]      dma_src_wmask,
    output logic                        dma_src_wvalid,
    input  wire logic                        dma_src_wready,
    input  wire logic                        dma_busy,
    input  wire logic                        dma_done,

    output logic write_done,
    output logic oa_calc_over
);

    localparam int unsigned BYTE_PER_BEAT = BUS_WIDTH / 8;
    localparam int unsigned VCOL_W = $clog2(VLEN);
    localparam int unsigned LOG2_BPB = $clog2(BYTE_PER_BEAT);
    localparam logic [VCOL_W:0] VLEN_COUNT = (VCOL_W + 1)'(VLEN);
    localparam int unsigned CNT_W = (COUNT_WIDTH < 1) ? 1 : COUNT_WIDTH;
    typedef logic [CNT_W-1:0] count_t;

    typedef enum logic [2:0] {
        S_IDLE,
        S_REQ,
        S_START,
        S_WRITE,
        S_DONE
    } state_t;

    (* fsm_encoding = "sequential" *) state_t state;

    logic [REG_WIDTH-1:0] cfg_dst_base;
    logic [REG_WIDTH-1:0] cfg_dst_row_stride_b;
    logic [REG_WIDTH-1:0] cfg_k;
    logic [REG_WIDTH-1:0] cfg_m;
    count_t               cfg_ia_reuse_num;
    logic                 cfg_has_tiles;
    logic                 cfg_is_mode;
    logic                 cfg_output_16bits;
    logic                 cfg_coalesce;
    logic [4:0]           cfg_coalesce_cols;
    logic                 cfg_lat_tick;
    count_t               row_tiles_total;
    count_t               col_tiles_total;
    count_t               row_tiles_last_idx;
    count_t               col_tiles_last_idx;
    logic [VCOL_W:0]      k_last_valid;
    logic [VCOL_W:0]      m_last_valid;

    count_t               tiles_done;
    count_t               tile_row_idx;
    count_t               tile_col_idx;
    count_t               row_group_base_idx;
    count_t               row_group_next_base_idx;
    logic [VCOL_W-1:0]    vec_valid_num_col_r;
    logic [VCOL_W-1:0]    vec_valid_num_row_r;
    logic [VCOL_W:0]      rows_valid_cur_tile;
    logic [VCOL_W:0]      cols_valid_cur_tile;
    logic [VCOL_W:0]      beats_per_row_cur_tile;
    logic [REG_WIDTH-1:0] tile_base_addr_cur;
    logic [REG_WIDTH-1:0] row_addr_step_cur;
    logic [REG_WIDTH-1:0] col_addr_step_cur;
    logic [REG_WIDTH-1:0] group_row_addr_step_cur;
    logic [REG_WIDTH-1:0] row_group_base_addr_cur;
    logic [REG_WIDTH-1:0] col_offset_addr_cur;
    logic [REG_WIDTH-1:0] row_offset_addr_cur;
    logic                 tile_row_is_last;
    logic                 tile_col_is_last;
    logic                 dma_done_q;
    logic [VCOL_W-1:0]    row_in_tile;
    logic [VCOL_W:0]      beats_in_row;
    logic [VCOL_W:0]      beats_per_row;
    logic                 has_grant;
    logic                 cmd_pending;
    logic                 cmd_inflight;
    logic                 rsp_inflight;
    logic                 tile_done_pending;
    logic                 writer_ready_cond;
    logic                 cmd_fire;
    logic                 beat_fire;
    logic                 rsp_fire;
    logic                 oa_calc_over_r;

    wire is_mode_eff = (ENABLE_IS_MODE != 0) ? is_mode : 1'b0;

    assign vec_valid_num_col = vec_valid_num_col_r;
    assign vec_valid_num_row = vec_valid_num_row_r;

    wire [REG_WIDTH-1:0] k_tiles_pre_w = (k == '0) ? '0 : ((k + REG_WIDTH'(VLEN - 1)) >> VCOL_W);
    wire [REG_WIDTH-1:0] m_tiles_pre_w = (m == '0) ? '0 : ((m + REG_WIDTH'(VLEN - 1)) >> VCOL_W);
    wire count_t k_tiles_pre = count_t'(k_tiles_pre_w);
    wire count_t m_tiles_pre = count_t'(m_tiles_pre_w);
    wire [VCOL_W-1:0]    k_tail_pre  = k[VCOL_W-1:0];
    wire [VCOL_W-1:0]    m_tail_pre  = m[VCOL_W-1:0];
    wire [VCOL_W:0]      k_last_valid_pre =
        (k == '0) ? '0 : ((k_tail_pre == '0) ? VLEN_COUNT : {1'b0, k_tail_pre});
    wire [VCOL_W:0]      m_last_valid_pre =
        (m == '0) ? '0 : ((m_tail_pre == '0) ? VLEN_COUNT : {1'b0, m_tail_pre});
    wire count_t row_tiles_total_pre = is_mode_eff ? m_tiles_pre : k_tiles_pre;
    wire count_t col_tiles_total_pre = is_mode_eff ? k_tiles_pre : m_tiles_pre;

    count_t tile_row_inc;
    count_t tile_col_inc;
    count_t reuse_group_base_cur;
    count_t reuse_group_next_base_cur;
    count_t next_tile_row_cur;
    count_t next_tile_col_cur;
    logic                 next_tile_row_is_last_cur;
    logic                 next_tile_col_is_last_cur;
    logic                 next_tile_wrap_cur;
    logic                 next_tile_row_advance_cur;
    logic                 next_tile_col_advance_cur;
    logic                 next_tile_group_advance_cur;
    count_t next_tile_row_r;
    count_t next_tile_col_r;
    logic                 next_tile_row_is_last_r;
    logic                 next_tile_col_is_last_r;
    logic                 next_tile_wrap_r;
    logic                 next_tile_row_advance_r;
    logic                 next_tile_col_advance_r;
    logic                 next_tile_group_advance_r;
    logic [VCOL_W-1:0]    vec_valid_num_col_next_r;
    logic [VCOL_W-1:0]    vec_valid_num_row_next_r;
    logic [VCOL_W:0]      rows_valid_calc;
    logic [VCOL_W:0]      cols_valid_calc;
    logic [VCOL_W:0]      k_last_index, m_last_index;
    logic [VCOL_W:0]      beats_per_row_calc;
    logic [VCOL_W:0]      vec_valid_num_col_next_w;
    logic [VCOL_W:0]      vec_valid_num_row_next_w;
    count_t               init_reuse_num_eff;
    logic [REG_WIDTH-1:0] init_tile_linear_step;
    logic [REG_WIDTH-1:0] init_tile_stride_step;
    logic [REG_WIDTH-1:0] init_row_addr_step;
    logic [REG_WIDTH-1:0] init_col_addr_step;
    logic [REG_WIDTH-1:0] init_group_row_addr_step;
    logic [REG_WIDTH-1:0] co_rows_limit;
    logic [REG_WIDTH-1:0] co_initial_limit;
    logic [REG_WIDTH-1:0] co_next_rows_remaining;
    logic [8:0] co_initial_rows;
    logic [8:0] co_current_rows;
    logic [8:0] co_next_rows_prepared;
    logic [8:0] co_initial_rows_calc;
    logic [8:0] co_next_rows_calc;
    logic [8:0] co_valid_rows;
    logic [4:0] co_initial_row_tiles_q, co_current_row_tiles_q;
    logic [4:0] co_next_row_tiles_q;
    logic [4:0] co_initial_row_tiles_calc, co_next_row_tiles_calc;
    logic [8:0] co_next_remaining_rows_low, co_limit_rows_low;
    logic [4:0] co_next_remaining_row_tiles, co_limit_row_tiles;
    logic co_has_next_col;
    logic co_has_next_group;
    logic co_advance_group;
    logic co_wrap_group;

    // 末尾索引先完成饱和减一，后续行列条件只选择已经准备的索引。
    assign k_last_index = (k_last_valid == '0) ? '0 : (k_last_valid - 1'b1);
    assign m_last_index = (m_last_valid == '0) ? '0 : (m_last_valid - 1'b1);

    always_comb begin
        init_reuse_num_eff = (ia_reuse_num == '0) ? count_t'(1) : count_t'(ia_reuse_num);
        init_tile_linear_step = REG_WIDTH'(VLEN) << (output_16bits ? 1 : 0);
        init_tile_stride_step = dst_row_stride_b << VCOL_W;
        init_row_addr_step = is_mode_eff ? init_tile_linear_step : init_tile_stride_step;
        init_col_addr_step = is_mode_eff ? init_tile_stride_step : init_tile_linear_step;
        unique case (init_reuse_num_eff)
            count_t'(1):  init_group_row_addr_step = init_row_addr_step;
            count_t'(2):  init_group_row_addr_step = init_row_addr_step << 1;
            count_t'(4):  init_group_row_addr_step = init_row_addr_step << 2;
            count_t'(8):  init_group_row_addr_step = init_row_addr_step << 3;
            count_t'(16): init_group_row_addr_step = init_row_addr_step << 4;
            count_t'(25): init_group_row_addr_step = (init_row_addr_step << 4) + (init_row_addr_step << 3) + init_row_addr_step;
            count_t'(32): init_group_row_addr_step = init_row_addr_step << 5;
            count_t'(64): init_group_row_addr_step = init_row_addr_step << 6;
            default:        init_group_row_addr_step = init_row_addr_step;
        endcase

        tile_row_inc = tile_row_idx +
                       ((cfg_coalesce && cfg_is_mode) ? cfg_ia_reuse_num : count_t'(1));
        tile_col_inc = tile_col_idx + count_t'(1);
        reuse_group_base_cur = row_group_base_idx;
        reuse_group_next_base_cur = row_group_next_base_idx;
        next_tile_row_is_last_cur = (row_tiles_last_idx == '0);
        next_tile_col_is_last_cur = (col_tiles_last_idx == '0);
        next_tile_wrap_cur = 1'b0;
        next_tile_row_advance_cur = 1'b0;
        next_tile_col_advance_cur = 1'b0;
        next_tile_group_advance_cur = 1'b0;

        if ((tile_row_inc < row_tiles_total) && (tile_row_inc < reuse_group_next_base_cur)) begin
            next_tile_row_cur = tile_row_inc;
            next_tile_col_cur = tile_col_idx;
            next_tile_row_is_last_cur = (tile_row_inc == row_tiles_last_idx);
            next_tile_col_is_last_cur = tile_col_is_last;
            next_tile_row_advance_cur = 1'b1;
        end else if (tile_col_inc < col_tiles_total) begin
            next_tile_row_cur = reuse_group_base_cur;
            next_tile_col_cur = tile_col_inc;
            next_tile_row_is_last_cur = (reuse_group_base_cur == row_tiles_last_idx);
            next_tile_col_is_last_cur = (tile_col_inc == col_tiles_last_idx);
            next_tile_col_advance_cur = 1'b1;
        end else if (reuse_group_next_base_cur < row_tiles_total) begin
            next_tile_row_cur = reuse_group_next_base_cur;
            next_tile_col_cur = '0;
            next_tile_row_is_last_cur = (reuse_group_next_base_cur == row_tiles_last_idx);
            next_tile_col_is_last_cur = (col_tiles_last_idx == '0);
            next_tile_group_advance_cur = 1'b1;
        end else begin
            next_tile_row_cur = '0;
            next_tile_col_cur = '0;
            next_tile_wrap_cur = 1'b1;
        end

        rows_valid_calc = cfg_is_mode
                        ? (tile_col_is_last ? k_last_valid : VLEN_COUNT)
                        : (tile_row_is_last ? k_last_valid : VLEN_COUNT);
        cols_valid_calc = cfg_is_mode
                        ? (tile_row_is_last ? m_last_valid : VLEN_COUNT)
                        : (tile_col_is_last ? m_last_valid : VLEN_COUNT);
        if (cfg_output_16bits) begin
            beats_per_row_calc = (cols_valid_calc + (VCOL_W + 1)'(BYTE_PER_BEAT/2 - 1)) >> (LOG2_BPB - 1);
        end else begin
            beats_per_row_calc = (cols_valid_calc + (VCOL_W + 1)'(BYTE_PER_BEAT - 1)) >> LOG2_BPB;
        end
        vec_valid_num_col_next_w = (cfg_is_mode ? next_tile_row_is_last_cur : next_tile_col_is_last_cur)
                                ? m_last_index : (VLEN_COUNT - 1'b1);
        vec_valid_num_row_next_w = (cfg_is_mode ? next_tile_col_is_last_cur : next_tile_row_is_last_cur)
                                ? k_last_index : (VLEN_COUNT - 1'b1);
    end

    assign write_oa_req = (state == S_REQ) || (state == S_START);
    assign writer_ready_cond = (state == S_WRITE) && dma_src_wready;
    assign output_ready = writer_ready_cond;
    assign dma_src_wvalid = (state == S_WRITE) && output_valid;
    assign dma_src_wdata = output_data;
    assign dma_src_wmask = output_mask;

    assign dma_start = (state == S_START) && write_oa_granted;
    assign dma_is_write = 1'b1;
    assign dma_linear_read_mode = 1'b0;
    assign dma_base_addr = tile_base_addr_cur;
    // 每个描述符覆盖当前 WS 组中已填充的行。
    logic [8:0] co_dma_rows;
    logic [REG_WIDTH-1:0] co_dma_stride;
    logic [7:0] co_dma_len;
    // 当前组行数随组起点更新；下一组的减法和范围比较在请求准备时完成。
    assign co_valid_rows = co_current_rows;
    assign co_rows_limit = REG_WIDTH'(cfg_ia_reuse_num) << VCOL_W;
    assign co_initial_limit = REG_WIDTH'(init_reuse_num_eff) << VCOL_W;
    assign co_initial_rows_calc = 9'((k < co_initial_limit) ? k : co_initial_limit);
    assign co_next_rows_remaining = cfg_k - (REG_WIDTH'(row_group_next_base_idx) << VCOL_W);
    assign co_next_rows_calc = 9'((co_next_rows_remaining < co_rows_limit) ?
        co_next_rows_remaining : co_rows_limit);
    // 行分块数量与行数同时准备，输出 FIFO 的启动判断直接使用寄存结果。
    assign co_initial_row_tiles_calc = co_initial_rows_calc[8:4] +
        {4'b0000, (|co_initial_rows_calc[3:0])};
    // 两种候选行数分别计算分块数量，完整范围比较只选择已经准备的结果。
    assign co_next_remaining_rows_low = 9'(co_next_rows_remaining);
    assign co_limit_rows_low = 9'(co_rows_limit);
    assign co_next_remaining_row_tiles = co_next_remaining_rows_low[8:4] +
        {4'b0000, (|co_next_remaining_rows_low[3:0])};
    assign co_limit_row_tiles = co_limit_rows_low[8:4] +
        {4'b0000, (|co_limit_rows_low[3:0])};
    assign co_next_row_tiles_calc = (co_next_rows_remaining < co_rows_limit) ?
        co_next_remaining_row_tiles : co_limit_row_tiles;
    assign co_advance_group = (state == S_WRITE) && write_done &&
        ((cfg_coalesce && !cfg_is_mode) ? (!co_has_next_col && co_has_next_group) :
        (!next_tile_wrap_r && !next_tile_row_advance_r &&
         !next_tile_col_advance_r && next_tile_group_advance_r));
    assign co_wrap_group = (state == S_WRITE) && write_done &&
        !(cfg_coalesce && !cfg_is_mode) && next_tile_wrap_r;
    wire [REG_WIDTH-1:0] co_chunk_bytes = REG_WIDTH'(cfg_coalesce_cols) << 4;
    logic [16:0] co_group_bytes;
    always_comb begin
        case (cfg_coalesce_cols)
            5'd16: co_group_bytes = 17'(co_valid_rows) << 8;
            5'd8:  co_group_bytes = 17'(co_valid_rows) << 7;
            5'd4:  co_group_bytes = 17'(co_valid_rows) << 6;
            5'd2:  co_group_bytes = 17'(co_valid_rows) << 5;
            default: co_group_bytes = 17'(co_valid_rows) << 4;
        endcase
    end
    // 描述符发出前保存后续组的范围信息，DMA 完成时只选择已准备的结果。
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            co_initial_rows <= '0;
            co_current_rows <= '0;
            co_next_rows_prepared <= '0;
            co_initial_row_tiles_q <= '0;
            co_current_row_tiles_q <= '0;
            co_next_row_tiles_q <= '0;
            co_has_next_col <= 1'b0;
            co_has_next_group <= 1'b0;
        end else if (init_cfg) begin
            co_initial_rows <= co_initial_rows_calc;
            co_current_rows <= co_initial_rows_calc;
            co_next_rows_prepared <= '0;
            co_initial_row_tiles_q <= co_initial_row_tiles_calc;
            co_current_row_tiles_q <= co_initial_row_tiles_calc;
            co_next_row_tiles_q <= '0;
            co_has_next_col <= 1'b0;
            co_has_next_group <= 1'b0;
        end else begin
            if ((state == S_REQ) && write_oa_granted) begin
                co_next_rows_prepared <= co_next_rows_calc;
                co_next_row_tiles_q <= co_next_row_tiles_calc;
                co_has_next_col <= (col_offset_addr_cur + co_chunk_bytes) < cfg_m;
                co_has_next_group <= row_group_next_base_idx < row_tiles_total;
            end
            if (co_advance_group) begin
                co_current_rows <= co_next_rows_prepared;
                co_current_row_tiles_q <= co_next_row_tiles_q;
            end else if (co_wrap_group) begin
                co_current_rows <= co_initial_rows;
                co_current_row_tiles_q <= co_initial_row_tiles_q;
            end
        end
    end
    assign coalesce_row_tiles = cfg_is_mode ? 5'd1 :
        co_current_row_tiles_q;
    assign coalesce_group_start = dma_start && cfg_coalesce && !cfg_is_mode;
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            co_dma_rows <= 0; co_dma_stride <= 0; co_dma_len <= 0;
        end else if (cfg_lat_tick || (state == S_REQ && write_oa_granted)) begin
            if (cfg_is_mode) begin
                co_dma_rows <= 0;
                co_dma_stride <= 0;
                co_dma_len <= 8'(REG_WIDTH'(cfg_coalesce_cols) * 16 / BYTE_PER_BEAT) - 1'b1;
            end else if (BUS_WIDTH == 64 && cfg_m == co_chunk_bytes && co_group_bytes[10:0] == 0) begin
                co_dma_rows <= 9'(co_group_bytes >> 11);
                co_dma_stride <= REG_WIDTH'(2048);
                co_dma_len <= 8'd255;
            end else if (cfg_m == co_chunk_bytes && co_group_bytes[9:0] == 0) begin
                co_dma_rows <= 9'(co_group_bytes >> 10);
                co_dma_stride <= REG_WIDTH'(1024);
                co_dma_len <= 8'(1024 / BYTE_PER_BEAT - 1);
            end else if (cfg_m == co_chunk_bytes && co_group_bytes[8:0] == 0) begin
                co_dma_rows <= 9'(co_group_bytes >> 9);
                co_dma_stride <= REG_WIDTH'(512);
                co_dma_len <= 8'(512 / BYTE_PER_BEAT - 1);
            end else if (cfg_m == co_chunk_bytes && co_group_bytes[7:0] == 0) begin
                co_dma_rows <= 9'(co_group_bytes >> 8);
                co_dma_stride <= REG_WIDTH'(256);
                co_dma_len <= 8'(256 / BYTE_PER_BEAT - 1);
            end else begin
                co_dma_rows <= co_valid_rows;
                co_dma_stride <= cfg_dst_row_stride_b;
                co_dma_len <= 8'(REG_WIDTH'(cfg_coalesce_cols) * 16 / BYTE_PER_BEAT) - 1'b1;
            end
        end
    end
    assign dma_row_stride = (cfg_coalesce && !cfg_is_mode) ? REG_WIDTH'(co_dma_stride)
                                                        : cfg_dst_row_stride_b;
    assign dma_rows_to_read = (cfg_coalesce && !cfg_is_mode) ? REG_WIDTH'(co_dma_rows)
                                                           : REG_WIDTH'(rows_valid_cur_tile);
    assign dma_burst_len_m1 = cfg_coalesce ? co_dma_len
        : ((beats_per_row_cur_tile == '0) ? 8'd0 : 8'(beats_per_row_cur_tile - 1'b1));
    assign dma_slot_id = 1'b0;
    assign dma_use_16bits = cfg_output_16bits;
    assign dma_lhs_zp = '0;

    assign write_done = (state == S_WRITE) && dma_done && !dma_done_q;
    assign oa_calc_over = oa_calc_over_r;
    assign beat_fire = output_valid && output_ready;
    assign cmd_fire = dma_start;
    assign rsp_fire = write_done;
    assign has_grant = write_oa_granted;
    assign cmd_pending = (state == S_REQ) || (state == S_START);
    assign cmd_inflight = dma_busy;
    assign rsp_inflight = (state == S_WRITE) && dma_busy;
    assign tile_done_pending = write_done;
    assign beats_per_row = beats_per_row_cur_tile;

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            cfg_dst_base <= '0;
            cfg_dst_row_stride_b <= '0;
            cfg_k <= '0;
            cfg_m <= '0;
            cfg_ia_reuse_num <= count_t'(1);
            cfg_has_tiles <= 1'b0;
            cfg_is_mode <= 1'b0;
            cfg_output_16bits <= 1'b0;
            cfg_coalesce <= 1'b0;
            cfg_coalesce_cols <= 1;
            cfg_lat_tick <= 1'b0;
            row_tiles_total <= '0;
            col_tiles_total <= '0;
            row_tiles_last_idx <= '0;
            col_tiles_last_idx <= '0;
            k_last_valid <= '0;
            m_last_valid <= '0;
        end else if (init_cfg) begin
            cfg_dst_base <= dst_base;
            cfg_dst_row_stride_b <= dst_row_stride_b;
            cfg_k <= k;
            cfg_m <= m;
            cfg_ia_reuse_num <= (ia_reuse_num == '0) ? count_t'(1) : count_t'(ia_reuse_num);
            cfg_has_tiles <= (k != '0) && (m != '0);
            cfg_is_mode <= is_mode_eff;
            cfg_output_16bits <= output_16bits;
            cfg_coalesce <= coalesce_enable;
            cfg_coalesce_cols <= coalesce_cols;
            cfg_lat_tick <= 1'b1;
            row_tiles_total <= row_tiles_total_pre;
            col_tiles_total <= col_tiles_total_pre;
            row_tiles_last_idx <= '0;
            col_tiles_last_idx <= '0;
            k_last_valid <= k_last_valid_pre;
            m_last_valid <= m_last_valid_pre;
        end else if (cfg_lat_tick) begin
            cfg_lat_tick <= 1'b0;
            row_tiles_last_idx <= (row_tiles_total == '0) ? '0 : (row_tiles_total - count_t'(1));
            col_tiles_last_idx <= (col_tiles_total == '0) ? '0 : (col_tiles_total - count_t'(1));
        end else begin
            cfg_lat_tick <= 1'b0;
        end
    end

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            state <= S_IDLE;
            tiles_done <= '0;
            tile_row_idx <= '0;
            tile_col_idx <= '0;
            row_group_base_idx <= '0;
                row_group_next_base_idx <= count_t'(1);
            vec_valid_num_col_r <= '0;
            vec_valid_num_row_r <= '0;
            rows_valid_cur_tile <= '0;
            cols_valid_cur_tile <= '0;
            beats_per_row_cur_tile <= '0;
            tile_base_addr_cur <= '0;
            row_addr_step_cur <= '0;
            col_addr_step_cur <= '0;
            group_row_addr_step_cur <= '0;
            row_group_base_addr_cur <= '0;
            col_offset_addr_cur <= '0;
            row_offset_addr_cur <= '0;
            tile_row_is_last <= 1'b1;
            tile_col_is_last <= 1'b1;
            next_tile_row_r <= '0;
            next_tile_col_r <= '0;
            next_tile_row_is_last_r <= 1'b1;
            next_tile_col_is_last_r <= 1'b1;
            next_tile_wrap_r <= 1'b1;
            next_tile_row_advance_r <= 1'b0;
            next_tile_col_advance_r <= 1'b0;
            next_tile_group_advance_r <= 1'b0;
            vec_valid_num_col_next_r <= '0;
            vec_valid_num_row_next_r <= '0;
            dma_done_q <= 1'b0;
            row_in_tile <= '0;
            beats_in_row <= '0;
            oa_calc_over_r <= 1'b0;
        end else begin
            dma_done_q <= dma_done;
            oa_calc_over_r <= 1'b0;

            if (init_cfg) begin
                state <= S_IDLE;
                tiles_done <= '0;
                tile_row_idx <= '0;
                tile_col_idx <= '0;
                row_group_base_idx <= '0;
                row_group_next_base_idx <= init_reuse_num_eff;
                vec_valid_num_col_r <= '0;
                vec_valid_num_row_r <= '0;
                rows_valid_cur_tile <= '0;
                cols_valid_cur_tile <= '0;
                beats_per_row_cur_tile <= '0;
                tile_base_addr_cur <= dst_base;
                row_addr_step_cur <= init_row_addr_step;
                col_addr_step_cur <= init_col_addr_step;
                group_row_addr_step_cur <= init_group_row_addr_step;
                row_group_base_addr_cur <= dst_base;
                col_offset_addr_cur <= '0;
                row_offset_addr_cur <= '0;
                tile_row_is_last <= (row_tiles_total_pre <= count_t'(1));
                tile_col_is_last <= (col_tiles_total_pre <= count_t'(1));
                next_tile_row_r <= '0;
                next_tile_col_r <= '0;
                next_tile_row_is_last_r <= 1'b1;
                next_tile_col_is_last_r <= 1'b1;
                next_tile_wrap_r <= 1'b1;
                next_tile_row_advance_r <= 1'b0;
                next_tile_col_advance_r <= 1'b0;
                next_tile_group_advance_r <= 1'b0;
                vec_valid_num_col_next_r <= '0;
                vec_valid_num_row_next_r <= '0;
                row_in_tile <= '0;
                beats_in_row <= '0;
                oa_calc_over_r <= 1'b0;
            end else begin
                case (state)
                    S_IDLE: begin
                        if (cfg_lat_tick) begin
                            vec_valid_num_col_r <= (cols_valid_calc == '0) ? '0 : VCOL_W'(cols_valid_calc - 1'b1);
                            vec_valid_num_row_r <= (rows_valid_calc == '0) ? '0 : VCOL_W'(rows_valid_calc - 1'b1);
                        end
                        if (cfg_has_tiles && (oa_fifo_req || output_valid)) begin
                            state <= S_REQ;
                        end
                    end

                    S_REQ: begin
                        if (write_oa_granted) begin
                            rows_valid_cur_tile <= rows_valid_calc;
                            cols_valid_cur_tile <= cols_valid_calc;
                            beats_per_row_cur_tile <= beats_per_row_calc;
                            next_tile_row_r <= next_tile_row_cur;
                            next_tile_col_r <= next_tile_col_cur;
                            next_tile_row_is_last_r <= next_tile_row_is_last_cur;
                            next_tile_col_is_last_r <= next_tile_col_is_last_cur;
                            next_tile_wrap_r <= next_tile_wrap_cur;
                            next_tile_row_advance_r <= next_tile_row_advance_cur;
                            next_tile_col_advance_r <= next_tile_col_advance_cur;
                            next_tile_group_advance_r <= next_tile_group_advance_cur;
                            vec_valid_num_col_next_r <= vec_valid_num_col_next_w[VCOL_W-1:0];
                            vec_valid_num_row_next_r <= vec_valid_num_row_next_w[VCOL_W-1:0];
                            row_in_tile <= '0;
                            beats_in_row <= '0;

                            state <= S_START;
                        end
                    end

                    S_START: begin
                        if (dma_start) begin

                            state <= S_WRITE;
                        end
                    end

                    S_WRITE: begin
                        if (beat_fire) begin

                            if ((beats_in_row + 1'b1) >= beats_per_row_cur_tile) begin
                                beats_in_row <= '0;
                                if (((VCOL_W + 1)'(row_in_tile) + (VCOL_W + 1)'(1)) < rows_valid_cur_tile) begin
                                    row_in_tile <= row_in_tile + 1'b1;
                                end
                            end else begin
                                beats_in_row <= beats_in_row + 1'b1;
                            end
                        end
                        if (write_done) begin
                            tiles_done <= tiles_done + 1'b1;

                            if (cfg_coalesce && !cfg_is_mode) begin
                                if (co_has_next_col) begin
                                    col_offset_addr_cur <= col_offset_addr_cur + co_chunk_bytes;
                                    tile_base_addr_cur <= tile_base_addr_cur + co_chunk_bytes;
                                    state <= S_IDLE;
                                end else if (!co_has_next_group) begin
                                    oa_calc_over_r <= 1'b1;
                                    state <= S_DONE;
                                end else begin
                                    row_group_base_idx <= row_group_next_base_idx;
                                    row_group_next_base_idx <= row_group_next_base_idx + cfg_ia_reuse_num;
                                    col_offset_addr_cur <= 0;
                                    row_group_base_addr_cur <= row_group_base_addr_cur + group_row_addr_step_cur;
                                    tile_base_addr_cur <= row_group_base_addr_cur + group_row_addr_step_cur;
                                    state <= S_IDLE;
                                end
                            end else if (next_tile_wrap_r) begin
                                oa_calc_over_r <= 1'b1;
                                state <= S_DONE;
                                tile_row_idx <= '0;
                                tile_col_idx <= '0;
                                row_group_base_idx <= '0;
                                row_group_next_base_idx <= cfg_ia_reuse_num;
                                tile_base_addr_cur <= cfg_dst_base;
                                row_group_base_addr_cur <= cfg_dst_base;
                                col_offset_addr_cur <= '0;
                                row_offset_addr_cur <= '0;
                                tile_row_is_last <= (row_tiles_last_idx == '0);
                                tile_col_is_last <= (col_tiles_last_idx == '0);

                            end else begin
                                tile_row_idx <= next_tile_row_r;
                                tile_col_idx <= next_tile_col_r;
                                tile_row_is_last <= next_tile_row_is_last_r;
                                tile_col_is_last <= next_tile_col_is_last_r;
                                vec_valid_num_col_r <= vec_valid_num_col_next_r;
                                vec_valid_num_row_r <= vec_valid_num_row_next_r;
                                if (next_tile_row_advance_r) begin
                                    row_offset_addr_cur <= row_offset_addr_cur + row_addr_step_cur;
                                    tile_base_addr_cur <= tile_base_addr_cur + row_addr_step_cur;
                                end else if (next_tile_col_advance_r) begin
                                    col_offset_addr_cur <= col_offset_addr_cur + col_addr_step_cur;
                                    row_offset_addr_cur <= '0;
                                    tile_base_addr_cur <= row_group_base_addr_cur +
                                                          col_offset_addr_cur +
                                                          col_addr_step_cur;
                                end else if (next_tile_group_advance_r) begin
                                    row_group_base_idx <= row_group_next_base_idx;
                                    row_group_next_base_idx <= row_group_next_base_idx +
                                                               cfg_ia_reuse_num;
                                    row_group_base_addr_cur <= row_group_base_addr_cur +
                                                               group_row_addr_step_cur;
                                    col_offset_addr_cur <= '0;
                                    row_offset_addr_cur <= '0;
                                    tile_base_addr_cur <= row_group_base_addr_cur +
                                                          group_row_addr_step_cur;
                                end
                                state <= S_IDLE;

                            end
                        end
                    end

                    S_DONE: begin
                        state <= S_DONE;
                    end

                    default: state <= S_IDLE;
                endcase
            end
        end
    end

endmodule

`default_nettype wire
