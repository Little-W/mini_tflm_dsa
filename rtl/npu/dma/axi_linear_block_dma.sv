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
        logic [REG_WIDTH-1:0] base_addr;
        logic [REG_WIDTH-1:0] row_stride;
        row_count_t rows;
        logic [REG_WIDTH-1:0] valid_cols;
        logic [7:0] burst_len_m1;
        logic [RD_SLOT_W-1:0] slot;
        logic linear_read;
        logic use_16bits;
        logic signed [REG_WIDTH-1:0] zp;
        logic [RD_TAG_WIDTH-1:0] tag;
    } read_context_t;

    read_context_t rd_context [RD_CTX_DEPTH];
    read_context_t rd_head, rd_incoming;
    context_ptr_t rd_context_head, rd_context_tail;
    context_count_t rd_context_count;
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
    logic [REG_WIDTH-1:0] rd_rsp_row_addr_cur;
    beat_count_t rd_rsp_beat_cnt;
    logic [BUS_WIDTH-1:0] rd_rsp_prev_data, rd_rsp_data_r;
    row_count_t rd_rsp_row_r;
    logic [$clog2(SIZE)-1:0] rd_rsp_col_base_r;
    logic rd_rsp_valid_r;
    logic [RD_SLOT_W-1:0] rd_rsp_slot;
    logic rd_rsp_use_16bits;
    logic signed [REG_WIDTH-1:0] rd_rsp_zp;
    logic [REG_WIDTH-1:0] rd_rsp_valid_cols;
    logic rd_done_r, rd_response_error, rd_completed_error;
    wire rd_active = rd_context_count != '0;
    wire rd_accept_start = rd_start && !abort && rd_start_ready;
    wire rd_unaligned_mode = rd_cfg_base_addr[ADDR_LSB-1:0] != '0 ||
                             rd_cfg_row_stride[ADDR_LSB-1:0] != '0;
    wire [ADDR_LSB-1:0] rd_rsp_offset = rd_rsp_row_addr_cur[ADDR_LSB-1:0];
    wire rd_rsp_cross = rd_rsp_offset != '0;
    wire [BEAT_CNT_W-1:0] rd_rsp_aligned_last_beat =
        (rd_head.linear_read ? beat_count_t'(0) : beat_count_t'(rd_head.burst_len_m1)) +
        beat_count_t'(rd_rsp_cross);
    wire rd_rsp_emit = !rd_rsp_cross || rd_rsp_beat_cnt != '0;
    wire rd_rsp_done = rd_r_hs && rd_rsp_beat_cnt == rd_rsp_aligned_last_beat;
    wire rd_issue_last_ar = rd_issue_active && rd_ar_hs && rd_follow_beats == '0 &&
                            rd_cmd_row_cnt == rd_cfg_rows;

    function automatic context_ptr_t next_context(input context_ptr_t pointer);
        if (pointer == context_ptr_t'(RD_CTX_DEPTH-1)) return '0;
        return pointer + context_ptr_t'(1);
    endfunction

    always_comb begin
        rd_head = rd_context[rd_context_head];
        rd_incoming.base_addr = rd_base_addr;
        rd_incoming.row_stride = rd_row_stride;
        rd_incoming.rows = row_count_t'(rd_rows_to_read);
        rd_incoming.valid_cols = rd_valid_cols == '0 ? REG_WIDTH'(SIZE) : rd_valid_cols;
        rd_incoming.burst_len_m1 = rd_burst_len_m1;
        rd_incoming.slot = rd_slot_id;
        rd_incoming.linear_read = rd_linear_read_mode;
        rd_incoming.use_16bits = SUPPORT_16BIT && rd_use_16bits;
        rd_incoming.zp = rd_lhs_zp;
        rd_incoming.tag = rd_tag;
    end

    assign rd_finish_beat = rd_active && rd_rsp_done &&
                            rd_rsp_row_cnt == rd_head.rows - row_count_t'(1);
    assign rd_finish_tag = rd_head.tag;
    assign rd_start_ready = (!rd_issue_active || rd_issue_last_ar) &&
                            (rd_context_count < context_count_t'(RD_CTX_DEPTH) || rd_finish_beat);
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
        end else begin
            if (rd_accept_start) begin
                rd_context_tail <= next_context(rd_context_tail);
            end
            if (rd_finish_beat) rd_context_head <= next_context(rd_context_head);
            unique case ({rd_accept_start,rd_finish_beat})
                2'b10: rd_context_count <= rd_context_count + context_count_t'(1);
                2'b01: rd_context_count <= rd_context_count - context_count_t'(1);
                default: ;
            endcase
        end
    end

    // Payload fields are written before their entry becomes valid.
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            for (int i=0; i<RD_CTX_DEPTH; i++) rd_context[i].tag <= '0;
        end else if (rd_accept_start) begin
            rd_context[rd_context_tail] <= rd_incoming;
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

    function automatic beat_count_t read_segment_beats(
        input logic [REG_WIDTH-1:0] address, input beat_count_t remaining);
        logic [12:0] page_beats;
        beat_count_t result;
        begin
            page_beats = (13'd4096 - {1'b0,address[11:0]}) >> ADDR_LSB;
            result = remaining > beat_count_t'(MAX_BURST_BEATS) ?
                beat_count_t'(MAX_BURST_BEATS) : remaining;
            if (13'(result) > page_beats) result = beat_count_t'(page_beats);
            return result;
        end
    endfunction
    wire [REG_WIDTH-1:0] rd_first_ar_addr =
        {rd_base_addr[REG_WIDTH-1:ADDR_LSB], {ADDR_LSB{1'b0}}};
    wire [BEAT_CNT_W-1:0] rd_first_beats = beat_count_t'(1) +
        (rd_linear_read_mode ? beat_count_t'(0) : beat_count_t'(rd_burst_len_m1)) +
        beat_count_t'(rd_base_addr[ADDR_LSB-1:0] != '0);
    wire [REG_WIDTH-1:0] rd_contiguous_beats =
        REG_WIDTH'(row_count_t'(rd_rows_to_read)) * REG_WIDTH'(rd_first_beats);
    wire rd_merge_rows = rd_base_addr[ADDR_LSB-1:0] == '0 &&
        rd_row_stride == (REG_WIDTH'(rd_first_beats) << ADDR_LSB) &&
        row_count_t'(rd_rows_to_read) > row_count_t'(1) &&
        rd_contiguous_beats <= REG_WIDTH'(256);
    wire [BEAT_CNT_W-1:0] rd_first_span_beats =
        rd_merge_rows ? beat_count_t'(rd_contiguous_beats) : rd_first_beats;
    wire [BEAT_CNT_W-1:0] rd_first_segment =
        read_segment_beats(rd_first_ar_addr,rd_first_span_beats);

    // A command remains in the issuer until its final external AR handshake.
    // A following command can replace it on that edge while responses retain
    // the earlier command's independent context at the FIFO head.
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            rd_issue_active <= 1'b0;
            rd_arvalid_r <= 1'b0; rd_araddr_r <= '0; rd_arlen_r <= '0;
        end else if (rd_accept_start) begin
            rd_issue_active <= 1'b1;
            rd_cfg_base_addr <= rd_base_addr;
            rd_cfg_row_stride <= rd_row_stride;
            rd_cfg_rows <= row_count_t'(rd_rows_to_read);
            rd_cfg_burst_len_m1 <= rd_burst_len_m1;
            rd_cfg_linear_read <= rd_linear_read_mode;
            rd_arvalid_r <= row_count_t'(rd_rows_to_read) != '0;
            rd_araddr_r <= rd_first_ar_addr;
            rd_arlen_r <= 8'(rd_first_segment - beat_count_t'(1));
            rd_follow_addr <= rd_first_ar_addr + (REG_WIDTH'(rd_first_segment) << ADDR_LSB);
            rd_follow_beats <= rd_first_span_beats - rd_first_segment;
            rd_cmd_row_cnt <= rd_merge_rows ? row_count_t'(rd_rows_to_read) : row_count_t'(1);
            rd_cmd_row_addr <= rd_base_addr + rd_row_stride;
            rd_pending_cmd_cross <= rd_base_addr[ADDR_LSB-1:0] != '0;
        end else if (rd_issue_active) begin
            if (rd_ar_hs) begin
                rd_arvalid_r <= 1'b0;
                rd_pending_cmd_cross <= 1'b0;
                if (rd_issue_last_ar) rd_issue_active <= 1'b0;
            end else if (!rd_arvalid_r && (!rd_unaligned_mode || rd_outstanding_cnt == '0) &&
                         (rd_follow_beats != '0 || rd_cmd_row_cnt < rd_cfg_rows)) begin
                logic [ADDR_LSB-1:0] cmd_offset_cur;
                logic [REG_WIDTH-1:0] cmd_addr;
                beat_count_t cmd_beats, segment_beats;
                cmd_offset_cur = rd_cmd_row_addr[ADDR_LSB-1:0];
                cmd_addr = rd_follow_beats != '0 ? rd_follow_addr :
                    {rd_cmd_row_addr[REG_WIDTH-1:ADDR_LSB],{ADDR_LSB{1'b0}}};
                cmd_beats = rd_follow_beats != '0 ? rd_follow_beats :
                    beat_count_t'(1) + (rd_cfg_linear_read ? beat_count_t'(0) :
                    beat_count_t'(rd_cfg_burst_len_m1)) + beat_count_t'(cmd_offset_cur != '0);
                segment_beats = read_segment_beats(cmd_addr,cmd_beats);
                rd_arvalid_r <= 1'b1;
                rd_araddr_r <= cmd_addr;
                rd_arlen_r <= 8'(segment_beats - beat_count_t'(1));
                rd_follow_addr <= cmd_addr + (REG_WIDTH'(segment_beats) << ADDR_LSB);
                rd_follow_beats <= cmd_beats - segment_beats;
                if (rd_follow_beats == '0) begin
                    rd_cmd_row_cnt <= rd_cmd_row_cnt + row_count_t'(1);
                    rd_cmd_row_addr <= rd_cmd_row_addr + rd_cfg_row_stride;
                end
                rd_pending_cmd_cross <= rd_follow_beats == '0 && cmd_offset_cur != '0;
            end
        end
    end

    // Logical row progression uses the response head, independent of AR issue.
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            rd_rsp_row_cnt <= '0; rd_rsp_row_addr_cur <= '0;
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
                if (rd_context_count > context_count_t'(1))
                    rd_rsp_row_addr_cur <= rd_context[next_context(rd_context_head)].base_addr;
                else if (rd_accept_start) rd_rsp_row_addr_cur <= rd_base_addr;
                else rd_rsp_row_addr_cur <= '0;
            end else if (!rd_active && rd_accept_start) begin
                rd_rsp_row_cnt <= '0; rd_rsp_row_addr_cur <= rd_base_addr;
                rd_rsp_beat_cnt <= '0; rd_rsp_prev_data <= '0;
                rd_response_error <= 1'b0;
            end else if (rd_r_hs) begin
                if (m_axi_rresp[1]) rd_response_error <= 1'b1;
                rd_rsp_prev_data <= m_axi_rdata;
                if (rd_rsp_done) begin
                    rd_rsp_beat_cnt <= '0;
                    rd_rsp_row_cnt <= rd_rsp_row_cnt + row_count_t'(1);
                    rd_rsp_row_addr_cur <= rd_rsp_row_addr_cur + rd_head.row_stride;
                end else rd_rsp_beat_cnt <= rd_rsp_beat_cnt + beat_count_t'(1);
            end
        end
    end

    beat_count_t rd_rsp_logical_beat_comb;
    logic [$clog2(SIZE)-1:0] rd_rsp_col_base_comb;
    logic [BUS_WIDTH-1:0] rd_rsp_aligned_data_comb;
    always_comb begin
        rd_rsp_logical_beat_comb = rd_head.linear_read ? beat_count_t'(rd_rsp_row_cnt) : rd_rsp_beat_cnt;
        rd_rsp_aligned_data_comb = m_axi_rdata;
        if (rd_rsp_cross) begin
            if (!rd_head.linear_read)
                rd_rsp_logical_beat_comb = rd_rsp_beat_cnt == '0 ? '0 : rd_rsp_beat_cnt - beat_count_t'(1);
            rd_rsp_aligned_data_comb =
                (m_axi_rdata << ((BYTE_PER_BEAT - int'(rd_rsp_offset)) * 8)) |
                (rd_rsp_prev_data >> (int'(rd_rsp_offset) * 8));
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
    always_comb begin
        for (int i=0; i<BYTE_PER_BEAT; i++) begin wr_data[i]='0; wr_valid[i]=1'b0; end
        if (rd_rsp_valid_r) begin
            if (rd_rsp_use_16bits) begin
                for (int i=0; i<ELEM_PER_BEAT_S16; i++) begin
                    if (REG_WIDTH'(rd_rsp_col_base_r) + REG_WIDTH'(i) < REG_WIDTH'(SIZE)) begin
                        if (REG_WIDTH'(rd_rsp_col_base_r + i) < rd_rsp_valid_cols)
                            wr_data[i] = DATA_WIDTH'($signed(rd_rsp_data_r[i*16+:16]) + rd_rsp_zp[15:0]);
                        wr_valid[i] = 1'b1;
                    end
                end
            end else begin
                for (int i=0; i<ELEM_PER_BEAT_S8; i++) begin
                    if (REG_WIDTH'(rd_rsp_col_base_r) + REG_WIDTH'(i) < REG_WIDTH'(SIZE)) begin
                        if (REG_WIDTH'(rd_rsp_col_base_r + i) < rd_rsp_valid_cols)
                            wr_data[i] = DATA_WIDTH'($signed({{8{rd_rsp_data_r[i*8+7]}},rd_rsp_data_r[i*8+:8]}) + rd_rsp_zp[15:0]);
                        wr_valid[i] = 1'b1;
                    end
                end
            end
        end
    end

    // ---------------------------------------------------------------------
    // Write engine configuration/state
    // ---------------------------------------------------------------------
    logic [REG_WIDTH-1:0] wr_cfg_base_addr;
    logic [REG_WIDTH-1:0] wr_cfg_row_stride;
    write_row_count_t wr_cfg_rows;
    logic [7:0] wr_cfg_burst_len_m1;
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
    logic wr_done_r;
    logic wr_error_r;
    logic wr_pending_cmd_cross;
    logic wr_abort;
    logic wr_abort_hold_valid;
    logic [BUS_WIDTH-1:0] wr_abort_hold_data;
    logic [BUS_WIDTH/8-1:0] wr_abort_hold_mask;

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
    wire [BEAT_CNT_W-1:0] wr_aligned_last_beat =
        wr_cfg_burst_len_ext + (wr_row_cross ? BEAT_CNT_W'(1) : BEAT_CNT_W'(0));
    wire [BEAT_CNT_W-1:0] wr_cmd_row_beats = wr_cfg_burst_len_ext + beat_count_t'(1)
        + beat_count_t'(wr_cmd_row_offset != '0);
    wire [REG_WIDTH-1:0] wr_cmd_segment_addr =
        {wr_cmd_row_addr_cur[REG_WIDTH-1:ADDR_LSB], {ADDR_LSB{1'b0}}}
        + (REG_WIDTH'(wr_cmd_beat_cnt) << ADDR_LSB);
    wire [REG_WIDTH-1:0] wr_data_segment_addr =
        {wr_data_row_addr_cur[REG_WIDTH-1:ADDR_LSB], {ADDR_LSB{1'b0}}}
        + (REG_WIDTH'(wr_beat_cnt) << ADDR_LSB);
    function automatic beat_count_t write_segment_beats(
        input logic [REG_WIDTH-1:0] address, input beat_count_t remaining);
        logic [12:0] page_beats;
        beat_count_t result;
        begin
            page_beats = (13'd4096 - {1'b0,address[11:0]}) >> ADDR_LSB;
            result = remaining > beat_count_t'(MAX_BURST_BEATS) ?
                beat_count_t'(MAX_BURST_BEATS) : remaining;
            if (13'(result) > page_beats) result = beat_count_t'(page_beats);
            return result;
        end
    endfunction
    wire [BEAT_CNT_W-1:0] wr_cmd_segment_beats =
        write_segment_beats(wr_cmd_segment_addr, wr_cmd_row_beats-wr_cmd_beat_cnt);
    wire [BEAT_CNT_W-1:0] wr_data_segment_beats =
        write_segment_beats(wr_data_segment_addr,
                            wr_aligned_last_beat + beat_count_t'(1) - wr_beat_cnt);
    wire wr_tail_beat = wr_row_cross && (wr_beat_cnt == wr_aligned_last_beat);
    wire wr_need_src_beat = !wr_tail_beat;
    wire wr_can_issue_aw = wr_active && !abort && !wr_abort &&
                            (wr_cmd_row_cnt < wr_cfg_rows) &&
                            (wr_outstanding_cnt < WR_OUTS_W'(WR_OUTS_MAX));
    wire wr_can_start_data = wr_active && !wr_data_active &&
                              (wr_pending_data_cnt != '0);
    wire wr_segment_done = wr_w_hs && m_axi_wlast;

    logic [BUS_WIDTH-1:0] wr_aligned_wdata;
    logic [BUS_WIDTH/8-1:0] wr_aligned_wstrb;
    always_comb begin
        wr_aligned_wdata = src_wdata;
        wr_aligned_wstrb = src_wmask;

        if (wr_row_cross) begin
            if (wr_tail_beat) begin
                wr_aligned_wdata = wr_tail_data;
                wr_aligned_wstrb = wr_tail_mask;
            end else begin
                wr_aligned_wdata =
                    (src_wdata << (int'(wr_row_offset) * 8)) | wr_tail_data;
                wr_aligned_wstrb =
                    (src_wmask << int'(wr_row_offset)) | wr_tail_mask;
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
            wr_error_r          <= 1'b0;
        end else if (wr_start && !wr_active && !abort) begin
            wr_active           <= 1'b1;
            wr_cfg_base_addr    <= wr_base_addr;
            wr_cfg_row_stride   <= wr_row_stride;
            wr_cfg_rows         <= write_row_count_t'(wr_rows_to_write);
            wr_cfg_burst_len_m1 <= wr_burst_len_m1;
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
                        wr_cmd_row_addr_cur <= wr_cmd_row_addr_cur + wr_cfg_row_stride;
                        wr_cmd_beat_cnt <= '0;
                    end else begin
                        wr_cmd_beat_cnt <= wr_cmd_beat_cnt + beat_count_t'(m_axi_awlen) + beat_count_t'(1);
                    end
                    wr_pending_cmd_cross <= 1'b0;
                end else if (!m_axi_awvalid && wr_can_issue_aw) begin
                    m_axi_awvalid <= 1'b1;
                    m_axi_awaddr  <= wr_cmd_segment_addr;
                    m_axi_awlen   <= 8'(wr_cmd_segment_beats - beat_count_t'(1));
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
                    2'b10: wr_pending_data_cnt <= wr_pending_data_cnt + 1'b1;
                    2'b01: wr_pending_data_cnt <= wr_pending_data_cnt - 1'b1;
                    default: wr_pending_data_cnt <= wr_pending_data_cnt;
                endcase

                if (wr_can_start_data) begin
                    wr_data_active <= 1'b1;
                    wr_segment_beat_cnt <= '0;
                    wr_segment_last_beat <= wr_data_segment_beats - beat_count_t'(1);
                end

                if (wr_w_hs) begin
                    if (wr_segment_done) begin
                        wr_data_active <= 1'b0;
                        wr_segment_beat_cnt <= '0;
                    end else begin
                        wr_segment_beat_cnt <= wr_segment_beat_cnt + beat_count_t'(1);
                    end
                    if (wr_need_src_beat && wr_row_cross) begin
                        wr_tail_data <= src_wdata >> ((BYTE_PER_BEAT - int'(wr_row_offset)) * 8);
                        wr_tail_mask <= src_wmask >> (BYTE_PER_BEAT - int'(wr_row_offset));
                    end
                    if (wr_beat_cnt == wr_aligned_last_beat) begin
                        wr_beat_cnt   <= '0;
                        wr_data_active <= 1'b0;
                        wr_data_row_cnt <= wr_data_row_cnt + write_row_count_t'(1);
                        wr_data_row_addr_cur <= wr_data_row_addr_cur + wr_cfg_row_stride;
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
