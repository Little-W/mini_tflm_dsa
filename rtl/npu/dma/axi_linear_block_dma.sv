/*
 * axi_linear_block_dma -- native AXI4 linear read/write engine
 * ======================================================
 *
 * This module is the shared AXI block DMA for accelerator memory traffic.
 * Read and write commands are split into independent engines:
 *
 *   - read  engine: AXI AR/R, used by IA/kernel/bias/quant loaders
 *   - write engine: AXI AW/W/B, used by OA writer
 *
 * The two engines can be active at the same time, allowing AXI full-duplex
 * memory traffic without a protocol bridge.
 */

module axi_linear_block_dma #(
    parameter int unsigned DATA_WIDTH   = 16,
    parameter int unsigned SIZE         = 16,
    parameter int unsigned BUS_WIDTH    = 32,
    parameter int unsigned REG_WIDTH    = 32,
    parameter int unsigned CACHE_BLOCKS = 4,
    parameter int unsigned DMA_MAX_BYTES = 256 * (BUS_WIDTH / 8),
    parameter int unsigned READ_OUTSTANDING = 4,
    parameter int unsigned RD_CONTEXT_DEPTH = 4,
    parameter int unsigned RD_TAG_WIDTH = 3,
    parameter int unsigned WRITE_OUTSTANDING = READ_OUTSTANDING
) (
    input logic clk,
    input logic rst_n,
    input logic abort = 1'b0,

    // ---- Read block command ----
    input  logic                                   rd_start,
    output logic                                   rd_start_ready,
    input  logic [RD_TAG_WIDTH-1:0]                 rd_tag = '0,
    output logic [RD_TAG_WIDTH-1:0]                 rd_response_tag,
    output logic [RD_TAG_WIDTH-1:0]                 rd_finish_tag,
    input  logic                                   rd_linear_read_mode,
    input  logic        [           REG_WIDTH-1:0] rd_base_addr,
    input  logic        [           REG_WIDTH-1:0] rd_row_stride,
    input  logic        [           REG_WIDTH-1:0] rd_rows_to_read,
    input  logic        [           REG_WIDTH-1:0] rd_valid_cols,
    input  logic        [                     7:0] rd_burst_len_m1,
    input  logic        [((CACHE_BLOCKS <= 1) ? 1 : $clog2(CACHE_BLOCKS))-1:0] rd_slot_id,
    input  logic                                   rd_use_16bits,
    input  logic signed [           REG_WIDTH-1:0] rd_lhs_zp,
    output logic                                   rd_busy,
    output logic                                   rd_done,
    output logic                                   rd_finish_beat,

    // ---- Write block command ----
    input  logic                            wr_start,
    input  logic [           REG_WIDTH-1:0] wr_base_addr,
    input  logic [           REG_WIDTH-1:0] wr_row_stride,
    input  logic [           REG_WIDTH-1:0] wr_rows_to_write,
    input  logic [                     7:0] wr_burst_len_m1,
    output logic                            wr_busy,
    output logic                            wr_done,

    // ---- Write data stream ----
    input  logic [  BUS_WIDTH-1:0] src_wdata,
    input  logic [BUS_WIDTH/8-1:0] src_wmask,
    input  logic                   src_wvalid,
    output logic                   src_wready,

    // ---- AXI4 master read address channel ----
    output logic                   m_axi_arvalid,
    input  logic                   m_axi_arready,
    output logic [  REG_WIDTH-1:0] m_axi_araddr,
    output logic [            7:0] m_axi_arlen,
    output logic [            2:0] m_axi_arsize,
    output logic [            1:0] m_axi_arburst,

    // ---- AXI4 master read data channel ----
    input  logic                   m_axi_rvalid,
    output logic                   m_axi_rready,
    input  logic [  BUS_WIDTH-1:0] m_axi_rdata,
    input  logic [            1:0] m_axi_rresp,
    input  logic                   m_axi_rlast,

    // ---- AXI4 master write address channel ----
    output logic                   m_axi_awvalid,
    input  logic                   m_axi_awready,
    output logic [  REG_WIDTH-1:0] m_axi_awaddr,
    output logic [            7:0] m_axi_awlen,
    output logic [            2:0] m_axi_awsize,
    output logic [            1:0] m_axi_awburst,

    // ---- AXI4 master write data channel ----
    output logic                   m_axi_wvalid,
    input  logic                   m_axi_wready,
    output logic [  BUS_WIDTH-1:0] m_axi_wdata,
    output logic [BUS_WIDTH/8-1:0] m_axi_wstrb,
    output logic                   m_axi_wlast,

    // ---- AXI4 master write response channel ----
    input  logic                   m_axi_bvalid,
    output logic                   m_axi_bready,
    input  logic [            1:0] m_axi_bresp,

    // ---- Read unpack output ----
    output logic        [((CACHE_BLOCKS <= 1) ? 1 : $clog2(CACHE_BLOCKS))-1:0] wr_slot,
    output logic        [        $clog2(SIZE)-1:0] wr_row,
    output logic        [        $clog2(SIZE)-1:0] wr_col_base,
    output logic signed [          DATA_WIDTH-1:0] wr_data      [BUS_WIDTH/8],
    output logic                                   wr_valid     [BUS_WIDTH/8],
    output logic                                   wr_use_16bits,

    // ---- Raw read stream for quant/bias-like users ----
    output logic [   BUS_WIDTH-1:0] rd_raw_data,
    output logic                    rd_raw_valid,
    output logic [$clog2(SIZE)-1:0] rd_raw_row,
    output logic [$clog2(SIZE)-1:0] rd_raw_col_base,

    output logic rd_error,
    output logic wr_error
);

    localparam int unsigned BYTE_PER_BEAT = BUS_WIDTH / 8;
    localparam int unsigned MAX_BURST_BEATS = DMA_MAX_BYTES / BYTE_PER_BEAT;
