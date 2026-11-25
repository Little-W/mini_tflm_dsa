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
    localparam int unsigned ADDR_LOW_W = (REG_WIDTH < 8) ? REG_WIDTH : 8;
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
    logic [VCOL_W:0]      beats_per_row_cur_tile;
    logic [REG_WIDTH-1:0] tile_base_addr_cur;
    logic [REG_WIDTH-1:0] row_addr_step_cur;
    logic [REG_WIDTH-1:0] col_addr_step_cur;
    logic [REG_WIDTH-1:0] group_row_addr_step_cur;
    logic [REG_WIDTH-1:0] row_group_base_addr_cur;
    logic [REG_WIDTH-1:0] col_offset_addr_cur;
    logic [REG_WIDTH-1:0] row_offset_addr_cur;
    logic [REG_WIDTH-1:0] column_base_addr;
    logic [REG_WIDTH-1:0] address_base, address_step;
    logic [REG_WIDTH-1:0] next_address_base, next_address_step;
    logic [REG_WIDTH-1:0] next_address;
    logic [ADDR_LOW_W-1:0] next_address_low;
    logic next_address_carry;
    logic unused_next_address_carry;
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

    logic [1:0] initial_axis_is_last;
    logic [REG_WIDTH-1:0] k_tiles_pre_w, m_tiles_pre_w;
    if ((VLEN == (1 << VCOL_W)) && (REG_WIDTH > VCOL_W) && (VCOL_W > 0)) begin : g_rounded_tile_counts
        localparam int p_quotient_width = REG_WIDTH - VCOL_W;
        logic [REG_WIDTH-1:0] dimensions [2];
        logic [p_quotient_width-1:0] rounded [2];

        assign dimensions[0] = k;
        assign dimensions[1] = m;
        // 低位非零时递增商，各八位分组直接读取原商的传播条件。
        for (genvar axis = 0; axis < 2; axis++) begin : g_axis
            logic [p_quotient_width-1:0] quotient;
            logic round_up;
            localparam int p_effective_width = (CNT_W < p_quotient_width) ? CNT_W : p_quotient_width;
            logic initial_is_last_binary;
            if (p_effective_width == 1) begin : g_single_count_bit
                assign initial_is_last_binary = 1'b1;
            end else begin : g_multiple_count_bits
                // 有限位宽商取0或1，以及向上取整后的模回绕，都属于首块末尾。
                assign initial_is_last_binary =
                    ((quotient[p_effective_width-1:1] == '0) && (!round_up || !quotient[0])) ||
                    ((&quotient[p_effective_width-1:0]) && round_up);
            end
            always_comb begin
                initial_axis_is_last[axis] = initial_is_last_binary;
`ifndef SYNTHESIS
                if ((^dimensions[axis]) === 1'bx) begin
                    initial_axis_is_last[axis] = count_t'(REG_WIDTH'(rounded[axis])) <= count_t'(1);
                end
`endif
            end

            assign quotient = dimensions[axis][REG_WIDTH-1:VCOL_W];
            assign round_up = |dimensions[axis][VCOL_W-1:0];
            for (genvar group = 0; group < (p_quotient_width+7)/8; group++) begin : g_group
                localparam int p_first = 8 * group;
                localparam int p_bits = (p_quotient_width-p_first < 8) ? p_quotient_width-p_first : 8;
                logic carry;

                if (group == 0) begin : g_first
                    assign carry = round_up;
                end else begin : g_upper
                    assign carry = round_up && (&quotient[p_first-1:0]);
                end
                assign rounded[axis][p_first +: p_bits] =
                    quotient[p_first +: p_bits] + p_bits'(carry);
            end
        end
        assign k_tiles_pre_w = REG_WIDTH'(rounded[0]);
        assign m_tiles_pre_w = REG_WIDTH'(rounded[1]);
    end else begin : g_general_tile_counts
        assign k_tiles_pre_w = (k == '0) ? '0 : ((k + REG_WIDTH'(VLEN - 1)) >> VCOL_W);
        assign m_tiles_pre_w = (m == '0) ? '0 : ((m + REG_WIDTH'(VLEN - 1)) >> VCOL_W);
        assign initial_axis_is_last[0] = count_t'(k_tiles_pre_w) <= count_t'(1);
        assign initial_axis_is_last[1] = count_t'(m_tiles_pre_w) <= count_t'(1);
    end
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
    // 首块末尾资格分别读取两个维度，模式仅选择一位判断结果。
    (* keep = "true" *) logic k_initial_is_last_pre, m_initial_is_last_pre;
    logic row_initial_is_last_pre, col_initial_is_last_pre;
    assign k_initial_is_last_pre = initial_axis_is_last[0];
    assign m_initial_is_last_pre = initial_axis_is_last[1];
    always_comb begin
        row_initial_is_last_pre = is_mode_eff ? m_initial_is_last_pre : k_initial_is_last_pre;
        col_initial_is_last_pre = is_mode_eff ? k_initial_is_last_pre : m_initial_is_last_pre;
`ifndef SYNTHESIS
        if ((^is_mode_eff) === 1'bx) begin
            row_initial_is_last_pre = row_tiles_total_pre <= count_t'(1);
            col_initial_is_last_pre = col_tiles_total_pre <= count_t'(1);
        end
`endif
    end

    count_t tile_row_inc;
    count_t tile_col_inc;
    count_t row_group_next_sum;
    count_t tile_row_inc_q, tile_col_inc_q;
    logic [CNT_W:0] row_total_difference, row_group_difference;
    logic [CNT_W:0] column_total_difference, group_total_difference;
    logic row_inc_in_range_q, col_inc_in_range_q, group_inc_in_range_q;
    logic row_inc_is_last_q, col_inc_is_last_q;
    logic group_base_is_last_q, group_next_is_last_q;
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
    logic [REG_WIDTH-1:0] init_group_step_25;
    logic [6:0] init_group_factor;
    (* use_dsp = "yes" *) logic [REG_WIDTH-1:0] init_group_product;
    logic [REG_WIDTH-1:0] row_offset_next, col_offset_next;
    logic [REG_WIDTH-1:0] co_next_col_offset;
    logic [2:0] init_group_shift;
    logic init_group_by_25;
    logic [1:0] unused_co_compare_equal;
    logic co_initial_is_short, co_next_is_short;
    count_t row_tiles_decrement, col_tiles_decrement;
    logic co_contiguous_q;
    logic [2:0] co_row_div_shift_q;
    logic [8:0] co_rows_per_256;
    logic [7:0] co_row_low_zero;
    logic [3:0] co_segment_aligned;
    logic [REG_WIDTH-1:0] co_rows_limit;
    logic [REG_WIDTH-1:0] co_initial_limit;
    logic [REG_WIDTH-1:0] co_next_rows_remaining;
    logic [REG_WIDTH-1:0] co_next_rows_remaining_q, co_next_col_offset_q;
    logic [REG_WIDTH-1:0] co_chunk_bytes;
    logic [8:0] co_initial_rows;
    logic [8:0] co_current_rows;
    logic [8:0] co_next_rows_prepared;
    logic [8:0] co_initial_rows_calc;
    logic [8:0] co_next_rows_calc;
    logic [8:0] co_valid_rows;
    logic [4:0] co_initial_row_tiles_q, co_current_row_tiles_q;
    logic [4:0] co_next_row_tiles_q;
    logic [4:0] co_initial_row_tiles_calc, co_next_row_tiles_calc;
    logic [8:0] co_initial_k_rows_low, co_initial_limit_rows_low;
    logic [4:0] co_initial_k_row_tiles, co_initial_limit_row_tiles;
    logic [8:0] co_next_remaining_rows_low, co_limit_rows_low;
    logic [4:0] co_next_remaining_row_tiles, co_limit_row_tiles;
    logic co_has_next_col;
    logic co_has_next_group;
    logic co_advance_group;
    logic co_wrap_group;

    // 步长与地址推进独立计算，状态机只在原有更新周期选择结果。
    assign init_group_step_25 = row_addr_step_cur * 5'd25;
    // 复用数量先译为有限位宽系数，组步长由完整定宽乘法计算。
    always_comb begin
        case (cfg_ia_reuse_num)
            count_t'(2):  init_group_factor = 7'd2;
            count_t'(4):  init_group_factor = 7'd4;
            count_t'(8):  init_group_factor = 7'd8;
            count_t'(16): init_group_factor = 7'd16;
            count_t'(25): init_group_factor = 7'd25;
            count_t'(32): init_group_factor = 7'd32;
            count_t'(64): init_group_factor = 7'd64;
            default:     init_group_factor = 7'd1;
        endcase
    end
    assign init_group_product = row_addr_step_cur * init_group_factor;
    assign row_group_next_sum = row_group_next_base_idx + cfg_ia_reuse_num;
    assign row_offset_next = row_offset_addr_cur + row_addr_step_cur;
    assign col_offset_next = col_offset_addr_cur + col_addr_step_cur;
    assign co_next_col_offset = col_offset_addr_cur + co_chunk_bytes;

    // 末尾索引先完成饱和减一，后续行列条件只选择已经准备的索引。
    assign k_last_index = (k_last_valid == '0) ? '0 : (k_last_valid - 1'b1);
    assign m_last_index = (m_last_valid == '0) ? '0 : (m_last_valid - 1'b1);

`ifdef SYNTHESIS
    count_t tile_row_selected_step;
    count_t tile_row_next;

    assign tile_row_selected_step = (cfg_coalesce && cfg_is_mode) ?
        cfg_ia_reuse_num : count_t'(1);
    if (CNT_W > 16) begin : g_row_carry_select
        logic unused_carry;
        // 高段两种和值并行计算，低段进位只选择结果，计数器仍在原有边沿更新。
        parallel_prefix_add #(
            .p_width(CNT_W),
            .p_group_width(8),
            .p_carry_select_width(16)
        ) u_row_add (
            .i_a(tile_row_idx),
            .i_b(tile_row_selected_step),
            .i_carry(1'b0),
            .o_sum(tile_row_next),
            .o_carry(unused_carry)
        );
    end else begin : g_row_short_add
        assign tile_row_next = tile_row_idx + tile_row_selected_step;
    end
`endif

    always_comb begin
        init_reuse_num_eff = (ia_reuse_num == '0) ? count_t'(1) : count_t'(ia_reuse_num);
        init_tile_linear_step = REG_WIDTH'(VLEN) << (output_16bits ? 1 : 0);
        init_tile_stride_step = dst_row_stride_b << VCOL_W;
        init_row_addr_step = is_mode_eff ? init_tile_linear_step : init_tile_stride_step;
        init_col_addr_step = is_mode_eff ? init_tile_stride_step : init_tile_linear_step;
        init_group_shift = '0;
        init_group_by_25 = 1'b0;
        if (CNT_W >= 7) begin
            // 移位候选保留部分未知数据的逐位传播语义。
            case (cfg_ia_reuse_num)
                count_t'(2):  init_group_shift = 3'd1;
                count_t'(4):  init_group_shift = 3'd2;
                count_t'(8):  init_group_shift = 3'd3;
                count_t'(16): init_group_shift = 3'd4;
                count_t'(25): init_group_by_25 = 1'b1;
                count_t'(32): init_group_shift = 3'd5;
                count_t'(64): init_group_shift = 3'd6;
                default: begin end
            endcase
            init_group_row_addr_step = init_group_by_25 ?
                init_group_step_25 :
                row_addr_step_cur << init_group_shift;
        end else begin
            unique case (cfg_ia_reuse_num)
                count_t'(1):  init_group_row_addr_step = row_addr_step_cur;
                count_t'(2):  init_group_row_addr_step = row_addr_step_cur << 1;
                count_t'(4):  init_group_row_addr_step = row_addr_step_cur << 2;
                count_t'(8):  init_group_row_addr_step = row_addr_step_cur << 3;
                count_t'(16): init_group_row_addr_step = row_addr_step_cur << 4;
                count_t'(25): init_group_row_addr_step = init_group_step_25;
                count_t'(32): init_group_row_addr_step = row_addr_step_cur << 5;
                count_t'(64): init_group_row_addr_step = row_addr_step_cur << 6;
                default: init_group_row_addr_step = row_addr_step_cur;
            endcase
        end

        if (CNT_W >= 7 && REG_WIDTH >= 7) begin
            case (^row_addr_step_cur)
                1'b0, 1'b1: init_group_row_addr_step = init_group_product;
                default: begin end
            endcase
        end

`ifdef SYNTHESIS
        tile_row_inc = tile_row_next;
`else
        tile_row_inc = tile_row_idx +
                       ((cfg_coalesce && cfg_is_mode) ? cfg_ia_reuse_num : count_t'(1));
`endif
        tile_col_inc = tile_col_idx + count_t'(1);
        reuse_group_base_cur = row_group_base_idx;
        reuse_group_next_base_cur = row_group_next_base_idx;
        next_tile_row_is_last_cur = (row_tiles_last_idx == '0);
        next_tile_col_is_last_cur = (col_tiles_last_idx == '0);
        next_tile_wrap_cur = 1'b0;
        next_tile_row_advance_cur = 1'b0;
        next_tile_col_advance_cur = 1'b0;
        next_tile_group_advance_cur = 1'b0;

        if (row_inc_in_range_q) begin
            next_tile_row_cur = tile_row_inc_q;
            next_tile_col_cur = tile_col_idx;
            next_tile_row_is_last_cur = row_inc_is_last_q;
            next_tile_col_is_last_cur = tile_col_is_last;
            next_tile_row_advance_cur = 1'b1;
        end else if (col_inc_in_range_q) begin
            next_tile_row_cur = reuse_group_base_cur;
            next_tile_col_cur = tile_col_inc_q;
            next_tile_row_is_last_cur = group_base_is_last_q;
            next_tile_col_is_last_cur = col_inc_is_last_q;
            next_tile_col_advance_cur = 1'b1;
        end else if (group_inc_in_range_q) begin
            next_tile_row_cur = reuse_group_next_base_cur;
            next_tile_col_cur = '0;
            next_tile_row_is_last_cur = group_next_is_last_q;
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

    assign row_total_difference = {1'b0, tile_row_inc_q} - {1'b0, row_tiles_total};
    assign row_group_difference = {1'b0, tile_row_inc_q} - {1'b0, row_group_next_base_idx};
    assign column_total_difference = {1'b0, tile_col_inc_q} - {1'b0, col_tiles_total};
    assign group_total_difference = {1'b0, row_group_next_base_idx} - {1'b0, row_tiles_total};

    // 行列索引在请求准备期间保持，递增与范围判断分别使用已有周期。
    // S_START 才保存下一块控制，S_WRITE 的完成事件随后消费这些结果。
    always_ff @(posedge clk) begin
        tile_row_inc_q <= tile_row_inc;
        tile_col_inc_q <= tile_col_inc;
        row_inc_in_range_q <= row_total_difference[CNT_W] && row_group_difference[CNT_W];
        col_inc_in_range_q <= column_total_difference[CNT_W];
        group_inc_in_range_q <= group_total_difference[CNT_W];
        row_inc_is_last_q <= tile_row_inc_q == row_tiles_last_idx;
        col_inc_is_last_q <= tile_col_inc_q == col_tiles_last_idx;
        group_base_is_last_q <= row_group_base_idx == row_tiles_last_idx;
        group_next_is_last_q <= row_group_next_base_idx == row_tiles_last_idx;
        co_next_rows_remaining_q <= co_next_rows_remaining;
        co_next_col_offset_q <= co_next_col_offset;
    end

    // 当前列首地址随列和组推进保存，后续地址只需要一次完整加法。
    // 请求准备期间选择互斥分支，S_WRITE 消费已经稳定的结果。
    always_comb begin
        if (cfg_coalesce && !cfg_is_mode) begin
            address_base = co_has_next_col ? tile_base_addr_cur : row_group_base_addr_cur;
            address_step = co_has_next_col ? co_chunk_bytes : group_row_addr_step_cur;
        end else if (next_tile_row_advance_cur) begin
            address_base = tile_base_addr_cur;
            address_step = row_addr_step_cur;
        end else if (next_tile_col_advance_cur) begin
            address_base = column_base_addr;
            address_step = col_addr_step_cur;
        end else begin
            address_base = row_group_base_addr_cur;
            address_step = group_row_addr_step_cur;
        end
    end

    // 低字节和进位在准备边沿保存，高位加法随后使用同一组操作数。
    always_ff @(posedge clk) begin
        next_address_base <= address_base;
        next_address_step <= address_step;
        {next_address_carry, next_address_low} <=
            {1'b0, address_base[ADDR_LOW_W-1:0]} + {1'b0, address_step[ADDR_LOW_W-1:0]};
    end
    assign next_address[ADDR_LOW_W-1:0] = next_address_low;
    if (REG_WIDTH > ADDR_LOW_W) begin : g_address_high
        assign {unused_next_address_carry, next_address[REG_WIDTH-1:ADDR_LOW_W]} =
            {1'b0, next_address_base[REG_WIDTH-1:ADDR_LOW_W]} +
            {1'b0, next_address_step[REG_WIDTH-1:ADDR_LOW_W]} + next_address_carry;
    end else begin : g_address_low_only
        assign unused_next_address_carry = next_address_carry;
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
    // 完整位宽的字节分组比较同时准备初始与下一组行数选择。
    unsigned_compare #(.p_width(REG_WIDTH)) u_initial_rows_compare (
        .i_a(k), .i_b(co_initial_limit),
        .o_less(co_initial_is_short), .o_equal(unused_co_compare_equal[0]));
    unsigned_compare #(.p_width(REG_WIDTH)) u_next_rows_compare (
        .i_a(co_next_rows_remaining_q), .i_b(co_rows_limit),
        .o_less(co_next_is_short), .o_equal(unused_co_compare_equal[1]));
    assign row_tiles_decrement = row_tiles_total - count_t'(1);
    assign col_tiles_decrement = col_tiles_total - count_t'(1);
    assign co_initial_rows_calc = 9'(co_initial_is_short ? k : co_initial_limit);
    assign co_next_rows_remaining = cfg_k - (REG_WIDTH'(row_group_next_base_idx) << VCOL_W);
    assign co_next_rows_calc = 9'(co_next_is_short ?
        co_next_rows_remaining_q : co_rows_limit);
    // 行分块数量与行数同时准备，输出 FIFO 的启动判断直接使用寄存结果。
    assign co_initial_k_rows_low = 9'(k);
    assign co_initial_limit_rows_low = 9'(co_initial_limit);
    assign co_initial_k_row_tiles = co_initial_k_rows_low[8:4] +
        {4'b0000, (|co_initial_k_rows_low[3:0])};
    assign co_initial_limit_row_tiles = co_initial_limit_rows_low[8:4] +
        {4'b0000, (|co_initial_limit_rows_low[3:0])};
    always_comb begin
        co_initial_row_tiles_calc = co_initial_is_short ?
            co_initial_k_row_tiles : co_initial_limit_row_tiles;
`ifndef SYNTHESIS
        if ((^{k, co_initial_limit}) === 1'bx) begin
            co_initial_row_tiles_calc = co_initial_rows_calc[8:4] +
                {4'b0000, (|co_initial_rows_calc[3:0])};
        end
`endif
    end
    // 两种候选行数分别计算分块数量，完整范围比较只选择已经准备的结果。
    assign co_next_remaining_rows_low = 9'(co_next_rows_remaining_q);
    assign co_limit_rows_low = 9'(co_rows_limit);
    assign co_next_remaining_row_tiles = co_next_remaining_rows_low[8:4] +
        {4'b0000, (|co_next_remaining_rows_low[3:0])};
    assign co_limit_row_tiles = co_limit_rows_low[8:4] +
        {4'b0000, (|co_limit_rows_low[3:0])};
    assign co_next_row_tiles_calc = co_next_is_short ?
        co_next_remaining_row_tiles : co_limit_row_tiles;
    assign co_advance_group = (state == S_WRITE) && write_done &&
        ((cfg_coalesce && !cfg_is_mode) ? (!co_has_next_col && co_has_next_group) :
        (!next_tile_wrap_r && !next_tile_row_advance_r &&
         !next_tile_col_advance_r && next_tile_group_advance_r));
    assign co_wrap_group = (state == S_WRITE) && write_done &&
        !(cfg_coalesce && !cfg_is_mode) && next_tile_wrap_r;
    assign co_chunk_bytes = REG_WIDTH'(cfg_coalesce_cols) << 4;
    // 配置周期保存连续输出资格和每256字节对应的行数右移量。
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            co_contiguous_q <= (REG_WIDTH'(16) == '0);
            co_row_div_shift_q <= 3'd4;
        end else if (init_cfg) begin
            co_contiguous_q <= m == (REG_WIDTH'(coalesce_cols) << 4);
            case (coalesce_cols)
                5'd16: co_row_div_shift_q <= 3'd0;
                5'd8: co_row_div_shift_q <= 3'd1;
                5'd4: co_row_div_shift_q <= 3'd2;
                5'd2: co_row_div_shift_q <= 3'd3;
                default: co_row_div_shift_q <= 3'd4;
            endcase
        end
    end
    assign co_rows_per_256 = co_valid_rows >> co_row_div_shift_q;
    assign co_row_low_zero[0] = 1'b1;
    for (genvar bits_count = 1; bits_count < 8; bits_count++) begin : g_row_divisibility
        assign co_row_low_zero[bits_count] = (co_valid_rows[bits_count-1:0] == '0);
    end
    assign co_segment_aligned = 4'(co_row_low_zero >> co_row_div_shift_q);
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
            co_initial_row_tiles_q <= is_mode_eff ? 5'd1 : co_initial_row_tiles_calc;
            co_current_row_tiles_q <= is_mode_eff ? 5'd1 : co_initial_row_tiles_calc;
            co_next_row_tiles_q <= '0;
            co_has_next_col <= 1'b0;
            co_has_next_group <= 1'b0;
        end else begin
            if ((state == S_REQ) && write_oa_granted) begin
                co_next_rows_prepared <= co_next_rows_calc;
                co_next_row_tiles_q <= cfg_is_mode ? 5'd1 : co_next_row_tiles_calc;
                co_has_next_col <= co_next_col_offset_q < cfg_m;
                co_has_next_group <= group_total_difference[CNT_W];
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
    // 保存模式生效后的组大小，输出 FIFO 直接读取寄存值。
    assign coalesce_row_tiles = co_current_row_tiles_q;
    assign coalesce_group_start = dma_start && cfg_coalesce && !cfg_is_mode;
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            co_dma_rows <= 0; co_dma_stride <= 0; co_dma_len <= 0;
        end else if (cfg_lat_tick || (state == S_REQ && write_oa_granted)) begin
            if (cfg_is_mode) begin
                co_dma_rows <= 0;
                co_dma_stride <= 0;
                co_dma_len <= 8'(REG_WIDTH'(cfg_coalesce_cols) * 16 / BYTE_PER_BEAT) - 1'b1;
            end else if (BUS_WIDTH == 64 && co_contiguous_q && co_segment_aligned[3]) begin
                co_dma_rows <= co_rows_per_256 >> 3;
                co_dma_stride <= REG_WIDTH'(2048);
                co_dma_len <= 8'd255;
            end else if (co_contiguous_q && co_segment_aligned[2]) begin
                co_dma_rows <= co_rows_per_256 >> 2;
                co_dma_stride <= REG_WIDTH'(1024);
                co_dma_len <= 8'(1024 / BYTE_PER_BEAT - 1);
            end else if (co_contiguous_q && co_segment_aligned[1]) begin
                co_dma_rows <= co_rows_per_256 >> 1;
                co_dma_stride <= REG_WIDTH'(512);
                co_dma_len <= 8'(512 / BYTE_PER_BEAT - 1);
            end else if (co_contiguous_q && co_segment_aligned[0]) begin
                co_dma_rows <= co_rows_per_256;
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
            row_tiles_last_idx <= (row_tiles_total == '0) ? '0 : row_tiles_decrement;
            col_tiles_last_idx <= (col_tiles_total == '0) ? '0 : col_tiles_decrement;
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
            beats_per_row_cur_tile <= '0;
            tile_base_addr_cur <= '0;
            row_addr_step_cur <= '0;
            col_addr_step_cur <= '0;
            group_row_addr_step_cur <= '0;
            row_group_base_addr_cur <= '0;
            column_base_addr <= '0;
            col_offset_addr_cur <= '0;
            row_offset_addr_cur <= '0;
            tile_row_is_last <= 1'b1;
            tile_col_is_last <= 1'b1;
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
                beats_per_row_cur_tile <= '0;
                tile_base_addr_cur <= dst_base;
                row_addr_step_cur <= init_row_addr_step;
                col_addr_step_cur <= init_col_addr_step;
                group_row_addr_step_cur <= '0;
                row_group_base_addr_cur <= dst_base;
                column_base_addr <= dst_base;
                col_offset_addr_cur <= '0;
                row_offset_addr_cur <= '0;
                tile_row_is_last <= row_initial_is_last_pre;
                tile_col_is_last <= col_initial_is_last_pre;
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
                            // 行步长与复用数量已经保存，组步长在首次请求之前准备。
                            group_row_addr_step_cur <= init_group_row_addr_step;
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
                            beats_per_row_cur_tile <= beats_per_row_calc;
                            row_in_tile <= '0;
                            beats_in_row <= '0;

                            state <= S_START;
                        end
                    end

                    S_START: begin
                        if (dma_start) begin
                            next_tile_row_is_last_r <= next_tile_row_is_last_cur;
                            next_tile_col_is_last_r <= next_tile_col_is_last_cur;
                            next_tile_wrap_r <= next_tile_wrap_cur;
                            next_tile_row_advance_r <= next_tile_row_advance_cur;
                            next_tile_col_advance_r <= next_tile_col_advance_cur;
                            next_tile_group_advance_r <= next_tile_group_advance_cur;
                            vec_valid_num_col_next_r <= vec_valid_num_col_next_w[VCOL_W-1:0];
                            vec_valid_num_row_next_r <= vec_valid_num_row_next_w[VCOL_W-1:0];

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
                                    col_offset_addr_cur <= co_next_col_offset_q;
                                    tile_base_addr_cur <= next_address;
                                    column_base_addr <= next_address;
                                    state <= S_IDLE;
                                end else if (!co_has_next_group) begin
                                    oa_calc_over_r <= 1'b1;
                                    state <= S_DONE;
                                end else begin
                                    row_group_base_idx <= row_group_next_base_idx;
                                    row_group_next_base_idx <= row_group_next_sum;
                                    col_offset_addr_cur <= 0;
                                    row_group_base_addr_cur <= next_address;
                                    tile_base_addr_cur <= next_address;
                                    column_base_addr <= next_address;
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
                                column_base_addr <= cfg_dst_base;
                                col_offset_addr_cur <= '0;
                                row_offset_addr_cur <= '0;
                                tile_row_is_last <= (row_tiles_last_idx == '0);
                                tile_col_is_last <= (col_tiles_last_idx == '0);

                            end else begin
                                tile_row_idx <= next_tile_row_cur;
                                tile_col_idx <= next_tile_col_cur;
                                tile_row_is_last <= next_tile_row_is_last_r;
                                tile_col_is_last <= next_tile_col_is_last_r;
                                vec_valid_num_col_r <= vec_valid_num_col_next_r;
                                vec_valid_num_row_r <= vec_valid_num_row_next_r;
                                if (next_tile_row_advance_r) begin
                                    row_offset_addr_cur <= row_offset_next;
                                    tile_base_addr_cur <= next_address;
                                end else if (next_tile_col_advance_r) begin
                                    col_offset_addr_cur <= col_offset_next;
                                    row_offset_addr_cur <= '0;
                                    tile_base_addr_cur <= next_address;
                                    column_base_addr <= next_address;
                                end else if (next_tile_group_advance_r) begin
                                    row_group_base_idx <= row_group_next_base_idx;
                                    row_group_next_base_idx <= row_group_next_sum;
                                    row_group_base_addr_cur <= next_address;
                                    col_offset_addr_cur <= '0;
                                    row_offset_addr_cur <= '0;
                                    tile_base_addr_cur <= next_address;
                                    column_base_addr <= next_address;
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
