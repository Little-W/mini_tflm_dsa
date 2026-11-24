/*
 * axi_dual_block_dma -- matrix/im2col AXI block DMA
 * ======================================================
 *
 * One shared read command path executes ordinary matrix blocks or implicit
 * im2col blocks. Both return the same signed-element/row/column/slot interface.
 * The image frontend, raw-input cache, ordinary-allocation guard and ordered
 * AXI read mux live here; loaders neither fetch input bytes nor own geometry.
 * Job configuration is accepted once, so image cache contents survive tiles.
 * The original linear read/write engine remains independent of im2col and
 * preserves GEMM's command/response and full-duplex write timing. The shared
 * read splitter repairs page-crossing rows without delaying legal bursts.
 */
`default_nettype none

module axi_dual_block_dma #(
    parameter int unsigned DATA_WIDTH   = 16,
    parameter int unsigned SIZE         = 16,
    parameter int unsigned BUS_WIDTH    = 32,
    parameter int unsigned DATA_LANES   = BUS_WIDTH / 8,
    parameter int unsigned REG_WIDTH    = 32,
    parameter int unsigned CACHE_BLOCKS = 4,
    parameter int unsigned DMA_MAX_BYTES = 256 * (BUS_WIDTH / 8),
    parameter int unsigned READ_OUTSTANDING = 4,
    parameter int unsigned WRITE_OUTSTANDING = READ_OUTSTANDING,
    parameter int unsigned RD_CONTEXT_DEPTH = 4,
    parameter int unsigned RD_TAG_WIDTH = 3,
    parameter int unsigned IM2COL_SIZE = SIZE,
    parameter int unsigned WINDOW_OUTSTANDING = 4,
    parameter int unsigned WINDOW_LANES = 4,
    parameter int unsigned CONV_CACHE_SETS = 128,
    parameter int unsigned CONV_CACHE_WAYS = 2,
    parameter int unsigned CONV_LINE_BYTES = 16,
    parameter int unsigned CONV_CACHE_POLICY = 3
) (
    input wire logic clk,
    input wire logic rst_n,
    input wire logic abort = 1'b0,

    // ---- Immutable job context; accepted only with all reads drained ----
    // Assert for every job, including GEMM (conv_enable=0). No read command may
    // be submitted on the same cycle. Existing non-Conv users may omit these.
    // Independent ordered window requests use destination tags and credits.
    input wire logic win_req_valid = 1'b0,
    output logic win_req_ready,
    input wire logic [31:0] win_req_p0 = '0, win_req_q0 = '0, win_req_cols = '0,
    input wire logic [1:0] win_req_tag = '0,
    output logic win_rsp_valid,
    input wire logic win_rsp_ready = 1'b1,
    output logic [1:0] win_rsp_tag,
    output logic [31:0] win_rsp_col,
    output logic signed [15:0] win_rsp_data[WINDOW_LANES],
    output logic [WINDOW_LANES-1:0] win_rsp_mask,
    output logic win_rsp_last,win_rsp_error,win_busy,

    input  wire logic conv_cfg_valid = 1'b0,
    output logic conv_cfg_ready,
    input  wire logic conv_enable = 1'b0,
    input  wire logic dma_range_enable = 1'b0,
    input  wire conv_im2col_pkg::conv_cfg_t conv_cfg = '0,
    input  wire logic [31:0] conv_sched_r = 32'd0,
    input  wire logic [31:0] conv_sched_groups = 32'd0,
    input  wire logic [31:0] conv_range_base [4] = '{default:'0},
    input  wire logic [32:0] conv_range_end [4] = '{default:'0},
    output logic conv_error, conv_busy,

    // ---- Read block command ----
    // Im2col returns rows_to_read by IM2COL_SIZE signed-16 elements. Padding
    // and reduction tail are explicit zero; no extra transpose is performed.
    input  wire logic rd_im2col = 1'b0,
    input  wire logic rd_wide_im2col = 1'b0,
    input  wire logic [31:0] rd_p0 = 32'd0,
    input  wire logic [31:0] rd_q0 = 32'd0,
    input  wire logic [31:0] rd_group = 32'd0,
    input  wire logic                                   rd_start,
    input  wire logic [RD_TAG_WIDTH-1:0]                 rd_tag = '0,
    output logic                                   rd_start_ready,
    output logic [RD_TAG_WIDTH-1:0]                 rd_response_tag,
    output logic [RD_TAG_WIDTH-1:0]                 rd_finish_tag,
    input  wire logic                                   rd_linear_read_mode,
    input  wire logic        [           REG_WIDTH-1:0] rd_base_addr,
    input  wire logic        [           REG_WIDTH-1:0] rd_row_stride,
    input  wire logic        [           REG_WIDTH-1:0] rd_rows_to_read,
    input  wire logic        [           REG_WIDTH-1:0] rd_valid_cols,
    input  wire logic        [                     7:0] rd_burst_len_m1,
    input  wire logic        [((CACHE_BLOCKS <= 1) ? 1 : $clog2(CACHE_BLOCKS))-1:0] rd_slot_id,
    input  wire logic                                   rd_use_16bits,
    input  wire logic signed [           REG_WIDTH-1:0] rd_lhs_zp,
    output logic                                   rd_busy,
    output logic                                   rd_done,
    output logic                                   rd_finish_beat,

    // ---- Write block command ----
    input  wire logic                            wr_start,
    input  wire logic [           REG_WIDTH-1:0] wr_base_addr,
    input  wire logic [           REG_WIDTH-1:0] wr_row_stride,
    input  wire logic [           REG_WIDTH-1:0] wr_rows_to_write,
    input  wire logic [                     7:0] wr_burst_len_m1,
    output logic                            wr_busy,
    output logic                            wr_done,

    // ---- Write data stream ----
    input  wire logic [  BUS_WIDTH-1:0] src_wdata,
    input  wire logic [BUS_WIDTH/8-1:0] src_wmask,
    input  wire logic                   src_wvalid,
    output logic                   src_wready,

    // ---- AXI4 master read address channel ----
    output logic                   m_axi_arvalid,
    input  wire logic                   m_axi_arready,
    output logic [  REG_WIDTH-1:0] m_axi_araddr,
    output logic [            7:0] m_axi_arlen,
    output logic [            2:0] m_axi_arsize,
    output logic [            1:0] m_axi_arburst,

    // ---- AXI4 master read data channel ----
    input  wire logic                   m_axi_rvalid,
    output logic                   m_axi_rready,
    input  wire logic [  BUS_WIDTH-1:0] m_axi_rdata,
    input  wire logic [            1:0] m_axi_rresp,
    input  wire logic                   m_axi_rlast,

    // ---- AXI4 master write address channel ----
    output logic                   m_axi_awvalid,
    input  wire logic                   m_axi_awready,
    output logic [  REG_WIDTH-1:0] m_axi_awaddr,
    output logic [            7:0] m_axi_awlen,
    output logic [            2:0] m_axi_awsize,
    output logic [            1:0] m_axi_awburst,

    // ---- AXI4 master write data channel ----
    output logic                   m_axi_wvalid,
    input  wire logic                   m_axi_wready,
    output logic [  BUS_WIDTH-1:0] m_axi_wdata,
    output logic [BUS_WIDTH/8-1:0] m_axi_wstrb,
    output logic                   m_axi_wlast,

    // ---- AXI4 master write response channel ----
    input  wire logic                   m_axi_bvalid,
    output logic                   m_axi_bready,
    input  wire logic [            1:0] m_axi_bresp,

    // ---- Read unpack output ----
    output logic        [((CACHE_BLOCKS <= 1) ? 1 : $clog2(CACHE_BLOCKS))-1:0] wr_slot,
    output logic        [        $clog2(SIZE)-1:0] wr_row,
    output logic        [        $clog2(SIZE)-1:0] wr_col_base,
    output logic signed [          DATA_WIDTH-1:0] wr_data      [DATA_LANES],
    output logic                                   wr_valid     [DATA_LANES],
    output logic                                   wr_use_16bits,

    // ---- Raw read stream for quant/bias-like users ----
    output logic [   BUS_WIDTH-1:0] rd_raw_data,
    output logic                    rd_raw_valid,
    output logic [$clog2(SIZE)-1:0] rd_raw_row,
    output logic [$clog2(SIZE)-1:0] rd_raw_col_base,

    output logic rd_error,
    output logic wr_error
);
    localparam int LANES = BUS_WIDTH / 8;
    localparam int SLOT_W = (CACHE_BLOCKS <= 1) ? 1 : $clog2(CACHE_BLOCKS);
    localparam int COL_W = $clog2(SIZE);
    localparam int CONV_CW = $clog2(IM2COL_SIZE);
    localparam int CONV_RW = $clog2(IM2COL_SIZE+1);
    localparam bit CONV_SUPPORTED = DATA_WIDTH >= 16 && (BUS_WIDTH == 32 || BUS_WIDTH == 64) &&
                                   REG_WIDTH == 32 && IM2COL_SIZE <= SIZE;

    logic job_conv, job_read_guard;
    logic cfg_fire;
    logic linear_start, linear_busy, linear_done, linear_finish, linear_error;
    logic linear_start_ready;
    logic [RD_TAG_WIDTH-1:0] linear_response_tag, linear_finish_tag, conv_tag_q;
    logic [SLOT_W-1:0] linear_slot;
    logic [COL_W-1:0] linear_row, linear_col;
    logic signed [DATA_WIDTH-1:0] linear_data [LANES];
    logic linear_valid [LANES];
    logic linear_use_16bits;

    logic linear_arvalid, linear_arready, linear_rvalid, linear_rready, linear_rlast;
    logic [REG_WIDTH-1:0] linear_araddr;
    logic [BUS_WIDTH-1:0] linear_rdata;
    logic [7:0] linear_arlen;
    logic [2:0] linear_arsize;
    logic [1:0] linear_arburst, linear_rresp;
    logic linear_awvalid, linear_awready, linear_wvalid, linear_wready, linear_wlast;
    logic linear_bvalid, linear_bready, write_guard_idle;
    logic [REG_WIDTH-1:0] linear_awaddr;
    logic [7:0] linear_awlen;
    logic [2:0] linear_awsize;
    logic [1:0] linear_awburst, linear_bresp;
    logic [BUS_WIDTH-1:0] linear_wdata;
    logic [BUS_WIDTH/8-1:0] linear_wstrb;
    logic guard_arvalid, guard_arready, guard_rvalid, guard_rready, guard_rlast;
    logic [REG_WIDTH-1:0] guard_araddr;
    logic [BUS_WIDTH-1:0] guard_rdata;
    logic [7:0] guard_arlen;
    logic [2:0] guard_arsize;
    logic [1:0] guard_arburst, guard_rresp;
    logic guard_idle, mux_idle;

    logic fe_cfg_ready, fe_tile_ready, fe_wr_valid, fe_done, fe_tile_error, fe_wr_last;
    logic fe_error, fe_busy;
    logic fe_output_valid, fe_output_ready, fe_output_window, fe_output_last;
    logic fe_matrix_output_valid;
    logic fe_input_ready, fe_output_drained, fe_window_error;
    logic [SLOT_W-1:0] fe_output_slot;
    logic [CONV_CW-1:0] fe_output_row, fe_output_col;
    logic signed [15:0] fe_output_data [WINDOW_LANES];
    logic [WINDOW_LANES-1:0] fe_output_mask;

    logic [SLOT_W-1:0] fe_slot;
    logic [CONV_CW-1:0] fe_row, fe_col;
    logic signed [15:0] fe_data [WINDOW_LANES];
    logic [WINDOW_LANES-1:0] fe_mask;
    logic fe_arvalid, fe_arready, fe_rvalid, fe_rready, fe_rlast;
    logic [31:0] fe_araddr;
    logic [BUS_WIDTH-1:0] fe_rdata;
    logic [7:0] fe_arlen;
    logic [2:0] fe_arsize;
    logic [1:0] fe_arburst, fe_rresp;

    // 普通 im2col 描述符在接收边沿保存，下一边沿起由前端接收。
    // 描述符完成表示矩阵数据已返回，后台填充由 busy 持续记录至全部结束。
    logic conv_active, conv_pending, conv_finished, conv_command_error, conv_wide;
    logic conv_done_r, conv_done_error, descriptor_error, command_im2col;
    logic [31:0] p0_q, q0_q, group_q;
    logic [CONV_RW-1:0] rows_q, cols_q;
    logic [SLOT_W-1:0] slot_q;
    logic win_frontend_valid,win_frontend_active,win_frontend_rsp_ready,win_queue_req_ready;
    logic [31:0] win_frontend_p0,win_frontend_q0,win_frontend_cols;
    logic win_cols_valid;
    logic [CONV_CW-1:0] win_response_col;
    logic frontend_i_tile_valid;
    logic [31:0] frontend_i_tile_p0, frontend_i_tile_q0, frontend_i_tile_group;
    logic [CONV_RW-1:0] frontend_i_tile_rows, frontend_i_tile_cols;
    logic [SLOT_W-1:0] frontend_i_tile_slot;

    assign win_rsp_col=32'(win_response_col);
    assign win_req_ready=win_queue_req_ready && !conv_cfg_valid && !rd_start;
    conv_window_queue #(.DEPTH(WINDOW_OUTSTANDING),.COL_W(CONV_CW),
        .WINDOW_LANES(WINDOW_LANES),.p_max_cols(IM2COL_SIZE),.p_frontend_outstanding(WINDOW_OUTSTANDING < 3 ? WINDOW_OUTSTANDING : 3)) u_window_queue (
        .clk,.rst_n,.configure(cfg_fire),
        .enable(CONV_SUPPORTED && job_conv && !conv_active && !conv_pending && !linear_busy && !fe_error),
        .req_valid(win_req_valid && !conv_cfg_valid && !rd_start),.req_ready(win_queue_req_ready),
        .req_p0(win_req_p0),.req_q0(win_req_q0),.req_cols(win_req_cols),.req_tag(win_req_tag),
        .rsp_valid(win_rsp_valid),.rsp_ready(win_rsp_ready),.rsp_tag(win_rsp_tag),
        .rsp_col(win_response_col),.rsp_data(win_rsp_data),.rsp_mask(win_rsp_mask),
        .rsp_last(win_rsp_last),.rsp_error(win_rsp_error),.busy(win_busy),
        .frontend_valid(win_frontend_valid),.frontend_active(win_frontend_active),.frontend_ready(fe_tile_ready),
        .frontend_p0(win_frontend_p0),.frontend_q0(win_frontend_q0),.frontend_cols(win_frontend_cols),
        .frontend_cols_valid(win_cols_valid),
        .frontend_rsp_valid(fe_output_valid && fe_output_window),.frontend_rsp_ready(win_frontend_rsp_ready),
        .frontend_rsp_col(fe_output_col),.frontend_rsp_data(fe_output_data),.frontend_rsp_mask(fe_output_mask),
        .frontend_rsp_last(fe_output_last),.frontend_error(fe_window_error));
    logic accept_read, accept_linear, accept_image, image_start_ready;
    logic configuration_available_q;
    logic win_payload_select;
    assign rd_busy = linear_busy || conv_active || fe_busy || fe_output_valid || win_busy || !guard_idle || !mux_idle;
    assign rd_done = linear_done || conv_done_r;
    // 线性命令保留最后返回拍的接收机会，图像命令在最后输出后完成。
    // 同一图像配置内可继续处理下一块，后台预取与下一块的读取重叠。
    assign rd_finish_beat = linear_finish || conv_done_r;
    assign image_start_ready = !conv_cfg_valid && !conv_active && !conv_pending &&
        (!linear_busy || linear_finish) && !win_busy && (!fe_busy || job_conv);
    // 切换至线性读取前，先排空图像前端及其物理读取通道。
    assign rd_start_ready = rd_im2col ? image_start_ready :
        (!conv_cfg_valid && linear_start_ready && !conv_active && !conv_pending &&
         !fe_busy && !fe_output_valid && !win_busy && (!job_conv || (guard_idle && mux_idle)));
    assign accept_linear = rd_start && !abort && !rd_im2col && rd_start_ready;
    assign accept_image = rd_start && !abort && rd_im2col && image_start_ready;
    assign accept_read = accept_linear || accept_image;
    // 窗口归属与完成状态决定返回标签，选择保持无效周期的数据行为。
    assign rd_response_tag = (fe_matrix_output_valid || conv_done_r) ?
      conv_tag_q : linear_response_tag;
    assign rd_finish_tag = linear_finish ? linear_finish_tag : conv_tag_q;
    assign linear_start = accept_linear;
    // 普通描述符只在窗口队列为空时接收，等待前端期间禁止窗口入队。
    // 队列占用状态直接选择已准备字段，最终返回周期只控制该项是否有效。
    assign win_payload_select=win_busy;
    assign frontend_i_tile_valid = conv_pending || win_frontend_valid;
    assign frontend_i_tile_p0 = win_payload_select ? win_frontend_p0 : p0_q;
    assign frontend_i_tile_q0 = win_payload_select ? win_frontend_q0 : q0_q;
    assign frontend_i_tile_rows = win_payload_select ? CONV_RW'(1) : rows_q;
    assign frontend_i_tile_cols = win_payload_select ?
        (win_cols_valid ? CONV_RW'(win_frontend_cols) : CONV_RW'(IM2COL_SIZE+1)) : cols_q;
    assign frontend_i_tile_slot = slot_q;
    assign frontend_i_tile_group = group_q;
    assign rd_error = linear_done ? linear_error :
                      conv_done_r ? conv_done_error :
                      command_im2col ? (conv_command_error || fe_error) : linear_error;
    // 读通道完全排空后保存配置接收资格；新工作接收时立即清除。
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) configuration_available_q <= 1'b0;
        else if (cfg_fire || accept_read || (win_req_valid && win_req_ready))
            configuration_available_q <= 1'b0;
        else configuration_available_q <= !rd_busy && !rd_done && fe_cfg_ready;
    end
    assign conv_cfg_ready = configuration_available_q;
    assign cfg_fire = conv_cfg_valid && conv_cfg_ready;
`ifdef NPU_SIM_ASSERT
    always @(posedge clk) if (rst_n && conv_cfg_ready)
        assert(!rd_busy && !rd_done && fe_cfg_ready);