`ifdef NPU_SIM_ASSERT
    initial begin
        if (DMA_MAX_BYTES < BYTE_PER_BEAT || DMA_MAX_BYTES > 256 * BYTE_PER_BEAT ||
            DMA_MAX_BYTES % BYTE_PER_BEAT != 0 ||
            (DMA_MAX_BYTES & (DMA_MAX_BYTES - 1)) != 0 || MAX_BURST_BEATS > 256)
            $fatal(1, "DMA_MAX_BYTES must contain a power-of-two count of 1 through 256 complete AXI beats");
    end
`endif

    localparam int unsigned ELEM_PER_BEAT_S8 = BYTE_PER_BEAT;
    localparam int unsigned ELEM_PER_BEAT_S16 = BYTE_PER_BEAT >> 1;
    localparam int unsigned ADDR_LSB = $clog2(BYTE_PER_BEAT);
    localparam int unsigned AXI_SIZE_VALUE = $clog2(BYTE_PER_BEAT);
    localparam int unsigned RD_OUTS_MAX =
        (READ_OUTSTANDING < 1) ? 1 : READ_OUTSTANDING;
    localparam int unsigned RD_OUTS_W =
        (RD_OUTS_MAX < 2) ? 1 : $clog2(RD_OUTS_MAX + 1);
    localparam int unsigned WR_OUTS_MAX =
        (WRITE_OUTSTANDING < 1) ? 1 : WRITE_OUTSTANDING;
    localparam int unsigned WR_OUTS_W =
        (WR_OUTS_MAX < 2) ? 1 : $clog2(WR_OUTS_MAX + 1);
    localparam int unsigned ROW_CNT_W = (SIZE <= 1) ? 1 : $clog2(SIZE + 1);
    localparam int unsigned BEAT_CNT_W = 9;
    localparam bit SUPPORT_16BIT = (DATA_WIDTH > 8);
    typedef logic [ROW_CNT_W-1:0] row_count_t;
    // A segmented output descriptor can span 16 row tiles (256 rows).
    localparam int unsigned WR_ROW_CNT_W = (ROW_CNT_W > 9) ? ROW_CNT_W : 9;
    typedef logic [WR_ROW_CNT_W-1:0] write_row_count_t;
    typedef logic [BEAT_CNT_W-1:0] beat_count_t;

    wire rd_ar_hs = m_axi_arvalid && m_axi_arready;
    wire rd_r_hs  = m_axi_rvalid && m_axi_rready;
    wire rd_r_last_hs = rd_r_hs && m_axi_rlast;
    wire wr_aw_hs = m_axi_awvalid && m_axi_awready;
    wire wr_w_hs  = m_axi_wvalid && m_axi_wready;
    wire wr_b_hs  = m_axi_bvalid && m_axi_bready;

    // ---------------------------------------------------------------------
    // Read command issue and ordered response contexts
    // ---------------------------------------------------------------------
    localparam int unsigned RD_CTX_DEPTH = (RD_CONTEXT_DEPTH < 1) ? 1 : RD_CONTEXT_DEPTH;
    localparam int unsigned RD_CTX_PTR_W = (RD_CTX_DEPTH <= 1) ? 1 : $clog2(RD_CTX_DEPTH);
    localparam int unsigned RD_CTX_CNT_W = $clog2(RD_CTX_DEPTH + 1);
    localparam int unsigned RD_SLOT_W = (CACHE_BLOCKS <= 1) ? 1 : $clog2(CACHE_BLOCKS);
    typedef logic [RD_CTX_PTR_W-1:0] context_ptr_t;
    typedef logic [RD_CTX_CNT_W-1:0] context_count_t;
    typedef struct packed {
        logic [REG_WIDTH-1:0] row_stride;
        row_count_t rows;
        logic [REG_WIDTH-1:0] valid_cols;
        logic [7:0] burst_len_m1;
        beat_count_t cross_last;
        logic [RD_SLOT_W-1:0] slot;
        logic linear_read;
        logic use_16bits;
        logic signed [REG_WIDTH-1:0] zp;
        logic [RD_TAG_WIDTH-1:0] tag;
    } response_context_t;
    typedef struct packed {
        logic [REG_WIDTH-1:0] base_addr;
        response_context_t response;
    } read_context_t;

    localparam int unsigned p_context_data_width = $bits(response_context_t) - RD_TAG_WIDTH;
    logic [RD_TAG_WIDTH-1:0] rd_context_tag_q [RD_CTX_DEPTH];
    logic context_storage_i_wr_en;
    logic [RD_CTX_PTR_W-1:0] context_storage_i_wr_addr;
    logic [p_context_data_width-1:0] context_storage_i_wr_data;
    logic [0:0] context_storage_i_wr_mask;
    logic [0:0] context_storage_i_rd_en;
    logic [0:0][RD_CTX_PTR_W-1:0] context_storage_i_rd_addr;
    logic [0:0][p_context_data_width-1:0] context_storage_o_rd_data;
    logic [0:0] context_base_i_rd_en;
    logic [0:0][RD_CTX_PTR_W-1:0] context_base_i_rd_addr;
    logic [REG_WIDTH-1:0] context_base_i_wr_data;
    logic [0:0][REG_WIDTH-1:0] context_base_o_rd_data;
    response_context_t rd_head;
    read_context_t rd_incoming;
    context_ptr_t rd_context_head, rd_context_tail;
    context_ptr_t rd_context_head_nxt, rd_context_tail_nxt;
    context_ptr_t rd_context_head_plus_one, rd_context_tail_plus_one;
    logic unused_context_head_carry, unused_context_tail_carry;
    context_count_t rd_context_count;
    context_count_t rd_context_increment, rd_context_decrement;
    logic rd_context_nonempty_q, rd_context_space_q;
    // 相邻计数并行计算，保存的资格与描述符计数在同一边沿更新。
    assign rd_context_increment = rd_context_count + context_count_t'(1);
    assign rd_context_decrement = rd_context_count - context_count_t'(1);
    logic rd_issue_active;
    logic [REG_WIDTH-1:0] rd_cfg_base_addr, rd_cfg_row_stride;
    row_count_t rd_cfg_rows;
    logic [7:0] rd_cfg_burst_len_m1;
    logic rd_cfg_linear_read;
    row_count_t rd_cmd_row_cnt;
    logic [REG_WIDTH-1:0] rd_cmd_row_addr;
    logic rd_arvalid_r;
    logic [REG_WIDTH-1:0] rd_araddr_r;
    logic [7:0] rd_arlen_r;
    logic [REG_WIDTH-1:0] rd_follow_addr;
    beat_count_t rd_follow_beats;
    logic [RD_OUTS_W-1:0] rd_outstanding_cnt;
    logic rd_pending_cmd_cross;

    row_count_t rd_rsp_row_cnt;
    logic [REG_WIDTH-1:0] rd_rsp_row_addr_cur, rd_rsp_row_addr_direct;
    logic rd_rsp_from_context;
    beat_count_t rd_rsp_beat_cnt;
    logic [BUS_WIDTH-1:0] rd_rsp_prev_data, rd_rsp_data_r;
    row_count_t rd_rsp_row_r;
    logic [$clog2(SIZE)-1:0] rd_rsp_col_base_r;
    logic rd_rsp_valid_r;
    logic [RD_SLOT_W-1:0] rd_rsp_slot;
    logic rd_rsp_use_16bits;
    logic signed [REG_WIDTH-1:0] rd_rsp_zp;
    logic [REG_WIDTH-1:0] rd_rsp_valid_cols;
    logic [BYTE_PER_BEAT-1:0] rd_rsp_lane_in_data_r, rd_rsp_lane_in_data_comb;
    logic rd_done_r, rd_response_error, rd_completed_error;
    logic [BEAT_CNT_W-1:0] rsp_last_equal_i_a, rsp_last_equal_i_b;
    logic [BEAT_CNT_W-1:0] rsp_last_equal_i_target;
    logic rsp_last_equal_i_carry_in;
    logic rsp_last_equal_o_equal;
    logic [ROW_CNT_W-1:0] rsp_row_equal_i_a, rsp_row_equal_i_b;
    logic [ROW_CNT_W-1:0] rsp_row_equal_i_target;
    logic rsp_row_equal_i_carry_in;
    (* keep = "true" *) logic rsp_row_equal_o_equal;
    (* keep = "true" *) logic rd_rsp_last_without_cross, rd_rsp_last_with_cross;
    logic rd_rsp_done;
    wire rd_active = rd_context_nonempty_q;
    (* keep = "true" *) logic rd_accept_issuer;
    (* keep = "true" *) wire rd_accept_start = rd_accept_issuer &&
        (rd_context_space_q || rd_finish_beat);
    wire rd_unaligned_mode = rd_cfg_base_addr[ADDR_LSB-1:0] != '0 ||
                             rd_cfg_row_stride[ADDR_LSB-1:0] != '0;
    wire [ADDR_LSB-1:0] rd_rsp_offset = rd_rsp_row_addr_cur[ADDR_LSB-1:0];
    wire rd_rsp_cross = rd_rsp_offset != '0;
    wire rd_rsp_emit = !rd_rsp_cross || rd_rsp_beat_cnt != '0;
    // 两种字节排列分别判断最后一拍，行地址低位只选择已经完成的比较结果。
    // 线性读取对应一个有效字，跨字读取再接收一拍以组成完整数据。
    // 加一结果的各位进位条件并行比较，末拍和末行判断共用相同的算术结构。
    assign rsp_last_equal_i_a = beat_count_t'(rd_head.burst_len_m1);
    assign rsp_last_equal_i_b = beat_count_t'(1);
    assign rsp_last_equal_i_target = rd_rsp_beat_cnt;
    assign rsp_last_equal_i_carry_in = 1'b0;
    assign rsp_row_equal_i_a = rd_rsp_row_cnt;
    assign rsp_row_equal_i_b = row_count_t'(1);
    assign rsp_row_equal_i_target = rd_head.rows;
    assign rsp_row_equal_i_carry_in = 1'b0;

    add_equal #(.p_width(BEAT_CNT_W), .p_use_lut(1'b0)) u_rsp_last_equal (
        .i_a(rsp_last_equal_i_a), .i_b(rsp_last_equal_i_b),
        .i_target(rsp_last_equal_i_target), .i_carry_in(rsp_last_equal_i_carry_in),
        .o_equal(rsp_last_equal_o_equal)
    );

    add_equal #(.p_width(ROW_CNT_W)) u_rsp_row_equal (
        .i_a(rsp_row_equal_i_a), .i_b(rsp_row_equal_i_b),
        .i_target(rsp_row_equal_i_target), .i_carry_in(rsp_row_equal_i_carry_in),
        .o_equal(rsp_row_equal_o_equal)
    );

    localparam int unsigned p_read_last_groups = (BEAT_CNT_W + 2) / 3;
    logic [BEAT_CNT_W-1:0] rd_rsp_plain_last;
    (* keep = "true" *) logic [p_read_last_groups-1:0] rd_rsp_plain_equal_group;
    assign rd_rsp_plain_last = beat_count_t'(rd_head.burst_len_m1);
    // 三位分组独立检查末拍序号，随后合并相等结果。
    for (genvar group = 0; group < p_read_last_groups; group++) begin : g_read_plain_equal
        localparam int unsigned p_first = 3 * group;
        localparam int unsigned p_bits = BEAT_CNT_W - p_first < 3 ? BEAT_CNT_W - p_first : 3;
        assign rd_rsp_plain_equal_group[group] = rd_rsp_beat_cnt[p_first +: p_bits] ==
            rd_rsp_plain_last[p_first +: p_bits];
    end
    (* keep = "true" *) logic [p_read_last_groups-1:0] rd_rsp_zero_group, rd_rsp_one_group;
    for (genvar group = 0; group < p_read_last_groups; group++) begin : g_read_linear_equal
        localparam int unsigned p_first = 3 * group;
        localparam int unsigned p_bits = BEAT_CNT_W - p_first < 3 ? BEAT_CNT_W - p_first : 3;
        assign rd_rsp_zero_group[group] = rd_rsp_beat_cnt[p_first +: p_bits] == p_bits'(0);
        assign rd_rsp_one_group[group] = rd_rsp_beat_cnt[p_first +: p_bits] == p_bits'(group == 0);
    end
    (* keep = "true" *) logic rd_rsp_count_zero, rd_rsp_count_one, rd_rsp_plain_equal;
    assign rd_rsp_count_zero = &rd_rsp_zero_group;
    assign rd_rsp_count_one = &rd_rsp_one_group;
    assign rd_rsp_plain_equal = &rd_rsp_plain_equal_group;
    assign rd_rsp_last_without_cross = rd_head.linear_read ? rd_rsp_count_zero : rd_rsp_plain_equal;
    (* keep = "true" *) logic [p_read_last_groups-1:0] rd_rsp_cross_equal_group;
    logic rd_rsp_cross_equal;
    for (genvar group = 0; group < p_read_last_groups; group++) begin : g_read_cross_equal
        localparam int unsigned p_first = 3 * group;
        localparam int unsigned p_bits = BEAT_CNT_W - p_first < 3 ? BEAT_CNT_W - p_first : 3;
        assign rd_rsp_cross_equal_group[group] = rd_rsp_beat_cnt[p_first +: p_bits] ==
            rd_head.cross_last[p_first +: p_bits];
    end
    // 跨字末拍序号随描述符保存，响应阶段直接比较当前拍数。
    always_comb begin
        case (^{rd_head.burst_len_m1, rd_head.cross_last, rd_rsp_beat_cnt})
            1'b0, 1'b1: rd_rsp_cross_equal = &rd_rsp_cross_equal_group;
            default: rd_rsp_cross_equal = rsp_last_equal_o_equal;
        endcase
    end
    assign rd_rsp_last_with_cross = rd_head.linear_read ?
        rd_rsp_count_one : rd_rsp_cross_equal;
    // 末拍和末行条件并行准备，地址低位只选择对应的完成结果。
    assign rd_rsp_done = rd_r_hs &&
        (rd_rsp_cross ? rd_rsp_last_with_cross : rd_rsp_last_without_cross);
    assign rd_finish_beat = rd_rsp_done && rsp_row_equal_o_equal;
    (* keep = "true" *) wire rd_issue_all_rows = rd_issue_active &&
        rd_follow_beats == '0 && rd_cmd_row_cnt == rd_cfg_rows;
    wire rd_issue_last_ar = rd_ar_hs && rd_issue_all_rows;
    assign rd_accept_issuer = rd_start && !abort && (!rd_issue_active || rd_issue_last_ar);

    assign {unused_context_head_carry, rd_context_head_plus_one} =
        {1'b0, rd_context_head} + (RD_CTX_PTR_W+1)'(1);
    assign {unused_context_tail_carry, rd_context_tail_plus_one} =
        {1'b0, rd_context_tail} + (RD_CTX_PTR_W+1)'(1);
    assign rd_context_head_nxt = rd_context_head == context_ptr_t'(RD_CTX_DEPTH-1) ?
        '0 : rd_context_head_plus_one;
    assign rd_context_tail_nxt = rd_context_tail == context_ptr_t'(RD_CTX_DEPTH-1) ?
        '0 : rd_context_tail_plus_one;

    // 描述符数据采用异步读取，命令标签独立复位，保持原有接收和响应周期。
    assign context_storage_i_wr_en = rst_n && rd_accept_start;
    assign context_storage_i_wr_addr = rd_context_tail;
    assign context_storage_i_wr_data = rd_incoming.response[$bits(response_context_t)-1:RD_TAG_WIDTH];
    assign context_storage_i_wr_mask = 1'b1;
    assign context_storage_i_rd_en = 1'b1;
    assign context_storage_i_rd_addr[0] = rd_context_head;
    assign rd_head = {context_storage_o_rd_data[0], rd_context_tag_q[rd_context_head]};
    // 下一描述符的基地址在当前描述符完成边沿读取，保持原有地址更新周期。
    assign context_base_i_wr_data = rd_incoming.base_addr;
    assign context_base_i_rd_en[0] = rst_n && rd_finish_beat &&
        rd_context_count > context_count_t'(1);
    assign context_base_i_rd_addr[0] = rd_context_head_nxt;
    assign rd_rsp_row_addr_cur = rd_rsp_from_context ?
        context_base_o_rd_data[0] : rd_rsp_row_addr_direct;

    regfile #(
        .p_data_width(p_context_data_width), .p_depth(RD_CTX_DEPTH),
        .p_addr_width(RD_CTX_PTR_W), .p_write_unit(p_context_data_width),
        .p_read_ports(1), .p_sync_read(1'b0)
    ) u_context_storage (
        .clk(clk), .i_wr_en(context_storage_i_wr_en), .i_wr_addr(context_storage_i_wr_addr),
        .i_wr_data(context_storage_i_wr_data), .i_wr_mask(context_storage_i_wr_mask),
        .i_rd_en(context_storage_i_rd_en), .i_rd_addr(context_storage_i_rd_addr),
        .o_rd_data(context_storage_o_rd_data)
    );

    regfile #(
        .p_data_width(REG_WIDTH), .p_depth(RD_CTX_DEPTH),
        .p_addr_width(RD_CTX_PTR_W), .p_write_unit(REG_WIDTH),
        .p_read_ports(1), .p_sync_read(1'b1), .p_ram_style("block")
    ) u_context_base (
        .clk(clk), .i_wr_en(context_storage_i_wr_en), .i_wr_addr(context_storage_i_wr_addr),
        .i_wr_data(context_base_i_wr_data), .i_wr_mask(context_storage_i_wr_mask),
        .i_rd_en(context_base_i_rd_en), .i_rd_addr(context_base_i_rd_addr),
        .o_rd_data(context_base_o_rd_data)
    );

    always_comb begin
        rd_incoming.base_addr = rd_base_addr;
        rd_incoming.response.row_stride = rd_row_stride;
        rd_incoming.response.rows = row_count_t'(rd_rows_to_read);
        rd_incoming.response.valid_cols = rd_valid_cols == '0 ? REG_WIDTH'(SIZE) : rd_valid_cols;
        rd_incoming.response.burst_len_m1 = rd_burst_len_m1;
        rd_incoming.response.cross_last = beat_count_t'(rd_burst_len_m1) + beat_count_t'(1);
        rd_incoming.response.slot = rd_slot_id;
        rd_incoming.response.linear_read = rd_linear_read_mode;
        rd_incoming.response.use_16bits = SUPPORT_16BIT && rd_use_16bits;
        rd_incoming.response.zp = rd_lhs_zp;
        rd_incoming.response.tag = rd_tag;
    end

    assign rd_finish_tag = rd_head.tag;
    assign rd_start_ready = (!rd_issue_active || rd_issue_last_ar) &&
                            (rd_context_space_q || rd_finish_beat);
    assign rd_busy = rd_active;
    assign rd_done = rd_done_r;
    assign rd_error = rd_done_r ? rd_completed_error : rd_response_error;
    assign m_axi_arsize = 3'(AXI_SIZE_VALUE);
    assign m_axi_arburst = 2'b01;
    assign m_axi_arvalid = rd_arvalid_r && rd_outstanding_cnt < RD_OUTS_W'(RD_OUTS_MAX);
    assign m_axi_araddr = rd_araddr_r;
    assign m_axi_arlen = rd_arlen_r;
    assign m_axi_rready = rd_active;
    assign wr_slot = rd_rsp_slot;
    assign wr_use_16bits = rd_rsp_use_16bits;

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            rd_context_head <= '0;
            rd_context_tail <= '0;
            rd_context_count <= '0;
            rd_context_nonempty_q <= 1'b0;
            rd_context_space_q <= 1'b1;
        end else begin
            if (rd_accept_start) begin
                rd_context_tail <= rd_context_tail_nxt;
            end
            if (rd_finish_beat) rd_context_head <= rd_context_head_nxt;
            unique case ({rd_accept_start,rd_finish_beat})
                2'b10: begin
                    rd_context_count <= rd_context_increment;
                    rd_context_nonempty_q <= rd_context_increment != '0;
                    rd_context_space_q <= rd_context_increment < context_count_t'(RD_CTX_DEPTH);
                end
                2'b01: begin
                    rd_context_count <= rd_context_decrement;
                    rd_context_nonempty_q <= rd_context_decrement != '0;
                    rd_context_space_q <= rd_context_decrement < context_count_t'(RD_CTX_DEPTH);
                end
                default: ;
            endcase
        end
    end

    // 标签复位不影响数据阵列，新的描述符在同一接收边沿写入数据与标签。
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            for (int i=0; i<RD_CTX_DEPTH; i++) rd_context_tag_q[i] <= '0;
        end else if (rd_accept_start) begin
            rd_context_tag_q[rd_context_tail] <= rd_incoming.response.tag;
        end
    end

    // AXI credits cover physical bursts from all accepted logical commands.
    always_ff @(posedge clk) begin
        if (!rst_n) rd_outstanding_cnt <= '0;
        else begin
            unique case ({rd_ar_hs,rd_r_last_hs})
                2'b10: rd_outstanding_cnt <= rd_outstanding_cnt + 1'b1;
                2'b01: rd_outstanding_cnt <= rd_outstanding_cnt - 1'b1;
                default: ;
            endcase
        end
    end

    //! 读取命令准备
    //! ------------
    // 接收、页长度选择和地址更新分别保存在寄存器中，同一套算术处理所有突发。
    typedef enum logic [1:0] {
        RD_ISSUE_IDLE,
        RD_ISSUE_LIMIT,
        RD_ISSUE_COMMIT,
        RD_ISSUE_WAIT
    } read_issue_phase_t;
    (* fsm_encoding = "none" *) read_issue_phase_t rd_issue_phase;
    logic [REG_WIDTH-1:0] rd_plan_addr;
    beat_count_t rd_plan_remaining, rd_plan_selected;
    logic rd_plan_has_rows;
    logic [12:0] rd_plan_page_beats;
    logic rd_plan_page_limited, rd_plan_burst_limited;
    beat_count_t rd_plan_limited;
    (* use_dsp = "yes" *) logic [REG_WIDTH:0] rd_plan_next_addr_sum;
    (* use_dsp = "yes" *) logic [REG_WIDTH:0] rd_cmd_start_addr_sum;
    (* use_dsp = "yes" *) logic [REG_WIDTH:0] rd_cmd_next_addr_sum;
    (* use_dsp = "yes" *) logic [REG_WIDTH:0] rd_rsp_next_addr_sum;
    logic [REG_WIDTH-1:0] merge_i_stride_a, merge_i_stride_b, merge_i_stride_target;
    logic merge_i_carry, merge_o_stride_equal;
    logic [REG_WIDTH-1:0] rd_merged_beats;
    logic rd_merge_rows;
    beat_count_t rd_first_beats, rd_first_span_beats, rd_next_row_beats;

    assign merge_i_stride_a = REG_WIDTH'(rd_linear_read_mode ? 8'd0 : rd_burst_len_m1) << ADDR_LSB;
    assign merge_i_stride_b = REG_WIDTH'(1) << ADDR_LSB;
    assign merge_i_stride_target = rd_row_stride;
    assign merge_i_carry = 1'b0;
    add_equal #(.p_width(REG_WIDTH)) u_merge_stride_equal (
        .i_a(merge_i_stride_a), .i_b(merge_i_stride_b), .i_target(merge_i_stride_target),
        .i_carry_in(merge_i_carry), .o_equal(merge_o_stride_equal)
    );

    assign rd_merged_beats = REG_WIDTH'(row_count_t'(rd_rows_to_read)) *
        REG_WIDTH'(rd_linear_read_mode ? 8'd0 : rd_burst_len_m1) +
        REG_WIDTH'(row_count_t'(rd_rows_to_read));
    assign rd_merge_rows = rd_base_addr[ADDR_LSB-1:0] == '0 && merge_o_stride_equal &&
        row_count_t'(rd_rows_to_read) > row_count_t'(1) && rd_merged_beats <= REG_WIDTH'(256);
    assign rd_first_beats = beat_count_t'(1) +
        (rd_linear_read_mode ? beat_count_t'(0) : beat_count_t'(rd_burst_len_m1)) +
        beat_count_t'(rd_base_addr[ADDR_LSB-1:0] != '0);
    assign rd_first_span_beats = rd_merge_rows ? beat_count_t'(rd_merged_beats) : rd_first_beats;
    assign rd_next_row_beats = beat_count_t'(1) +
        (rd_cfg_linear_read ? beat_count_t'(0) : beat_count_t'(rd_cfg_burst_len_m1)) +
        beat_count_t'(rd_cmd_row_addr[ADDR_LSB-1:0] != '0);

    // 页限制和突发上限同时比较，选择后的拍数在下一阶段用于地址及计数更新。
    assign rd_plan_page_beats = (13'd4096 - {1'b0, rd_plan_addr[11:0]}) >> ADDR_LSB;
    assign rd_plan_page_limited = rd_plan_page_beats < 13'(MAX_BURST_BEATS) &&
        13'(rd_plan_remaining) > rd_plan_page_beats;
    assign rd_plan_burst_limited = rd_plan_remaining > beat_count_t'(MAX_BURST_BEATS);
    assign rd_plan_limited = rd_plan_page_limited ? beat_count_t'(rd_plan_page_beats) :
        (rd_plan_burst_limited ? beat_count_t'(MAX_BURST_BEATS) : rd_plan_remaining);
    assign rd_plan_next_addr_sum = {1'b0, rd_plan_addr} +
        ((REG_WIDTH+1)'(rd_plan_selected) << ADDR_LSB);
    assign rd_cmd_start_addr_sum = {1'b0, rd_base_addr} + {1'b0, rd_row_stride};
    assign rd_cmd_next_addr_sum = {1'b0, rd_cmd_row_addr} + {1'b0, rd_cfg_row_stride};
    assign rd_rsp_next_addr_sum = {1'b0, rd_rsp_row_addr_cur} + {1'b0, rd_head.row_stride};

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            rd_issue_active <= 1'b0;
            rd_issue_phase <= RD_ISSUE_IDLE;
            rd_arvalid_r <= 1'b0;
            rd_araddr_r <= '0;
            rd_arlen_r <= '0;
            rd_plan_addr <= '0;
            rd_plan_remaining <= '0;
            rd_plan_selected <= '0;
            rd_plan_has_rows <= 1'b0;
        end else if (rd_accept_start) begin
            rd_issue_active <= 1'b1;
            rd_issue_phase <= RD_ISSUE_LIMIT;
            rd_arvalid_r <= 1'b0;
            rd_cfg_base_addr <= rd_base_addr;
            rd_cfg_row_stride <= rd_row_stride;
            rd_cfg_rows <= row_count_t'(rd_rows_to_read);
            rd_cfg_burst_len_m1 <= rd_burst_len_m1;
            rd_cfg_linear_read <= rd_linear_read_mode;
            rd_plan_addr <= {rd_base_addr[REG_WIDTH-1:ADDR_LSB], {ADDR_LSB{1'b0}}};
            rd_plan_remaining <= rd_first_span_beats;
            rd_plan_has_rows <= row_count_t'(rd_rows_to_read) != '0;
            rd_cmd_row_cnt <= rd_merge_rows ? row_count_t'(rd_rows_to_read) : row_count_t'(1);
            rd_cmd_row_addr <= rd_cmd_start_addr_sum[REG_WIDTH-1:0];
            rd_pending_cmd_cross <= rd_base_addr[ADDR_LSB-1:0] != '0;
        end else if (rd_issue_active) begin
            case (rd_issue_phase)
                RD_ISSUE_LIMIT: begin
                    rd_plan_selected <= rd_plan_limited;
                    rd_issue_phase <= RD_ISSUE_COMMIT;
                end
                RD_ISSUE_COMMIT: begin
                    rd_arvalid_r <= rd_plan_has_rows;
                    rd_araddr_r <= rd_plan_addr;
                    rd_arlen_r <= 8'(rd_plan_selected - beat_count_t'(1));
                    rd_follow_addr <= rd_plan_next_addr_sum[REG_WIDTH-1:0];
                    rd_follow_beats <= rd_plan_remaining - rd_plan_selected;
                    rd_issue_phase <= RD_ISSUE_WAIT;
                end
                RD_ISSUE_WAIT: begin
                    if (rd_ar_hs) begin
                        rd_arvalid_r <= 1'b0;
                        rd_pending_cmd_cross <= 1'b0;
                        if (rd_issue_last_ar) begin
                            rd_issue_active <= 1'b0;
                            rd_issue_phase <= RD_ISSUE_IDLE;
                        end
                    end else if (!rd_arvalid_r && (!rd_unaligned_mode || rd_outstanding_cnt == '0) &&
                                 (rd_follow_beats != '0 || rd_cmd_row_cnt < rd_cfg_rows)) begin
                        rd_plan_addr <= rd_follow_beats != '0 ? rd_follow_addr :
                            {rd_cmd_row_addr[REG_WIDTH-1:ADDR_LSB], {ADDR_LSB{1'b0}}};
                        rd_plan_remaining <= rd_follow_beats != '0 ? rd_follow_beats : rd_next_row_beats;
                        rd_plan_has_rows <= 1'b1;
                        rd_issue_phase <= RD_ISSUE_LIMIT;
                        if (rd_follow_beats == '0) begin
                            rd_cmd_row_cnt <= rd_cmd_row_cnt + row_count_t'(1);
                            rd_cmd_row_addr <= rd_cmd_next_addr_sum[REG_WIDTH-1:0];
                        end
                        rd_pending_cmd_cross <= rd_follow_beats == '0 &&
                            rd_cmd_row_addr[ADDR_LSB-1:0] != '0;
                    end
                end
                default: rd_issue_phase <= RD_ISSUE_IDLE;
            endcase
        end
    end

    // Logical row progression uses the response head, independent of AR issue.
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            rd_rsp_row_cnt <= '0; rd_rsp_row_addr_direct <= '0; rd_rsp_from_context <= 1'b0;
            rd_rsp_beat_cnt <= '0; rd_rsp_prev_data <= '0;
            rd_done_r <= 1'b0; rd_response_error <= 1'b0; rd_completed_error <= 1'b0;
        end else begin
            rd_done_r <= rd_finish_beat;
            if (rd_finish_beat) begin
                rd_completed_error <= rd_response_error || m_axi_rresp[1];
                rd_response_error <= 1'b0;
                rd_rsp_row_cnt <= '0;
                rd_rsp_beat_cnt <= '0;
                rd_rsp_prev_data <= '0;
                // 同步 RAM 输出与来源标志同时更新，同址读写保留写入前的基地址。
                rd_rsp_from_context <= rd_context_count > context_count_t'(1);
                if (rd_context_count <= context_count_t'(1)) begin
                    rd_rsp_row_addr_direct <= rd_accept_issuer ? rd_base_addr : REG_WIDTH'(0);
                end
            end else if (!rd_active && rd_accept_issuer && rd_context_space_q) begin
                rd_rsp_row_cnt <= '0; rd_rsp_row_addr_direct <= rd_base_addr;
                rd_rsp_from_context <= 1'b0;
                rd_rsp_beat_cnt <= '0; rd_rsp_prev_data <= '0;
                rd_response_error <= 1'b0;
            end else if (rd_r_hs) begin
                if (m_axi_rresp[1]) rd_response_error <= 1'b1;
                rd_rsp_prev_data <= m_axi_rdata;
                if (rd_rsp_done) begin
                    rd_rsp_beat_cnt <= '0;
                    rd_rsp_row_cnt <= rd_rsp_row_cnt + row_count_t'(1);
                    rd_rsp_row_addr_direct <= rd_rsp_next_addr_sum[REG_WIDTH-1:0];
                    rd_rsp_from_context <= 1'b0;
                end else rd_rsp_beat_cnt <= rd_rsp_beat_cnt + beat_count_t'(1);
            end
        end
    end

    beat_count_t rd_rsp_logical_beat_comb;
    logic [$clog2(SIZE)-1:0] rd_rsp_col_base_comb;
    logic [BUS_WIDTH-1:0] rd_rsp_aligned_data_comb;
    logic [2*BUS_WIDTH-1:0] rd_rsp_joined_data;
    logic [2*BUS_WIDTH-1:0] rd_rsp_shifted_data;

    // 跨字读取先连接相邻两个总线字，再按字节偏移选择连续数据。
    assign rd_rsp_joined_data = {m_axi_rdata, rd_rsp_prev_data};
    assign rd_rsp_shifted_data = rd_rsp_joined_data >> {rd_rsp_offset, 3'b000};
    always_comb begin
        rd_rsp_logical_beat_comb = rd_head.linear_read ? beat_count_t'(rd_rsp_row_cnt) : rd_rsp_beat_cnt;
        rd_rsp_aligned_data_comb = m_axi_rdata;
        if (rd_rsp_cross) begin
            if (!rd_head.linear_read)
                rd_rsp_logical_beat_comb = rd_rsp_beat_cnt == '0 ? '0 : rd_rsp_beat_cnt - beat_count_t'(1);
            rd_rsp_aligned_data_comb = rd_rsp_shifted_data[BUS_WIDTH-1:0];
        end
    end
    assign rd_rsp_col_base_comb = rd_head.use_16bits ?
        rd_rsp_logical_beat_comb[$clog2(SIZE)-1:0] << $clog2(ELEM_PER_BEAT_S16) :
        rd_rsp_logical_beat_comb[$clog2(SIZE)-1:0] << $clog2(ELEM_PER_BEAT_S8);

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            rd_rsp_data_r <= '0; rd_rsp_row_r <= '0; rd_rsp_col_base_r <= '0;
            rd_rsp_valid_r <= 1'b0; rd_rsp_slot <= '0; rd_rsp_use_16bits <= 1'b0;
            rd_rsp_zp <= '0; rd_rsp_valid_cols <= '0; rd_response_tag <= '0;
            rd_rsp_lane_in_data_r <= '0;
        end else begin
            rd_rsp_valid_r <= rd_r_hs && rd_rsp_emit;
            if (rd_r_hs) begin
                rd_rsp_data_r <= rd_rsp_aligned_data_comb;
                rd_rsp_row_r <= rd_head.linear_read ? '0 : rd_rsp_row_cnt;
                rd_rsp_col_base_r <= rd_rsp_col_base_comb;
                rd_rsp_slot <= rd_head.slot;
                rd_rsp_use_16bits <= rd_head.use_16bits;
                rd_rsp_zp <= rd_head.zp;
                rd_rsp_valid_cols <= rd_head.valid_cols;
                rd_rsp_lane_in_data_r <= rd_rsp_lane_in_data_comb;
                rd_response_tag <= rd_head.tag;
            end
        end
    end

    assign wr_row = rd_rsp_row_r[$clog2(SIZE)-1:0];
    assign wr_col_base = rd_rsp_col_base_r;
    assign rd_raw_data = rd_rsp_data_r;
    assign rd_raw_valid = rd_rsp_valid_r;
    assign rd_raw_row = rd_rsp_row_r[$clog2(SIZE)-1:0];
    assign rd_raw_col_base = rd_rsp_col_base_r;
    for (genvar lane = 0; lane < BYTE_PER_BEAT; lane++) begin : g_unpack_lane
        logic [15:0] lane_data;
        (* use_dsp = "yes" *) logic [DATA_WIDTH-1:0] adjusted_data;
        logic lane_enabled;
        logic lane_in_tile;
        logic lane_in_data;

        // 列范围与返回数据在同一边沿保存，输出通道直接读取对应资格位。
        assign lane_in_data = rd_rsp_lane_in_data_r[lane];

        // 输入格式先选择统一的十六位数值，各通道共用一次零点相加。
        if (lane < ELEM_PER_BEAT_S16) begin : g_s8_s16
            assign lane_data = rd_rsp_use_16bits ? rd_rsp_data_r[16*lane+:16] :
                {{8{rd_rsp_data_r[8*lane+7]}}, rd_rsp_data_r[8*lane+:8]};
            assign lane_enabled = 1'b1;
        end else begin : g_s8
            assign lane_data = {{8{rd_rsp_data_r[8*lane+7]}}, rd_rsp_data_r[8*lane+:8]};
            assign lane_enabled = !rd_rsp_use_16bits;
        end
        assign adjusted_data = DATA_WIDTH'(lane_data) + DATA_WIDTH'(rd_rsp_zp[15:0]);
        if (REG_WIDTH > $clog2(SIZE) && lane < (1 << $clog2(SIZE))) begin : g_column_range
            localparam int p_column_width = $clog2(SIZE);
            logic [p_column_width:0] limit_low_delta;
            logic limit_high_zero;

            // 固定通道偏移先作用于有效长度，列地址直接参与低段比较。
            assign limit_low_delta = {1'b0, rd_head.valid_cols[p_column_width-1:0]} -
                (p_column_width+1)'(lane);
            assign limit_high_zero = !(|rd_head.valid_cols[REG_WIDTH-1:p_column_width]);
            // 有效输出已限定在当前块内，长度高段非零时覆盖全部块内通道。
            assign rd_rsp_lane_in_data_comb[lane] = !limit_high_zero ||
                (!limit_low_delta[p_column_width] &&
                 rd_rsp_col_base_comb < limit_low_delta[p_column_width-1:0]);
            if (lane < SIZE) begin : g_inside_tile
                assign lane_in_tile = REG_WIDTH'(rd_rsp_col_base_r) < REG_WIDTH'(SIZE-lane);
            end else begin : g_outside_tile
                assign lane_in_tile = 1'b0;
            end
        end else begin : g_column_range_general
            assign lane_in_tile = REG_WIDTH'(rd_rsp_col_base_r) + REG_WIDTH'(lane) < REG_WIDTH'(SIZE);
            assign rd_rsp_lane_in_data_comb[lane] =
                REG_WIDTH'(rd_rsp_col_base_comb + lane) < rd_head.valid_cols;
        end
        assign wr_valid[lane] = rd_rsp_valid_r && lane_enabled && lane_in_tile;
        assign wr_data[lane] = wr_valid[lane] && lane_in_data ? adjusted_data : '0;
    end

    // ---------------------------------------------------------------------
    // Write engine configuration/state
    // ---------------------------------------------------------------------
    logic [REG_WIDTH-1:0] wr_cfg_base_addr;
    logic [REG_WIDTH-1:0] wr_cfg_row_stride;
    write_row_count_t wr_cfg_rows;
    logic [7:0] wr_cfg_burst_len_m1;
    beat_count_t wr_cfg_cross_last;
    write_row_count_t wr_cmd_row_cnt;
    logic [REG_WIDTH-1:0] wr_cmd_row_addr_cur;
    beat_count_t wr_cmd_beat_cnt;
    write_row_count_t wr_data_row_cnt;
    logic [REG_WIDTH-1:0] wr_data_row_addr_cur;
    beat_count_t wr_beat_cnt;
    beat_count_t wr_segment_beat_cnt, wr_segment_last_beat;
    logic [BUS_WIDTH-1:0] wr_tail_data;
    logic [BUS_WIDTH/8-1:0] wr_tail_mask;
    logic wr_active;
    logic wr_data_active;
    logic [WR_OUTS_W-1:0] wr_outstanding_cnt;
    logic [WR_OUTS_W-1:0] wr_pending_data_cnt;
    // 相邻计数提前并行形成，握手条件仅选择已经计算的结果。
    (* keep = "true" *) logic [WR_OUTS_W-1:0] wr_pending_increment, wr_pending_decrement;
    logic [WR_OUTS_W-1:0] wr_pending_inc_bits, wr_pending_dec_bits;
    assign wr_pending_inc_bits[0] = ~wr_pending_data_cnt[0];
    assign wr_pending_dec_bits[0] = ~wr_pending_data_cnt[0];
    for (genvar bit_index = 1; bit_index < WR_OUTS_W; bit_index++) begin : g_pending_count
        assign wr_pending_inc_bits[bit_index] = wr_pending_data_cnt[bit_index] ^
            (&wr_pending_data_cnt[bit_index-1:0]);
        assign wr_pending_dec_bits[bit_index] = wr_pending_data_cnt[bit_index] ^
            !(|wr_pending_data_cnt[bit_index-1:0]);
    end
    always_comb begin
        case (^wr_pending_data_cnt)
            1'b0, 1'b1: begin
                wr_pending_increment = wr_pending_inc_bits;
                wr_pending_decrement = wr_pending_dec_bits;
            end
            default: begin
                wr_pending_increment = wr_pending_data_cnt + WR_OUTS_W'(1);
                wr_pending_decrement = wr_pending_data_cnt - WR_OUTS_W'(1);
            end
        endcase
    end
    logic wr_done_r;
    logic wr_error_r;
    logic wr_pending_cmd_cross;
    logic wr_abort;
    logic wr_abort_hold_valid;
    logic [BUS_WIDTH-1:0] wr_abort_hold_data;
    logic [BUS_WIDTH/8-1:0] wr_abort_hold_mask;

    (* use_dsp = "yes" *) logic [REG_WIDTH:0] wr_cmd_next_addr_sum;
    assign wr_cmd_next_addr_sum = {1'b0, wr_cmd_row_addr_cur} + {1'b0, wr_cfg_row_stride};
    (* use_dsp = "yes" *) logic [REG_WIDTH:0] wr_data_next_addr_sum;
    assign wr_data_next_addr_sum = {1'b0, wr_data_row_addr_cur} + {1'b0, wr_cfg_row_stride};

    // Preserve a stalled W beat across abort. Subsequent accepted AW bursts
    // finish with zero byte enables, independent of the producer's progress.
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            wr_abort <= 1'b0;
            wr_abort_hold_valid <= 1'b0;
            wr_abort_hold_data <= '0;
            wr_abort_hold_mask <= '0;
        end else begin
            if (abort) wr_abort <= 1'b1;
            else if (!wr_active) wr_abort <= 1'b0;
            if (abort && !wr_abort && m_axi_wvalid && !m_axi_wready) begin
                wr_abort_hold_valid <= 1'b1;
                wr_abort_hold_data <= m_axi_wdata;
                wr_abort_hold_mask <= m_axi_wstrb;
            end else if (wr_abort_hold_valid && wr_w_hs) begin
                wr_abort_hold_valid <= 1'b0;
            end
        end
    end

    assign wr_busy  = wr_active;
    assign wr_done  = wr_done_r;
    assign wr_error = wr_error_r;

    wire [BEAT_CNT_W-1:0] wr_cfg_burst_len_ext = BEAT_CNT_W'(wr_cfg_burst_len_m1);
    wire [ADDR_LSB-1:0] wr_cmd_row_offset = wr_cmd_row_addr_cur[ADDR_LSB-1:0];
    wire [ADDR_LSB-1:0] wr_row_offset = wr_data_row_addr_cur[ADDR_LSB-1:0];
    wire wr_row_cross = (wr_row_offset != '0);
    // 两种行结束位置分别比较，字节偏移仅选择已完成的比较结果。
    wire wr_plain_row_end = wr_beat_cnt == wr_cfg_burst_len_ext;
    localparam int unsigned p_row_equal_groups = (BEAT_CNT_W + 2) / 3;
    (* keep = "true" *) logic [p_row_equal_groups-1:0] wr_cross_equal_group;
    for (genvar group = 0; group < p_row_equal_groups; group++) begin : g_write_row_equal
        localparam int unsigned p_first = 3 * group;
        localparam int unsigned p_bits = BEAT_CNT_W - p_first < 3 ? BEAT_CNT_W - p_first : 3;
        assign wr_cross_equal_group[group] = wr_beat_cnt[p_first +: p_bits] ==
            wr_cfg_cross_last[p_first +: p_bits];
    end
    wire wr_cross_row_end = &wr_cross_equal_group;

    wire wr_row_end = wr_row_cross ? wr_cross_row_end : wr_plain_row_end;
    wire [BEAT_CNT_W-1:0] wr_cmd_row_beats = wr_cfg_burst_len_ext + beat_count_t'(1)
        + beat_count_t'(wr_cmd_row_offset != '0);
    (* use_dsp = "yes" *) wire [REG_WIDTH-1:0] wr_cmd_segment_addr =
        {wr_cmd_row_addr_cur[REG_WIDTH-1:ADDR_LSB], {ADDR_LSB{1'b0}}}
        + (REG_WIDTH'(wr_cmd_beat_cnt) << ADDR_LSB);
    (* use_dsp = "yes" *) wire [REG_WIDTH-1:0] wr_data_segment_addr =
        {wr_data_row_addr_cur[REG_WIDTH-1:ADDR_LSB], {ADDR_LSB{1'b0}}}
        + (REG_WIDTH'(wr_beat_cnt) << ADDR_LSB);
    logic [REG_WIDTH-1:0] wr_segment_addr [2];
    beat_count_t wr_remaining_last_beat [2];
    beat_count_t wr_selected_last_beat [2];

    assign wr_segment_addr[0] = wr_cmd_segment_addr;
    assign wr_segment_addr[1] = wr_data_segment_addr;
    assign wr_remaining_last_beat[0] = wr_cfg_burst_len_ext - wr_cmd_beat_cnt +
        beat_count_t'(wr_cmd_row_offset != '0);
    assign wr_remaining_last_beat[1] = wr_cfg_burst_len_ext - wr_beat_cnt + beat_count_t'(wr_row_cross);

    for (genvar segment = 0; segment < 2; segment++) begin : g_write_segment
        logic [12-ADDR_LSB-1:0] page_last_beat;
        beat_count_t boundary_last_beat;
        logic remaining_zero;
        logic remaining_within_page;
        logic remaining_within_burst;

        // 总线字边界上的页内地址取反，即为页内可传输的末拍编号。
        assign page_last_beat = ~wr_segment_addr[segment][11:ADDR_LSB];
        assign remaining_zero = &wr_remaining_last_beat[segment];
        assign remaining_within_page = 13'(wr_remaining_last_beat[segment]) <= 13'(page_last_beat);
        assign remaining_within_burst = wr_remaining_last_beat[segment] < beat_count_t'(MAX_BURST_BEATS);
        assign boundary_last_beat = 13'(page_last_beat) < 13'(MAX_BURST_BEATS-1) ?
            beat_count_t'(page_last_beat) : beat_count_t'(MAX_BURST_BEATS-1);

        // 直接选择末拍编号，并保留零剩余拍数时九位减一的回绕结果。
        always_comb begin
            wr_selected_last_beat[segment] = boundary_last_beat;
            if (remaining_zero) begin
                wr_selected_last_beat[segment] = '1;
            end else if (remaining_within_page && remaining_within_burst) begin
                wr_selected_last_beat[segment] = wr_remaining_last_beat[segment];
            end
        end
    end
    wire wr_tail_beat = wr_row_cross && wr_cross_row_end;
    wire wr_need_src_beat = !wr_tail_beat;
    wire wr_can_issue_aw = wr_active && !abort && !wr_abort &&
                            (wr_cmd_row_cnt < wr_cfg_rows) &&
                            (wr_outstanding_cnt < WR_OUTS_W'(WR_OUTS_MAX));
    wire wr_can_start_data = wr_active && !wr_data_active &&
                              (wr_pending_data_cnt != '0);
    wire wr_segment_done = wr_w_hs && m_axi_wlast;

    logic [BUS_WIDTH-1:0] wr_aligned_wdata;
    logic [BUS_WIDTH/8-1:0] wr_aligned_wstrb;
    logic [2*BUS_WIDTH-1:0] wr_shifted_data;
    logic [2*BYTE_PER_BEAT-1:0] wr_shifted_mask;

    // 同一字节旋转同时准备当前字和后续保留字，再按字节位置分配两部分。
    if (BYTE_PER_BEAT > 1 && BYTE_PER_BEAT == (1 << ADDR_LSB)) begin : g_write_rotation
        logic [2*BUS_WIDTH-1:0] repeated_data;
        logic [2*BYTE_PER_BEAT-1:0] repeated_mask;
        logic [BUS_WIDTH-1:0] rotated_data;
        logic [BYTE_PER_BEAT-1:0] rotated_mask;
        logic [2*BUS_WIDTH-1:0] selected_data;
        logic [2*BYTE_PER_BEAT-1:0] selected_mask;

        assign repeated_data = {src_wdata, src_wdata} << {wr_row_offset, 3'b000};
        assign repeated_mask = {src_wmask, src_wmask} << wr_row_offset;
        assign rotated_data = repeated_data[2*BUS_WIDTH-1:BUS_WIDTH];
        assign rotated_mask = repeated_mask[2*BYTE_PER_BEAT-1:BYTE_PER_BEAT];
        for (genvar lane = 0; lane < BYTE_PER_BEAT; lane++) begin : g_byte
            logic belongs_to_tail;
            assign belongs_to_tail = wr_row_offset > ADDR_LSB'(lane);
            assign selected_data[8*lane +: 8] = belongs_to_tail ? 8'b0 : rotated_data[8*lane +: 8];
            assign selected_data[BUS_WIDTH+8*lane +: 8] = belongs_to_tail ? rotated_data[8*lane +: 8] : 8'b0;
            assign selected_mask[lane] = belongs_to_tail ? 1'b0 : rotated_mask[lane];
            assign selected_mask[BYTE_PER_BEAT+lane] = belongs_to_tail ? rotated_mask[lane] : 1'b0;
        end
        always_comb begin
            case (^wr_row_offset)
                1'b0, 1'b1: begin
                    wr_shifted_data = selected_data;
                    wr_shifted_mask = selected_mask;
                end
                default: begin
                    wr_shifted_data = {{BUS_WIDTH{1'b0}}, src_wdata} << {wr_row_offset, 3'b000};
                    wr_shifted_mask = {{BYTE_PER_BEAT{1'b0}}, src_wmask} << wr_row_offset;
                end
            endcase
        end
    end else begin : g_write_shift
        assign wr_shifted_data = {{BUS_WIDTH{1'b0}}, src_wdata} << {wr_row_offset, 3'b000};
        assign wr_shifted_mask = {{BYTE_PER_BEAT{1'b0}}, src_wmask} << wr_row_offset;
    end

    always_comb begin
        wr_aligned_wdata = src_wdata;
        wr_aligned_wstrb = src_wmask;

        if (wr_row_cross) begin
            if (wr_tail_beat) begin
                wr_aligned_wdata = wr_tail_data;
                wr_aligned_wstrb = wr_tail_mask;
            end else begin
                wr_aligned_wdata =
                    wr_shifted_data[BUS_WIDTH-1:0] | wr_tail_data;
                wr_aligned_wstrb =
                    wr_shifted_mask[BYTE_PER_BEAT-1:0] | wr_tail_mask;
            end
        end
    end

    assign m_axi_awsize  = 3'(AXI_SIZE_VALUE);
    assign m_axi_awburst = 2'b01; // INCR
    assign m_axi_wdata   = wr_abort_hold_valid ? wr_abort_hold_data :
                          wr_abort ? '0 : wr_aligned_wdata;
    assign m_axi_wstrb   = wr_abort_hold_valid ? wr_abort_hold_mask :
                          wr_abort ? '0 : wr_aligned_wstrb;
    assign m_axi_wvalid  = wr_active && wr_data_active &&
                           (wr_abort || (wr_need_src_beat ? src_wvalid : 1'b1));
    assign m_axi_wlast   = (wr_segment_beat_cnt == wr_segment_last_beat);
    assign m_axi_bready  = wr_active;
    assign src_wready    = wr_active && wr_data_active && !wr_abort &&
                           wr_need_src_beat && m_axi_wready;

    wire last_wr_b = wr_b_hs && (wr_outstanding_cnt == WR_OUTS_W'(1)) &&
        (wr_cmd_row_cnt == wr_cfg_rows) && !m_axi_awvalid;
    wire wr_abort_drained = wr_abort && !m_axi_awvalid &&
        wr_outstanding_cnt == '0 && !wr_data_active && wr_pending_data_cnt == '0;

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            wr_done_r <= 1'b0;
        end else begin
            wr_done_r <= wr_active && (last_wr_b || wr_abort_drained);
        end
    end

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            wr_active           <= 1'b0;
            wr_cfg_base_addr    <= '0;
            wr_cfg_row_stride   <= '0;
            wr_cfg_rows         <= '0;
            wr_cfg_burst_len_m1 <= '0;
            wr_cfg_cross_last <= beat_count_t'(1);
            wr_error_r          <= 1'b0;
        end else if (wr_start && !wr_active && !abort) begin
            wr_active           <= 1'b1;
            wr_cfg_base_addr    <= wr_base_addr;
            wr_cfg_row_stride   <= wr_row_stride;
            wr_cfg_rows         <= write_row_count_t'(wr_rows_to_write);
            wr_cfg_burst_len_m1 <= wr_burst_len_m1;
            wr_cfg_cross_last <= beat_count_t'(wr_burst_len_m1) + beat_count_t'(1);
            wr_error_r          <= 1'b0;
        end else begin
            if (wr_b_hs && m_axi_bresp[1]) wr_error_r <= 1'b1;
            if (wr_done_r) wr_active <= 1'b0;
        end
    end

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            m_axi_awvalid <= 1'b0;
            m_axi_awaddr  <= '0;
            m_axi_awlen   <= '0;
            wr_cmd_row_cnt <= '0;
            wr_cmd_row_addr_cur <= '0;
            wr_cmd_beat_cnt <= '0;
            wr_data_row_cnt <= '0;
            wr_data_row_addr_cur <= '0;
            wr_beat_cnt   <= '0;
            wr_segment_beat_cnt <= '0;
            wr_segment_last_beat <= '0;
            wr_tail_data   <= '0;
            wr_tail_mask   <= '0;
            wr_data_active <= 1'b0;
            wr_outstanding_cnt <= '0;
            wr_pending_data_cnt <= '0;
            wr_pending_cmd_cross <= 1'b0;
        end else if (wr_start && !wr_active && !abort) begin
            m_axi_awvalid <= 1'b0;
            m_axi_awaddr  <= wr_base_addr;
            m_axi_awlen   <= wr_burst_len_m1;
            wr_cmd_row_cnt <= '0;
            wr_cmd_row_addr_cur <= wr_base_addr;
            wr_cmd_beat_cnt <= '0;
            wr_data_row_cnt <= '0;
            wr_data_row_addr_cur <= wr_base_addr;
            wr_beat_cnt   <= '0;
            wr_segment_beat_cnt <= '0;
            wr_segment_last_beat <= '0;
            wr_tail_data   <= '0;
            wr_tail_mask   <= '0;
            wr_data_active <= 1'b0;
            wr_outstanding_cnt <= '0;
            wr_pending_data_cnt <= '0;
            wr_pending_cmd_cross <= 1'b0;
        end else if (wr_active) begin
            if (wr_done_r) begin
                m_axi_awvalid <= 1'b0;
                wr_data_active <= 1'b0;
                wr_outstanding_cnt <= '0;
                wr_pending_data_cnt <= '0;
                wr_pending_cmd_cross <= 1'b0;
            end else begin
                if (wr_aw_hs) begin
                    m_axi_awvalid <= 1'b0;
                    if (wr_cmd_beat_cnt + beat_count_t'(m_axi_awlen) + beat_count_t'(1) == wr_cmd_row_beats) begin
                        wr_cmd_row_cnt <= wr_cmd_row_cnt + write_row_count_t'(1);
                        wr_cmd_row_addr_cur <= wr_cmd_next_addr_sum[REG_WIDTH-1:0];
                        wr_cmd_beat_cnt <= '0;
                    end else begin
                        wr_cmd_beat_cnt <= wr_cmd_beat_cnt + beat_count_t'(m_axi_awlen) + beat_count_t'(1);
                    end
                    wr_pending_cmd_cross <= 1'b0;
                end else if (!m_axi_awvalid && wr_can_issue_aw) begin
                    m_axi_awvalid <= 1'b1;
                    m_axi_awaddr  <= wr_cmd_segment_addr;
                    m_axi_awlen   <= 8'(wr_selected_last_beat[0]);
                    wr_pending_cmd_cross <= (wr_cmd_beat_cnt == '0) && (wr_cmd_row_offset != '0);
                end

                unique case ({wr_aw_hs, wr_b_hs})
                    2'b10: wr_outstanding_cnt <= wr_outstanding_cnt + 1'b1;
                    2'b01: wr_outstanding_cnt <= wr_outstanding_cnt - 1'b1;
                    default: wr_outstanding_cnt <= wr_outstanding_cnt;
                endcase

                // Accepted physical addresses and completed W bursts are
                // counted independently from logical row progress.
                unique case ({wr_aw_hs, wr_segment_done})
                    2'b10: wr_pending_data_cnt <= wr_pending_increment;
                    2'b01: wr_pending_data_cnt <= wr_pending_decrement;
                    default: wr_pending_data_cnt <= wr_pending_data_cnt;
                endcase

                if (wr_can_start_data) begin
                    wr_data_active <= 1'b1;
                    wr_segment_beat_cnt <= '0;
                    wr_segment_last_beat <= wr_selected_last_beat[1];
                end

                if (wr_w_hs) begin
                    if (wr_segment_done) begin
                        wr_data_active <= 1'b0;
                        wr_segment_beat_cnt <= '0;
                    end else begin
                        wr_segment_beat_cnt <= wr_segment_beat_cnt + beat_count_t'(1);
                    end
                    if (wr_need_src_beat && wr_row_cross) begin
                        wr_tail_data <= wr_shifted_data[2*BUS_WIDTH-1:BUS_WIDTH];
                        wr_tail_mask <= wr_shifted_mask[2*BYTE_PER_BEAT-1:BYTE_PER_BEAT];
                    end
                    if (wr_row_end) begin
                        wr_beat_cnt   <= '0;
                        wr_data_active <= 1'b0;
                        wr_data_row_cnt <= wr_data_row_cnt + write_row_count_t'(1);
                        wr_data_row_addr_cur <= wr_data_next_addr_sum[REG_WIDTH-1:0];
                        wr_tail_data   <= '0;
                        wr_tail_mask   <= '0;
                    end else begin
                        wr_beat_cnt <= wr_beat_cnt + beat_count_t'(1);
                    end
                end

            end
        end else begin
            m_axi_awvalid <= 1'b0;
            wr_cmd_row_cnt <= '0;
            wr_cmd_row_addr_cur <= '0;
            wr_cmd_beat_cnt <= '0;
            wr_data_row_cnt <= '0;
            wr_data_row_addr_cur <= '0;
            wr_beat_cnt   <= '0;
            wr_segment_beat_cnt <= '0;
            wr_segment_last_beat <= '0;
            wr_tail_data   <= '0;
            wr_tail_mask   <= '0;
            wr_data_active <= 1'b0;
            wr_outstanding_cnt <= '0;
            wr_pending_data_cnt <= '0;
            wr_pending_cmd_cross <= 1'b0;
        end
    end

endmodule