`endif
    assign conv_error = descriptor_error || (job_conv && fe_error);
    assign conv_busy = conv_active || fe_busy || fe_output_valid || win_busy;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            job_conv <= 1'b0; job_read_guard <= 1'b0; conv_active <= 1'b0; conv_pending <= 1'b0;
            conv_finished <= 1'b0; conv_command_error <= 1'b0;
            conv_wide <= 1'b0;
            conv_done_r <= 1'b0; conv_done_error <= 1'b0;
            descriptor_error <= 1'b0; command_im2col <= 1'b0;
            conv_tag_q <= '0;
            p0_q <= '0; q0_q <= '0; group_q <= '0; rows_q <= '0; cols_q <= '0; slot_q <= '0;
        end else begin
            conv_done_r <= 1'b0;
            if (cfg_fire) begin
                job_conv <= conv_enable && CONV_SUPPORTED;
                // 读取保护和请求复用共用已保存的模式条件，返回路径直接使用寄存位。
                job_read_guard <= (conv_enable && CONV_SUPPORTED) || dma_range_enable;
                descriptor_error <= conv_enable && !CONV_SUPPORTED;
                conv_command_error <= 1'b0;
            end
            if (accept_read) begin
                command_im2col <= rd_im2col;
                if (rd_im2col) begin
                    conv_wide <= rd_wide_im2col && DATA_LANES >= WINDOW_LANES;
                    conv_tag_q <= rd_tag;
                    conv_active <= 1'b1;
                    p0_q <= rd_p0; q0_q <= rd_q0; group_q <= rd_group;
                    rows_q <= CONV_RW'(rd_rows_to_read); slot_q <= rd_slot_id;
                    cols_q <= (rd_valid_cols > 0 && rd_valid_cols <= REG_WIDTH'(IM2COL_SIZE)) ?
                              CONV_RW'(rd_valid_cols) : CONV_RW'(IM2COL_SIZE);
                    if (!CONV_SUPPORTED || !job_conv || fe_error ||
                        rd_rows_to_read == 0 || rd_rows_to_read > REG_WIDTH'(IM2COL_SIZE)) begin
                        conv_pending <= 1'b0; conv_finished <= 1'b1;
                        conv_command_error <= 1'b1; descriptor_error <= 1'b1;
                    end else begin
                        conv_pending <= 1'b1; conv_finished <= 1'b0;
                        conv_command_error <= 1'b0;
                    end
                end
            end
            if (conv_pending && fe_tile_ready) conv_pending <= 1'b0;
            if (conv_active && (fe_done || fe_tile_error || fe_error)) begin
                conv_finished <= 1'b1;
                conv_command_error <= conv_command_error || fe_tile_error || fe_error;
            end
            if (conv_active && fe_output_drained &&
                (conv_finished || fe_done || fe_tile_error || fe_error)) begin
                conv_active <= 1'b0; conv_pending <= 1'b0; conv_finished <= 1'b0;
                conv_done_r <= 1'b1;
                conv_done_error <= conv_command_error || fe_error || fe_tile_error;
            end
        end
    end

    // 图像输出在同一边沿保存数据与位置，普通矩阵和独立窗口共用这一寄存边界。
    // 独立窗口暂停接收时保持整项内容；接收当前项的同时可保存下一项。
    assign fe_output_ready = !fe_output_window || win_frontend_rsp_ready;
    assign fe_input_ready = !fe_output_valid || fe_output_ready;
    assign fe_output_drained = !fe_output_valid || fe_output_ready;
    // 已保存的数据先完成发送，随后窗口队列按描述符顺序返回终止错误。
    assign fe_window_error = (fe_error || fe_tile_error) && !fe_output_valid;
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            fe_output_valid <= 1'b0;
            fe_output_window <= 1'b0;
            fe_matrix_output_valid <= 1'b0;
        end else if (fe_input_ready) begin
            fe_output_valid <= fe_wr_valid;
            // 响应种类与数据同时保存，矩阵返回可直接使用已寄存的路由资格。
            if (fe_wr_valid) begin
                fe_output_window <= win_frontend_active;
                fe_matrix_output_valid <= !win_frontend_active;
            end else begin
                fe_matrix_output_valid <= fe_wr_valid && !fe_output_window;
            end
        end
    end
    always_ff @(posedge clk) begin
        if (fe_wr_valid && fe_input_ready) begin
            fe_output_slot <= fe_slot;
            fe_output_row <= fe_row;
            fe_output_col <= fe_col;
            fe_output_mask <= fe_mask;
            fe_output_last <= fe_wr_last;
            for (int lane = 0; lane < WINDOW_LANES; lane++) begin
                fe_output_data[lane] <= fe_data[lane];
            end
        end
    end

    // 线性读取的末次输出与图像输出均由各自有效信号选择。
    always_comb begin
        wr_slot = linear_slot; wr_row = linear_row; wr_col_base = linear_col;
        if (conv_done_r) wr_slot = slot_q;
        wr_use_16bits = linear_use_16bits;
        // 线性 DMA 维持外部总线宽度，窗口命中可向矩阵端返回更多元素。
        for (int i=0; i<DATA_LANES; i++) begin
            wr_data[i] = '0; wr_valid[i] = 1'b0;
            if (i<LANES) begin
                wr_data[i] = linear_data[i]; wr_valid[i] = linear_valid[i];
            end
        end
        if (fe_matrix_output_valid) begin
            wr_slot = fe_output_slot; wr_row = COL_W'(fe_output_row); wr_col_base = COL_W'(fe_output_col);
            wr_use_16bits = 1'b1;
            for (int i=0; i<DATA_LANES; i++) begin
                wr_data[i] = '0; wr_valid[i] = 1'b0;
                if (i<WINDOW_LANES) begin
                    wr_data[i] = DATA_WIDTH'($signed(fe_output_data[i]));
                    wr_valid[i] = fe_output_mask[i];
                end
            end
        end
    end

    axi_linear_block_dma #(
        .DMA_MAX_BYTES(DMA_MAX_BYTES),
        .DATA_WIDTH(DATA_WIDTH), .SIZE(SIZE), .BUS_WIDTH(BUS_WIDTH),
        .REG_WIDTH(REG_WIDTH), .CACHE_BLOCKS(CACHE_BLOCKS),
        .READ_OUTSTANDING(READ_OUTSTANDING), .WRITE_OUTSTANDING(WRITE_OUTSTANDING),
        .RD_CONTEXT_DEPTH(RD_CONTEXT_DEPTH), .RD_TAG_WIDTH(RD_TAG_WIDTH)
    ) u_linear (
        .clk, .rst_n, .abort, .rd_start(linear_start), .rd_linear_read_mode,
        .rd_tag, .rd_start_ready(linear_start_ready),
        .rd_response_tag(linear_response_tag), .rd_finish_tag(linear_finish_tag),
        .rd_base_addr, .rd_row_stride, .rd_rows_to_read, .rd_valid_cols,
        .rd_burst_len_m1, .rd_slot_id, .rd_use_16bits, .rd_lhs_zp,
        .rd_busy(linear_busy), .rd_done(linear_done), .rd_finish_beat(linear_finish),
        .rd_error(linear_error),
        .wr_start, .wr_base_addr, .wr_row_stride, .wr_rows_to_write,
        .wr_burst_len_m1, .wr_busy, .wr_done, .wr_error,
        .src_wdata, .src_wmask, .src_wvalid, .src_wready,
        .m_axi_arvalid(linear_arvalid), .m_axi_arready(linear_arready),
        .m_axi_araddr(linear_araddr), .m_axi_arlen(linear_arlen),
        .m_axi_arsize(linear_arsize), .m_axi_arburst(linear_arburst),
        .m_axi_rvalid(linear_rvalid), .m_axi_rready(linear_rready),
        .m_axi_rdata(linear_rdata), .m_axi_rresp(linear_rresp), .m_axi_rlast(linear_rlast),
        .m_axi_awvalid(linear_awvalid), .m_axi_awready(linear_awready),
        .m_axi_awaddr(linear_awaddr), .m_axi_awlen(linear_awlen),
        .m_axi_awsize(linear_awsize), .m_axi_awburst(linear_awburst),
        .m_axi_wvalid(linear_wvalid), .m_axi_wready(linear_wready),
        .m_axi_wdata(linear_wdata), .m_axi_wstrb(linear_wstrb), .m_axi_wlast(linear_wlast),
        .m_axi_bvalid(linear_bvalid), .m_axi_bready(linear_bready), .m_axi_bresp(linear_bresp),
        .wr_slot(linear_slot), .wr_row(linear_row), .wr_col_base(linear_col),
        .wr_data(linear_data), .wr_valid(linear_valid), .wr_use_16bits(linear_use_16bits),
        .rd_raw_data, .rd_raw_valid, .rd_raw_row, .rd_raw_col_base
    );

    logic buffered_wvalid, buffered_wready, buffered_wlast;
    logic [BUS_WIDTH-1:0] buffered_wdata;
    logic [BUS_WIDTH/8-1:0] buffered_wstrb;
    logic write_guard_core_idle;

    // 写数据和字节使能一起保存，源端就绪只由本地寄存容量决定。
    dma_register_buffer #(.p_width(BUS_WIDTH+BUS_WIDTH/8+1)) u_write_data_buffer (
        .clk, .rst_n,
        .i_valid(linear_wvalid), .o_ready(linear_wready),
        .i_data({linear_wdata,linear_wstrb,linear_wlast}),
        .o_valid(buffered_wvalid), .i_ready(buffered_wready),
        .o_data({buffered_wdata,buffered_wstrb,buffered_wlast})
    );
    assign write_guard_idle = write_guard_core_idle && !buffered_wvalid;

    axi_write_page_guard #(.ADDR_W(REG_WIDTH), .DATA_W(BUS_WIDTH),
        .WRITE_OUTSTANDING(WRITE_OUTSTANDING)) u_write_guard (
        .clk, .rst_n,
        .s_awvalid(linear_awvalid), .s_awready(linear_awready),
        .s_awaddr(linear_awaddr), .s_awlen(linear_awlen),
        .s_awsize(linear_awsize), .s_awburst(linear_awburst),
        .s_wvalid(buffered_wvalid), .s_wready(buffered_wready),
        .s_wdata(buffered_wdata), .s_wstrb(buffered_wstrb), .s_wlast(buffered_wlast),
        .s_bvalid(linear_bvalid), .s_bready(linear_bready), .s_bresp(linear_bresp),
        .m_awvalid(m_axi_awvalid), .m_awready(m_axi_awready),
        .m_awaddr(m_axi_awaddr), .m_awlen(m_axi_awlen),
        .m_awsize(m_axi_awsize), .m_awburst(m_axi_awburst),
        .m_wvalid(m_axi_wvalid), .m_wready(m_axi_wready),
        .m_wdata(m_axi_wdata), .m_wstrb(m_axi_wstrb), .m_wlast(m_axi_wlast),
        .m_bvalid(m_axi_bvalid), .m_bready(m_axi_bready), .m_bresp(m_axi_bresp),
        .idle(write_guard_core_idle)
    );

    generate if (CONV_SUPPORTED) begin : g_im2col
        conv_im2col_frontend #(
            .BUS_WIDTH(BUS_WIDTH),.DMA_MAX_BYTES(DMA_MAX_BYTES),
            .SIZE(IM2COL_SIZE), .SLOT_W(SLOT_W), .LANES(WINDOW_LANES),
            .CACHE_SETS(CONV_CACHE_SETS), .CACHE_WAYS(CONV_CACHE_WAYS),
            .LINE_BYTES(CONV_LINE_BYTES), .CACHE_POLICY(CONV_CACHE_POLICY),
            .REGISTER_DESCRIPTOR(1'b0),
            .REGISTER_ROW_ADDRESS(1'b0),
            .REGISTER_CACHE_REQUEST(1'b0),
            .CACHE_RESPONSE_DEPTH(1)
        ) u_frontend (
            .clk, .rst_n, .cfg_valid(cfg_fire && conv_enable), .cfg_ready(fe_cfg_ready),
            .cfg(conv_cfg), .cfg_sched_r(conv_sched_r), .cfg_sched_groups(conv_sched_groups),
            .tile_valid(frontend_i_tile_valid), .tile_ready(fe_tile_ready),
            .tile_p0(frontend_i_tile_p0), .tile_q0(frontend_i_tile_q0),
            .tile_rows(frontend_i_tile_rows), .tile_cols(frontend_i_tile_cols),
            .tile_slot(frontend_i_tile_slot), .tile_group(frontend_i_tile_group),
            .tile_narrow(!win_payload_select && !conv_wide),
            .wr_valid(fe_wr_valid), .wr_ready(fe_input_ready), .wr_slot(fe_slot),
            .wr_row(fe_row), .wr_col(fe_col), .wr_data(fe_data), .wr_mask(fe_mask),
            .tile_done(fe_done), .tile_error(fe_tile_error), .error(fe_error), .busy(fe_busy), .wr_last(fe_wr_last),
            .arvalid(fe_arvalid), .arready(fe_arready), .araddr(fe_araddr), .arlen(fe_arlen),
            .arsize(fe_arsize), .arburst(fe_arburst), .rvalid(fe_rvalid), .rready(fe_rready),
            .rdata(fe_rdata), .rresp(fe_rresp), .rlast(fe_rlast)
        );
        // Conv's ordinary matrix reads also need allocation-tail clipping.
        // The im2col span reader already emits exact legal byte/word transfers.
        logic read_mux_i_arvalid, read_mux_o_arvalid;
        logic buffered_arvalid, buffered_arready, read_guard_core_idle;
        logic [REG_WIDTH-1:0] buffered_araddr;
        logic [7:0] buffered_arlen;
        logic [2:0] buffered_arsize;
        logic [1:0] buffered_arburst;

        // 完整读地址先进入寄存队列，分配范围和页边界检查从寄存输出开始。
        dma_register_buffer #(.p_width(REG_WIDTH+13)) u_read_address_buffer (
            .clk, .rst_n,
            .i_valid(linear_arvalid), .o_ready(linear_arready),
            .i_data({linear_araddr,linear_arlen,linear_arsize,linear_arburst}),
            .o_valid(buffered_arvalid), .i_ready(buffered_arready),
            .o_data({buffered_araddr,buffered_arlen,buffered_arsize,buffered_arburst})
        );
        assign guard_idle = read_guard_core_idle && !buffered_arvalid;

        conv_axi_read_guard #(.ADDR_W(REG_WIDTH), .DATA_W(BUS_WIDTH),
            .SPLIT_GEMM_4K(1'b1), .READ_OUTSTANDING(READ_OUTSTANDING)) u_read_guard (
            .clk, .rst_n, .enable(job_read_guard), .cfg_valid(cfg_fire),
            .cfg_base(conv_range_base), .cfg_end(conv_range_end),
            .s_arvalid(buffered_arvalid), .s_arready(buffered_arready),
            .s_araddr(buffered_araddr), .s_arlen(buffered_arlen),
            .s_arsize(buffered_arsize), .s_arburst(buffered_arburst),
            .s_rvalid(linear_rvalid), .s_rready(linear_rready),
            .s_rdata(linear_rdata), .s_rresp(linear_rresp), .s_rlast(linear_rlast),
            .m_arvalid(guard_arvalid), .o_arb_arvalid(read_mux_i_arvalid), .m_arready(guard_arready),
            .m_araddr(guard_araddr), .m_arlen(guard_arlen),
            .m_arsize(guard_arsize), .m_arburst(guard_arburst),
            .m_rvalid(guard_rvalid), .m_rready(guard_rready),
            .m_rdata(guard_rdata), .m_rresp(guard_rresp), .m_rlast(guard_rlast),
            .idle(read_guard_core_idle)
        );
        // 保护模式的请求参与通道仲裁，直通模式的地址有效信号直接送往总线。
        assign m_axi_arvalid = job_read_guard ? read_mux_o_arvalid : guard_arvalid;
        conv_axi_read_mux #(.ADDR_W(REG_WIDTH), .DATA_W(BUS_WIDTH)) u_read_mux (
            .clk, .rst_n, .enable(job_read_guard),
            .a_arvalid(read_mux_i_arvalid), .a_arready(guard_arready),
            .a_araddr(guard_araddr), .a_arlen(guard_arlen),
            .a_arsize(guard_arsize), .a_arburst(guard_arburst),
            .a_rvalid(guard_rvalid), .a_rready(guard_rready),
            .a_rdata(guard_rdata), .a_rresp(guard_rresp), .a_rlast(guard_rlast),
            .b_arvalid(fe_arvalid), .b_arready(fe_arready),
            .b_araddr(fe_araddr), .b_arlen(fe_arlen), .b_arsize(fe_arsize), .b_arburst(fe_arburst),
            .b_rvalid(fe_rvalid), .b_rready(fe_rready),
            .b_rdata(fe_rdata), .b_rresp(fe_rresp), .b_rlast(fe_rlast),
            .m_arvalid(read_mux_o_arvalid), .m_arready(m_axi_arready),
            .m_araddr(m_axi_araddr), .m_arlen(m_axi_arlen),
            .m_arsize(m_axi_arsize), .m_arburst(m_axi_arburst),
            .m_rvalid(m_axi_rvalid), .m_rready(m_axi_rready),
            .m_rdata(m_axi_rdata), .m_rresp(m_axi_rresp), .m_rlast(m_axi_rlast),
            .idle(mux_idle)
        );
    end else begin : g_linear_only
        assign fe_cfg_ready=1'b1; assign fe_tile_ready=1'b0;
        assign fe_wr_valid=1'b0; assign fe_wr_last=1'b0; assign fe_done=1'b0; assign fe_tile_error=1'b0;
        assign fe_error=1'b0; assign fe_busy=1'b0;
        assign fe_slot='0; assign fe_row='0; assign fe_col='0;
        assign fe_mask='0;
        for (genvar lane=0;lane<WINDOW_LANES;lane++) begin : g_empty_window_data
            assign fe_data[lane]='0;
        end
        assign guard_idle=1'b1; assign mux_idle=1'b1;
        assign guard_arvalid=linear_arvalid; assign linear_arready=guard_arready;
        assign guard_araddr=linear_araddr; assign guard_arlen=linear_arlen;
        assign guard_arsize=linear_arsize; assign guard_arburst=linear_arburst;
        assign linear_rvalid=guard_rvalid; assign guard_rready=linear_rready;
        assign linear_rdata=guard_rdata; assign linear_rresp=guard_rresp;
        assign linear_rlast=guard_rlast;
        assign m_axi_arvalid=guard_arvalid; assign guard_arready=m_axi_arready;
        assign m_axi_araddr=guard_araddr; assign m_axi_arlen=guard_arlen;
        assign m_axi_arsize=guard_arsize; assign m_axi_arburst=guard_arburst;
        assign guard_rvalid=m_axi_rvalid; assign m_axi_rready=guard_rready;
        assign guard_rdata=m_axi_rdata; assign guard_rresp=m_axi_rresp;
        assign guard_rlast=m_axi_rlast;
    end endgenerate

`ifdef NPU_SIM_ASSERT
    initial forever @(posedge clk) if (rst_n) begin
        if (cfg_fire) assert(!rd_start && !rd_busy && !win_busy)
            else $error("DMA job configuration requires all reads to complete");
        if (accept_read && rd_im2col) assert(!linear_busy || linear_finish)
            else $error("Image command requires ordinary reads to complete");
        if (fe_wr_valid) begin
            assert((conv_active && command_im2col) || win_frontend_active);
            assert(!(conv_active && win_frontend_active));
            for (int i=0; i<LANES; i++) assert(!linear_valid[i]);
        end
        if (fe_output_valid) begin
            assert(fe_output_window ? win_frontend_active : conv_active);
            assert(!conv_cfg_ready);
            if (!fe_output_window) begin
                for (int lane = 0; lane < LANES; lane++) assert(!linear_valid[lane]);
            end
        end
        if (conv_done_r) assert(!fe_output_valid || fe_output_window);
        assert(!(linear_done && conv_done_r));
        if (!wr_busy) assert(write_guard_idle);
    end
`endif
endmodule

`default_nettype wire
