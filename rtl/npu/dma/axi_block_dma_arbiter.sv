/*
 * axi_block_dma_arbiter -- AXI-native DMA front-end for NPU clients
 * ================================================================
 *
 * Read clients (IA/kernel/bias/quant) share the AXI read engine through a
 * small priority arbiter.  The OA writer owns the AXI write engine directly.
 * This preserves the existing loader-side handshake semantics while allowing
 * AXI read traffic and OA writeback to run concurrently.
 */

module axi_block_dma_arbiter #(
    parameter int unsigned DATA_WIDTH   = 16,
    parameter int unsigned KERNEL_WIDTH = DATA_WIDTH,
    parameter int unsigned SIZE         = 16,
    parameter int unsigned DMA_SIZE     = SIZE,
    parameter int unsigned BUS_WIDTH    = 32,
    parameter int unsigned DATA_LANES   = BUS_WIDTH / 8,
    parameter int unsigned REG_WIDTH    = 32,
    parameter int unsigned CACHE_BLOCKS = 4,
    parameter int unsigned ENABLE_QUANT_CLIENT = 1,
    parameter int unsigned DMA_MAX_BYTES = 256 * (BUS_WIDTH / 8),
    parameter int unsigned READ_OUTSTANDING = 4,
    parameter int unsigned WRITE_OUTSTANDING = READ_OUTSTANDING,
    parameter int unsigned WINDOW_OUTSTANDING = 4,
    parameter int unsigned WINDOW_LANES = 4,
    parameter int unsigned CONV_CACHE_SETS = 128,
    parameter int unsigned CONV_CACHE_WAYS = 2,
    parameter int unsigned CONV_LINE_BYTES = 16,
    parameter int unsigned CONV_CACHE_POLICY = 3,
    parameter bit CONV_LOW_LATENCY = 1'b0,
    parameter bit p_register_bus_error = 1'b0
) (
    input logic clk,
    input logic rst_n,
    input logic abort = 1'b0,

    // Independent ordered window requests use destination tags and credits.
    input logic win_req_valid = 1'b0,
    output logic win_req_ready,
    input logic [31:0] win_req_p0 = '0, win_req_q0 = '0, win_req_cols = '0,
    input logic [1:0] win_req_tag = '0,
    output logic win_rsp_valid,
    input logic win_rsp_ready = 1'b1,
    output logic [1:0] win_rsp_tag,
    output logic [31:0] win_rsp_col,
    output logic signed [15:0] win_rsp_data[WINDOW_LANES],
    output logic [WINDOW_LANES-1:0] win_rsp_mask,
    output logic win_rsp_last,win_rsp_error,win_busy,

    // Job context belongs to the shared DMA, never to an individual loader.
    input  logic conv_cfg_valid = 1'b0,
    output logic conv_cfg_ready,
    input  logic conv_enable = 1'b0,
    input  logic dma_range_enable = 1'b0,
    input  conv_im2col_pkg::conv_cfg_t conv_cfg = '0,
    input  logic [31:0] conv_sched_r = 32'd0,
    input  logic [31:0] conv_sched_groups = 32'd0,
    input  logic [31:0] conv_range_base [4] = '{default:'0},
    input  logic [32:0] conv_range_end [4] = '{default:'0},
    output logic conv_error, conv_busy,

    input  logic ia_req,
    output logic ia_granted,
    input  logic ia_start,
    input  logic ia_im2col = 1'b0,
    input  logic [31:0] ia_p0 = 32'd0,
    input  logic [31:0] ia_q0 = 32'd0,
    input  logic [31:0] ia_group = 32'd0,
    input  logic ia_linear_read_mode,
    input  logic [REG_WIDTH-1:0] ia_base_addr,
    input  logic [REG_WIDTH-1:0] ia_row_stride,
    input  logic [REG_WIDTH-1:0] ia_rows_to_read,
    input  logic [7:0] ia_burst_len_m1,
    input  logic [((CACHE_BLOCKS <= 1) ? 1 : $clog2(CACHE_BLOCKS))-1:0] ia_slot_id,
    input  logic ia_use_16bits,
    input  logic signed [REG_WIDTH-1:0] ia_lhs_zp,
    output logic ia_busy,
    output logic ia_done,
    output logic [((CACHE_BLOCKS <= 1) ? 1 : $clog2(CACHE_BLOCKS))-1:0] ia_wr_slot,
    output logic [$clog2(SIZE)-1:0] ia_wr_row,
    output logic [$clog2(SIZE)-1:0] ia_wr_col_base,
    output logic signed [DATA_WIDTH-1:0] ia_wr_data [DATA_LANES],
    output logic ia_wr_valid [DATA_LANES],
    input logic ia_wide_im2col = 1'b0,
    output logic ia_wr_use_16bits,

    input  logic kernel_req,
    output logic kernel_granted,
    input  logic kernel_start,
    input  logic kernel_im2col = 1'b0,
    input  logic [31:0] kernel_p0 = 32'd0,
    input  logic [31:0] kernel_q0 = 32'd0,
    input  logic [31:0] kernel_group = 32'd0,
    input  logic kernel_linear_read_mode,
    input  logic [REG_WIDTH-1:0] kernel_base_addr,
    input  logic [REG_WIDTH-1:0] kernel_row_stride,
    input  logic [REG_WIDTH-1:0] kernel_rows_to_read,
    input  logic [7:0] kernel_burst_len_m1,
    input  logic kernel_slot_id,
    input  logic kernel_use_16bits,
    input  logic signed [REG_WIDTH-1:0] kernel_lhs_zp,
    output logic kernel_busy,
    output logic kernel_done,
    output logic kernel_wr_slot,
    output logic [$clog2(SIZE)-1:0] kernel_wr_row,
    output logic [$clog2(SIZE)-1:0] kernel_wr_col_base,
    output logic signed [KERNEL_WIDTH-1:0] kernel_wr_data [DATA_LANES],
    output logic kernel_wr_valid [DATA_LANES],

    input  logic bias_req,
    output logic bias_granted,
    input  logic bias_start,
    input  logic bias_linear_read_mode,
    input  logic [REG_WIDTH-1:0] bias_base_addr,
    input  logic [REG_WIDTH-1:0] bias_row_stride,
    input  logic [REG_WIDTH-1:0] bias_rows_to_read,
    input  logic [7:0] bias_burst_len_m1,
    input  logic bias_slot_id,
    input  logic bias_use_16bits,
    input  logic signed [REG_WIDTH-1:0] bias_lhs_zp,
    output logic bias_busy,
    output logic bias_done,
    output logic bias_wr_slot,
    output logic [$clog2(DMA_SIZE)-1:0] bias_wr_row,
    output logic [$clog2(DMA_SIZE)-1:0] bias_wr_col_base,
    output logic signed [7:0] bias_wr_data [BUS_WIDTH/8],
    output logic bias_wr_valid [BUS_WIDTH/8],
    output logic bias_wr_use_16bits,

    input  logic quant_req,
    output logic quant_granted,
    input  logic quant_start,
    input  logic quant_linear_read_mode,
    input  logic [REG_WIDTH-1:0] quant_base_addr,
    input  logic [REG_WIDTH-1:0] quant_row_stride,
    input  logic [REG_WIDTH-1:0] quant_rows_to_read,
    input  logic [7:0] quant_burst_len_m1,
    input  logic quant_slot_id,
    input  logic quant_use_16bits,
    input  logic signed [REG_WIDTH-1:0] quant_lhs_zp,
    output logic quant_busy,
    output logic quant_done,
    output logic [BUS_WIDTH-1:0] quant_raw_data,
    output logic quant_raw_valid,

    // Vector and window-reduction client. Descriptors are accepted after grant.
    input  logic dw_req = 1'b0,
    output logic dw_granted,
    input  logic dw_start = 1'b0,
    input  logic dw_im2col = 1'b0,
    input  logic [31:0] dw_p0 = '0, dw_q0 = '0, dw_group = '0,
    input  logic dw_linear_read_mode = 1'b0,
    input  logic [REG_WIDTH-1:0] dw_base_addr = '0,
    input  logic [REG_WIDTH-1:0] dw_row_stride = '0,
    input  logic [REG_WIDTH-1:0] dw_rows_to_read = '0,
    input  logic [REG_WIDTH-1:0] dw_valid_cols = REG_WIDTH'(DMA_SIZE),
    input  logic [7:0] dw_burst_len_m1 = '0,
    input  logic dw_use_16bits = 1'b0,
    input  logic signed [REG_WIDTH-1:0] dw_lhs_zp = '0,
    output logic dw_busy, dw_done, dw_error,
    output logic [$clog2(DMA_SIZE)-1:0] dw_row, dw_col_base,
    output logic signed [DATA_WIDTH-1:0] dw_data [BUS_WIDTH/8],
    output logic dw_valid [BUS_WIDTH/8],
    output logic [BUS_WIDTH-1:0] dw_raw_data,
    output logic dw_raw_valid,

    input  logic dw_wr_req = 1'b0,
    output logic dw_wr_granted,
    input  logic dw_wr_start = 1'b0,
    input  logic [REG_WIDTH-1:0] dw_wr_base_addr = '0,
    input  logic [REG_WIDTH-1:0] dw_wr_row_stride = '0,
    input  logic [REG_WIDTH-1:0] dw_wr_rows_to_write = '0,
    input  logic [7:0] dw_wr_burst_len_m1 = '0,
    input  logic [BUS_WIDTH-1:0] dw_src_wdata = '0,
    input  logic [BUS_WIDTH/8-1:0] dw_src_wmask = '0,
    input  logic dw_src_wvalid = 1'b0,
    output logic dw_src_wready,
    output logic dw_wr_busy, dw_wr_done, dw_wr_error,

    input  logic oa_req,
    output logic oa_granted,
    input  logic oa_start,
    input  logic [REG_WIDTH-1:0] oa_base_addr,
    input  logic [REG_WIDTH-1:0] oa_row_stride,
    input  logic [REG_WIDTH-1:0] oa_rows_to_read,
    input  logic [7:0] oa_burst_len_m1,
    input  logic [BUS_WIDTH-1:0] oa_src_wdata,
    input  logic [BUS_WIDTH/8-1:0] oa_src_wmask,
    input  logic oa_src_wvalid,
    output logic oa_src_wready,
    output logic oa_busy,
    output logic oa_done,

    output logic                   m_axi_arvalid,
    input  logic                   m_axi_arready,
    output logic [  REG_WIDTH-1:0] m_axi_araddr,
    output logic [            7:0] m_axi_arlen,
    output logic [            2:0] m_axi_arsize,
    output logic [            1:0] m_axi_arburst,
    input  logic                   m_axi_rvalid,
    output logic                   m_axi_rready,
    input  logic [  BUS_WIDTH-1:0] m_axi_rdata,
    input  logic [            1:0] m_axi_rresp,
    input  logic                   m_axi_rlast,

    output logic                   m_axi_awvalid,
    input  logic                   m_axi_awready,
    output logic [  REG_WIDTH-1:0] m_axi_awaddr,
    output logic [            7:0] m_axi_awlen,
    output logic [            2:0] m_axi_awsize,
    output logic [            1:0] m_axi_awburst,
    output logic                   m_axi_wvalid,
    input  logic                   m_axi_wready,
    output logic [  BUS_WIDTH-1:0] m_axi_wdata,
    output logic [BUS_WIDTH/8-1:0] m_axi_wstrb,
    output logic                   m_axi_wlast,
    input  logic                   m_axi_bvalid,
    output logic                   m_axi_bready,
    input  logic [            1:0] m_axi_bresp,
    output logic                   idle,
    output logic                   bus_error,
    // 未计入同周期中止的权重命令资格，供顶层并行计算接收条件。
    output logic                   o_kernel_eligible
);

    localparam int BYTE_PER_BEAT = BUS_WIDTH / 8;

    logic local_abort, dma_abort, transfer_abort, bus_error_event;
    logic response_error_pending, completed_error;

    // 错误响应有效时即停止接收新命令，接收资格不经过返回通道的就绪逻辑。
    // 错误上报仍以真实响应握手为准，已接收事务继续排空。
    if (p_register_bus_error) begin : g_registered_bus_error
        assign local_abort = abort || response_error_pending || completed_error;
        assign dma_abort = abort || bus_error_event;
        assign transfer_abort = abort || bus_error;
        always_ff @(posedge clk) begin
            if (!rst_n) bus_error <= 1'b0;
            else bus_error <= bus_error_event;
        end
    end else begin : g_direct_bus_error
        assign local_abort = abort;
        assign dma_abort = abort;
        assign transfer_abort = abort;
        assign bus_error = bus_error_event;
    end

    typedef enum logic [2:0] {
        C_IA     = 3'd0,
        C_KERNEL = 3'd1,
        C_BIAS   = 3'd2,
        C_QUANT  = 3'd3,
        C_DW     = 3'd4,
        C_WINDOW = 3'd5,
        C_NONE   = 3'd7
    } client_e;

    client_e rd_grant_client, rd_next_client, rd_command_client, rd_response_client;
    logic rd_active;
    logic [1:0] rd_client_inflight [5];
    logic [3:0] rd_pending_count;
    logic [2:0] rd_pending_count_q;
    logic [2:0] rd_pending_count_next;
    logic rd_pending_increment, rd_pending_decrement, rd_pending_decrement_two;
    logic rd_command_space, rd_reservation_space;
    logic rd_dma_start;
    logic [4:0] rd_client_accept;
    logic rd_dma_start_q, rd_dma_start_ready;
    wire rd_dma_cancel = local_abort && rd_dma_start_q;
    logic [2:0] rd_dma_tag_q, rd_dma_response_tag, rd_dma_finish_tag;
    logic rd_dma_busy;
    logic rd_dma_done;
    logic rd_finish_beat;
    logic dma_conv_cfg_ready, dma_conv_cfg_valid;
    // 授予仅使用已保存的请求方和命令寄存器状态，隔开请求优先选择与外部握手。
    assign rd_command_space = !rd_dma_start_q;
    assign rd_reservation_space = !rd_dma_start_q || rd_dma_start_ready;
    assign rd_command_client = rd_grant_client;
    assign rd_response_client = client_e'(rd_dma_response_tag);
    assign rd_active = (rd_pending_count != 0);
    // 各请求方直接记录自身握手，计数更新只依赖本通道的接收条件。
    assign rd_client_accept[C_IA] = ia_start && ia_granted;
    assign rd_client_accept[C_KERNEL] = kernel_start && kernel_granted;
    assign rd_client_accept[C_BIAS] = bias_start && bias_granted;
    assign rd_client_accept[C_QUANT] = quant_start && quant_granted;
    assign rd_client_accept[C_DW] = dw_start && dw_granted;
    // 各请求方的接收条件已经包含归属译码，直接并行归并为命令接收事件。
    assign rd_dma_start = |rd_client_accept;
    assign dma_conv_cfg_valid = conv_cfg_valid && !rd_active &&
                                !rd_dma_start_q && rd_grant_client == C_NONE;
    assign conv_cfg_ready = dma_conv_cfg_ready && !rd_active &&
                            !rd_dma_start_q && rd_grant_client == C_NONE;

    logic rd_dma_linear_read_mode;
    logic rd_dma_im2col;
    logic [31:0] rd_dma_p0, rd_dma_q0, rd_dma_group;
    logic [REG_WIDTH-1:0] rd_dma_base_addr;
    logic [REG_WIDTH-1:0] rd_dma_row_stride;
    logic [REG_WIDTH-1:0] rd_dma_rows_to_read;
    logic [REG_WIDTH-1:0] rd_dma_valid_cols;
    logic [7:0] rd_dma_burst_len_m1;
    logic [((CACHE_BLOCKS <= 1) ? 1 : $clog2(CACHE_BLOCKS))-1:0] rd_dma_slot_id;
    logic rd_dma_use_16bits;
    logic signed [REG_WIDTH-1:0] rd_dma_lhs_zp;

    logic [((CACHE_BLOCKS <= 1) ? 1 : $clog2(CACHE_BLOCKS))-1:0] dma_wr_slot;
    logic [$clog2(DMA_SIZE)-1:0] dma_wr_row;
    logic [$clog2(DMA_SIZE)-1:0] dma_wr_col_base;
    logic signed [DATA_WIDTH-1:0] dma_wr_data [DATA_LANES];
    logic dma_wr_valid [DATA_LANES];
    logic dma_wr_use_16bits;
    logic [BUS_WIDTH-1:0] dma_raw_data;
    logic dma_raw_valid;
    logic [$clog2(DMA_SIZE)-1:0] dma_raw_row;
    logic [$clog2(DMA_SIZE)-1:0] dma_raw_col_base;
    logic dma_rd_error;
    logic dma_wr_error;

    logic wr_active;
    logic wr_started;
    logic wr_owner_dw;
    logic wr_dma_start;
    logic wr_dma_busy;
    logic wr_dma_done;
    logic wr_src_wready;
    logic conv_job_q;
    wire quant_req_eff = (ENABLE_QUANT_CLIENT != 0) ? quant_req : 1'b0;

    always_ff @(posedge clk) begin
        if (!rst_n) conv_job_q <= 1'b0;
        else if (conv_cfg_valid && conv_cfg_ready) conv_job_q <= conv_enable;
    end

    // 在途总数与各请求方计数使用同一组接受、完成和取消事件更新。
    // 完成旧描述符并取消暂存描述符时，同一边沿释放两个位置。
    assign rd_pending_count = {1'b0, rd_pending_count_q};
    assign rd_pending_increment = rd_dma_start && !rd_dma_done && !rd_dma_cancel;
    assign rd_pending_decrement = (!rd_dma_start && (rd_dma_done ^ rd_dma_cancel)) ||
        (rd_dma_start && rd_dma_done && rd_dma_cancel);
    assign rd_pending_decrement_two = !rd_dma_start && rd_dma_done && rd_dma_cancel;
    // 三位计数逐位计算翻转条件，晚到的完成事件直接参与最终结果选择。
    assign rd_pending_count_next[0] = rd_pending_count_q[0] ^
        rd_dma_start ^ rd_dma_done ^ rd_dma_cancel;
    assign rd_pending_count_next[1] = rd_pending_count_q[1] ^
        ((rd_pending_increment && rd_pending_count_q[0]) ||
         (rd_pending_decrement && !rd_pending_count_q[0]) || rd_pending_decrement_two);
    assign rd_pending_count_next[2] = rd_pending_count_q[2] ^
        ((rd_pending_increment && (&rd_pending_count_q[1:0])) ||
         (rd_pending_decrement && !(|rd_pending_count_q[1:0])) ||
         (rd_pending_decrement_two && !rd_pending_count_q[1]));
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            rd_pending_count_q <= 3'd0;
        end else begin
            rd_pending_count_q <= rd_pending_count_next;
        end
    end

    always_comb begin
        rd_next_client = C_NONE;
        if (!local_abort && rd_reservation_space && !conv_cfg_valid && rd_pending_count < 4 &&
            (!conv_job_q || rd_pending_count < 2)) begin
            if (dw_req && rd_client_inflight[C_DW] == 0)
                rd_next_client = C_DW;
            else if (kernel_req && rd_client_inflight[C_KERNEL] < 2)
                rd_next_client = C_KERNEL;
            else if (quant_req_eff && rd_client_inflight[C_QUANT] == 0)
                rd_next_client = C_QUANT;
            else if (bias_req && rd_client_inflight[C_BIAS] == 0)
                rd_next_client = C_BIAS;
            else if (ia_req && rd_client_inflight[C_IA] == 0)
                rd_next_client = C_IA;
            else if (win_req_valid && !rd_active && !rd_dma_start_q)
                rd_next_client = C_WINDOW;
        end
    end

    // 当前描述符交付DMA的边沿可同时保存下一次授予，连续命令保留两周期接收间隔。
    // 请求撤销清除尚未启动的授予；已接收描述符按各自返回标记释放。
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            rd_grant_client <= C_NONE;
        end else begin
            if (rd_dma_start) rd_grant_client <= C_NONE;
            else if (rd_grant_client == C_NONE) rd_grant_client <= rd_next_client;
            else if (rd_grant_client == C_WINDOW) begin
                if (local_abort || conv_cfg_valid || !win_req_valid)
                    rd_grant_client <= C_NONE;
                // 窗口描述符完成握手后立即选择下一请求，连续窗口保持逐周期接收。
                else if (win_req_ready)
                    rd_grant_client <= rd_next_client;
            end
            else if (local_abort || (rd_grant_client == C_IA && !ia_req) ||
                     (rd_grant_client == C_KERNEL && !kernel_req) ||
                     (rd_grant_client == C_BIAS && !bias_req) ||
                     (rd_grant_client == C_QUANT && !quant_req_eff) ||
                     (rd_grant_client == C_DW && !dw_req))
                rd_grant_client <= C_NONE;
        end
    end
    // 每个请求方独立更新两位计数，接收、完成和取消按同一张更新表合并。
    for (genvar client_index = 0; client_index < 5; client_index++) begin : g_client_inflight
        logic [1:0] count_q, count_d;
        logic client_done, client_cancel;

        assign rd_client_inflight[client_index] = count_q;
        assign client_done = rd_dma_done && rd_response_client == client_e'(client_index);
        assign client_cancel = rd_dma_cancel && rd_dma_tag_q == 3'(client_index);
        // 接收增加一项，完成与取消分别释放一项，计数保留两位回绕行为。
        always_comb begin
            count_d = count_q;
            case ({rd_client_accept[client_index], client_done, client_cancel})
                3'b100: count_d = count_q + 2'd1;
                3'b001, 3'b010, 3'b111: count_d = count_q - 2'd1;
                3'b011: count_d = count_q - 2'd2;
                default: ;
            endcase
        end
        always_ff @(posedge clk) begin
            if (!rst_n) count_q <= 2'd0;
            else count_q <= count_d;
        end
    end
    assign o_kernel_eligible = rd_command_space && rd_command_client == C_KERNEL;
    // 请求方译码与命令位置、中止条件在同一级完成，保留所有请求方的同周期撤销。
    assign dw_granted = !local_abort && rd_command_space && rd_command_client == C_DW;
    assign ia_granted = !local_abort && rd_command_space && rd_command_client == C_IA;
    assign kernel_granted = !local_abort && rd_command_space && rd_command_client == C_KERNEL;
    assign bias_granted = !local_abort && rd_command_space && rd_command_client == C_BIAS;
    assign quant_granted = !local_abort && (ENABLE_QUANT_CLIENT != 0) && rd_command_space &&
        rd_command_client == C_QUANT;
    assign dw_busy = (rd_client_inflight[C_DW] != 0);
    assign dw_done = rd_response_client == C_DW && rd_dma_done;
    assign dw_error = dw_done && dma_rd_error;
    assign ia_busy = (rd_client_inflight[C_IA] != 0);
    assign kernel_busy = (rd_client_inflight[C_KERNEL] != 0);
    assign bias_busy = (rd_client_inflight[C_BIAS] != 0);
    assign quant_busy = (rd_client_inflight[C_QUANT] != 0);
    // Internal completion always releases the DMA owner, including errors.
    // A failed Conv operand must not publish a successful tile commit to its
    // loader; the task's error/drain/reset path discards its partial writes.
    // GEMM retains the original completion semantics.
    assign ia_done = rd_response_client == C_IA && rd_dma_done &&
                     (!conv_job_q || !dma_rd_error);
    assign kernel_done = rd_response_client == C_KERNEL && rd_dma_done &&
                         (!conv_job_q || !dma_rd_error);
    assign bias_done = rd_response_client == C_BIAS && rd_dma_done;
    assign quant_done = rd_response_client == C_QUANT && rd_dma_done;

    always_comb begin
        rd_dma_im2col           = 1'b0;
        rd_dma_p0               = '0;
        rd_dma_q0               = '0;
        rd_dma_group            = '0;
        rd_dma_linear_read_mode = 1'b0;
        rd_dma_base_addr        = '0;
        rd_dma_row_stride       = '0;
        rd_dma_rows_to_read     = '0;
        rd_dma_valid_cols       = REG_WIDTH'(DMA_SIZE);
        rd_dma_burst_len_m1     = '0;
        rd_dma_slot_id          = '0;
        rd_dma_use_16bits       = 1'b0;
        rd_dma_lhs_zp           = '0;

        unique case (rd_command_client)
            C_DW: begin
                rd_dma_im2col = dw_im2col;
                rd_dma_p0 = dw_p0;
                rd_dma_q0 = dw_q0;
                rd_dma_group = dw_group;
                rd_dma_linear_read_mode = dw_linear_read_mode;
                rd_dma_base_addr = dw_base_addr;
                rd_dma_row_stride = dw_row_stride;
                rd_dma_rows_to_read = dw_rows_to_read;
                rd_dma_valid_cols = dw_valid_cols;
                rd_dma_burst_len_m1 = dw_burst_len_m1;
                rd_dma_use_16bits = dw_use_16bits;
                rd_dma_lhs_zp = dw_lhs_zp;
            end
            C_IA: begin
                rd_dma_im2col           = ia_im2col;
                rd_dma_p0               = ia_p0;
                rd_dma_q0               = ia_q0;
                rd_dma_group            = ia_group;
                rd_dma_linear_read_mode = ia_linear_read_mode;
                rd_dma_base_addr        = ia_base_addr;
                rd_dma_row_stride       = ia_row_stride;
                rd_dma_rows_to_read     = ia_rows_to_read;
                rd_dma_burst_len_m1     = ia_burst_len_m1;
                rd_dma_slot_id          = ia_slot_id;
                rd_dma_use_16bits       = ia_use_16bits;
                rd_dma_lhs_zp           = ia_lhs_zp;
            end
            C_KERNEL: begin
                rd_dma_im2col           = kernel_im2col;
                rd_dma_p0               = kernel_p0;
                rd_dma_q0               = kernel_q0;
                rd_dma_group            = kernel_group;
                rd_dma_linear_read_mode = kernel_linear_read_mode;
                rd_dma_base_addr        = kernel_base_addr;
                rd_dma_row_stride       = kernel_row_stride;
                rd_dma_rows_to_read     = kernel_rows_to_read;
                rd_dma_burst_len_m1     = kernel_burst_len_m1;
                rd_dma_slot_id          = '0;
                rd_dma_slot_id[0]       = kernel_slot_id;
                rd_dma_use_16bits       = kernel_use_16bits;
                rd_dma_lhs_zp           = kernel_lhs_zp;
            end
            C_BIAS: begin
                rd_dma_linear_read_mode = bias_linear_read_mode;
                rd_dma_base_addr        = bias_base_addr;
                rd_dma_row_stride       = bias_row_stride;
                rd_dma_rows_to_read     = bias_rows_to_read;
                rd_dma_burst_len_m1     = bias_burst_len_m1;
                rd_dma_slot_id          = '0;
                rd_dma_slot_id[0]       = bias_slot_id;
                rd_dma_use_16bits       = bias_use_16bits;
                rd_dma_lhs_zp           = bias_lhs_zp;
            end
            C_QUANT: begin
                if (ENABLE_QUANT_CLIENT != 0) begin
                    rd_dma_linear_read_mode = quant_linear_read_mode;
                    rd_dma_base_addr        = quant_base_addr;
                    rd_dma_row_stride       = quant_row_stride;
                    rd_dma_rows_to_read     = quant_rows_to_read;
                    rd_dma_burst_len_m1     = quant_burst_len_m1;
                    rd_dma_slot_id          = '0;
                    rd_dma_slot_id[0]       = quant_slot_id;
                    rd_dma_use_16bits       = quant_use_16bits;
                    rd_dma_lhs_zp           = quant_lhs_zp;
                end
            end
            default: ;
        endcase
    end

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            wr_active  <= 1'b0;
            wr_started <= 1'b0;
            wr_owner_dw <= 1'b0;
        end else begin
            if (!wr_active) begin
                if (!local_abort && (dw_wr_req || oa_req)) begin
                    wr_owner_dw <= dw_wr_req;
                    wr_active  <= 1'b1;
                    wr_started <= 1'b0;
                end
            end else if (!wr_started) begin
                if (wr_dma_start) begin
                    wr_started <= 1'b1;
                end else if (local_abort || (wr_owner_dw ? !dw_wr_req : !oa_req)) begin
                    wr_active  <= 1'b0;
                    wr_started <= 1'b0;
                end
            end else if (wr_dma_done) begin
                wr_active  <= 1'b0;
                wr_started <= 1'b0;
            end
        end
    end

    assign oa_granted = !local_abort && wr_active && !wr_owner_dw;
    assign dw_wr_granted = !local_abort && wr_active && wr_owner_dw;
    assign wr_dma_start = !wr_started &&
        ((oa_start && oa_granted) || (dw_wr_start && dw_wr_granted));
    // 已启动的写通道按保存的归属返回忙碌与数据接收资格。
    // 当周期出现读错误时，已经发送的写数据仍向生产者确认接收，随后停止新数据。
    wire write_transfer_active = wr_active && !transfer_abort;
    assign dw_wr_busy = write_transfer_active && wr_owner_dw && wr_dma_busy;
    assign dw_wr_done = dw_wr_granted && wr_dma_done;
    assign dw_wr_error = dw_wr_done && dma_wr_error;
    assign dw_src_wready = write_transfer_active && wr_owner_dw && wr_src_wready;
    assign oa_busy = write_transfer_active && !wr_owner_dw && wr_dma_busy;
    assign oa_done = oa_granted && wr_dma_done;
    assign oa_src_wready = write_transfer_active && !wr_owner_dw && wr_src_wready;

    for (genvar i = 0; i < BYTE_PER_BEAT; i++) begin : gen_route_wr
        assign dw_data[i] = dma_wr_data[i];
        assign dw_valid[i] = (rd_response_client == C_DW) && dma_wr_valid[i];
        assign bias_wr_data[i]    = dma_wr_data[i][7:0];
        assign bias_wr_valid[i]   = (rd_response_client == C_BIAS) && dma_wr_valid[i];
    end
    for (genvar i = 0; i < DATA_LANES; i++) begin : g_matrix_data
        assign ia_wr_data[i]      = dma_wr_data[i];
        assign ia_wr_valid[i]     = (rd_response_client == C_IA) && dma_wr_valid[i];
        assign kernel_wr_data[i]  = KERNEL_WIDTH'($signed(dma_wr_data[i]));
        assign kernel_wr_valid[i] = (rd_response_client == C_KERNEL) && dma_wr_valid[i];
    end

    assign dw_row = dma_wr_row;
    assign dw_col_base = dma_wr_col_base;
    assign dw_raw_data = dma_raw_data;
    assign dw_raw_valid = (rd_response_client == C_DW) && dma_raw_valid;

    assign ia_wr_slot       = dma_wr_slot;
    assign ia_wr_row        = dma_wr_row[$clog2(SIZE)-1:0];
    assign ia_wr_col_base   = dma_wr_col_base[$clog2(SIZE)-1:0];
    assign ia_wr_use_16bits = dma_wr_use_16bits;

    assign kernel_wr_slot     = dma_wr_slot[0];
    assign kernel_wr_row      = dma_wr_row[$clog2(SIZE)-1:0];
    assign kernel_wr_col_base = dma_wr_col_base[$clog2(SIZE)-1:0];

    assign bias_wr_slot       = dma_wr_slot[0];
    assign bias_wr_row        = dma_wr_row;
    assign bias_wr_col_base   = dma_wr_col_base;
    assign bias_wr_use_16bits = dma_wr_use_16bits;

    assign quant_raw_data  = (ENABLE_QUANT_CLIENT != 0) ? dma_raw_data : '0;
    assign quant_raw_valid = (rd_response_client == C_QUANT) && dma_raw_valid;

    // Registered command descriptor separates client arbitration from DMA
    // address arithmetic. Client grants and completion tags keep their order.
    logic win_dma_req_ready, win_accept_allowed;
    // 窗口与普通读请求共用寄存授予，连续窗口可在相邻周期完成握手。
    // 普通卷积可提前保存一条命令，描述符按接受顺序进入 DMA。
    assign win_accept_allowed = !local_abort && !conv_cfg_valid && !rd_active &&
                                rd_command_client == C_WINDOW && !rd_dma_start_q;
    assign win_req_ready = win_dma_req_ready && win_accept_allowed;
    // 写授予占用期间保持非空闲，开始资格不再经生产者组合信号返回空闲判断。
    assign idle = !rd_active && rd_grant_client == C_NONE &&
                  !rd_dma_busy && !wr_dma_busy && !rd_dma_start_q && !wr_active;
    // 响应错误资格与命令完成错误并行计算，响应握手只控制错误上报。
    assign response_error_pending = (m_axi_rvalid && m_axi_rresp[1]) ||
        (m_axi_bvalid && m_axi_bresp[1]);
    assign completed_error = (rd_dma_done && dma_rd_error) ||
        (wr_dma_done && dma_wr_error);
    assign bus_error_event = (m_axi_rvalid && m_axi_rready && m_axi_rresp[1]) ||
        (m_axi_bvalid && m_axi_bready && m_axi_bresp[1]) ||
        completed_error;
    logic rd_dma_linear_read_mode_q;
    logic rd_dma_im2col_q;
    logic [31:0] rd_dma_p0_q, rd_dma_q0_q, rd_dma_group_q;
    logic [REG_WIDTH-1:0] rd_dma_base_addr_q;
    logic [REG_WIDTH-1:0] rd_dma_row_stride_q;
    logic [REG_WIDTH-1:0] rd_dma_rows_to_read_q;
    logic [REG_WIDTH-1:0] rd_dma_valid_cols_q;
    logic [8-1:0] rd_dma_burst_len_m1_q;
    logic [((CACHE_BLOCKS <= 1) ? 1 : $clog2(CACHE_BLOCKS))-1:0] rd_dma_slot_id_q;
    logic rd_dma_use_16bits_q;
    logic [REG_WIDTH-1:0] rd_dma_lhs_zp_q;
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            rd_dma_start_q <= '0;
            rd_dma_tag_q <= '0;
            rd_dma_im2col_q <= '0;
            rd_dma_p0_q <= '0;
            rd_dma_q0_q <= '0;
            rd_dma_group_q <= '0;
            rd_dma_linear_read_mode_q <= '0;
            rd_dma_base_addr_q <= '0;
            rd_dma_row_stride_q <= '0;
            rd_dma_rows_to_read_q <= '0;
            rd_dma_valid_cols_q <= '0;
            rd_dma_burst_len_m1_q <= '0;
            rd_dma_slot_id_q <= '0;
            rd_dma_use_16bits_q <= '0;
            rd_dma_lhs_zp_q <= '0;
        end else begin
            // Abort releases the registered descriptor before DMA acceptance.
            // Already accepted contexts keep their ordinary completion path.
            if (local_abort || rd_dma_start_ready) rd_dma_start_q <= 1'b0;
            if (rd_dma_start) begin
                rd_dma_start_q <= 1'b1;
                rd_dma_tag_q <= rd_command_client;
                rd_dma_im2col_q <= rd_dma_im2col;
                rd_dma_p0_q <= rd_dma_p0;
                rd_dma_q0_q <= rd_dma_q0;
                rd_dma_group_q <= rd_dma_group;
                rd_dma_linear_read_mode_q <= rd_dma_linear_read_mode;
                rd_dma_base_addr_q <= rd_dma_base_addr;
                rd_dma_row_stride_q <= rd_dma_row_stride;
                rd_dma_rows_to_read_q <= rd_dma_rows_to_read;
                rd_dma_valid_cols_q <= rd_dma_valid_cols;
                rd_dma_burst_len_m1_q <= rd_dma_burst_len_m1;
                rd_dma_slot_id_q <= rd_dma_slot_id;
                rd_dma_use_16bits_q <= rd_dma_use_16bits;
                rd_dma_lhs_zp_q <= rd_dma_lhs_zp;
            end
        end
    end

    axi_dual_block_dma #(
        .DMA_MAX_BYTES(DMA_MAX_BYTES),
        .DATA_WIDTH       (DATA_WIDTH),
        .SIZE             (DMA_SIZE),
        .IM2COL_SIZE      (SIZE),
        .WINDOW_OUTSTANDING(WINDOW_OUTSTANDING),
        .WINDOW_LANES(WINDOW_LANES),
        .DATA_LANES(DATA_LANES),
        .BUS_WIDTH        (BUS_WIDTH),
        .REG_WIDTH        (REG_WIDTH),
        .CACHE_BLOCKS     (CACHE_BLOCKS),
        .READ_OUTSTANDING (READ_OUTSTANDING),
        .RD_CONTEXT_DEPTH (4),
        .RD_TAG_WIDTH     (3),
        .WRITE_OUTSTANDING(WRITE_OUTSTANDING),
        .CONV_CACHE_SETS(CONV_CACHE_SETS), .CONV_CACHE_WAYS(CONV_CACHE_WAYS),
        .CONV_LINE_BYTES(CONV_LINE_BYTES), .CONV_CACHE_POLICY(CONV_CACHE_POLICY),
        .CONV_LOW_LATENCY(CONV_LOW_LATENCY)
    ) u_dma (
        .clk                (clk),
        .rst_n              (rst_n),
        .win_req_valid(win_req_valid && win_accept_allowed),.win_req_ready(win_dma_req_ready),
        .win_req_p0,.win_req_q0,.win_req_cols,.win_req_tag,
        .win_rsp_valid,.win_rsp_ready,.win_rsp_tag,.win_rsp_col,.win_rsp_data,.win_rsp_mask,
        .win_rsp_last,.win_rsp_error,.win_busy,
        .abort(dma_abort),
        .conv_cfg_valid(dma_conv_cfg_valid), .conv_cfg_ready(dma_conv_cfg_ready),
        .conv_enable, .dma_range_enable, .conv_cfg,
        .conv_sched_r, .conv_sched_groups, .conv_range_base, .conv_range_end,
        .conv_error, .conv_busy,
        .rd_start           (rd_dma_start_q && !local_abort),
        .rd_tag             (rd_dma_tag_q),
        .rd_start_ready     (rd_dma_start_ready),
        .rd_response_tag    (rd_dma_response_tag),
        .rd_finish_tag      (rd_dma_finish_tag),
        .rd_im2col          (rd_dma_im2col_q),
        .rd_wide_im2col     (rd_dma_tag_q == C_KERNEL || (rd_dma_tag_q == C_IA && ia_wide_im2col)),
        .rd_p0              (rd_dma_p0_q),
        .rd_q0              (rd_dma_q0_q),
        .rd_group           (rd_dma_group_q),
        .rd_linear_read_mode(rd_dma_linear_read_mode_q),
        .rd_base_addr       (rd_dma_base_addr_q),
        .rd_row_stride      (rd_dma_row_stride_q),
        .rd_rows_to_read    (rd_dma_rows_to_read_q),
        .rd_valid_cols      (rd_dma_valid_cols_q),
        .rd_burst_len_m1    (rd_dma_burst_len_m1_q),
        .rd_slot_id         (rd_dma_slot_id_q),
        .rd_use_16bits      (rd_dma_use_16bits_q),
        .rd_lhs_zp          (rd_dma_lhs_zp_q),
        .rd_busy            (rd_dma_busy),
        .rd_done            (rd_dma_done),
        .rd_finish_beat     (rd_finish_beat),
        .wr_start           (wr_dma_start),
        .wr_base_addr       (wr_owner_dw ? dw_wr_base_addr : oa_base_addr),
        .wr_row_stride      (wr_owner_dw ? dw_wr_row_stride : oa_row_stride),
        .wr_rows_to_write   (wr_owner_dw ? dw_wr_rows_to_write : oa_rows_to_read),
        .wr_burst_len_m1    (wr_owner_dw ? dw_wr_burst_len_m1 : oa_burst_len_m1),
        .wr_busy            (wr_dma_busy),
        .wr_done            (wr_dma_done),
        .src_wdata          (wr_owner_dw ? dw_src_wdata : oa_src_wdata),
        .src_wmask          (wr_owner_dw ? dw_src_wmask : oa_src_wmask),
        .src_wvalid         (wr_owner_dw ? dw_src_wvalid : oa_src_wvalid),
        .src_wready         (wr_src_wready),
        .m_axi_arvalid      (m_axi_arvalid),
        .m_axi_arready      (m_axi_arready),
        .m_axi_araddr       (m_axi_araddr),
        .m_axi_arlen        (m_axi_arlen),
        .m_axi_arsize       (m_axi_arsize),
        .m_axi_arburst      (m_axi_arburst),
        .m_axi_rvalid       (m_axi_rvalid),
        .m_axi_rready       (m_axi_rready),
        .m_axi_rdata        (m_axi_rdata),
        .m_axi_rresp        (m_axi_rresp),
        .m_axi_rlast        (m_axi_rlast),
        .m_axi_awvalid      (m_axi_awvalid),
        .m_axi_awready      (m_axi_awready),
        .m_axi_awaddr       (m_axi_awaddr),
        .m_axi_awlen        (m_axi_awlen),
        .m_axi_awsize       (m_axi_awsize),
        .m_axi_awburst      (m_axi_awburst),
        .m_axi_wvalid       (m_axi_wvalid),
        .m_axi_wready       (m_axi_wready),
        .m_axi_wdata        (m_axi_wdata),
        .m_axi_wstrb        (m_axi_wstrb),
        .m_axi_wlast        (m_axi_wlast),
        .m_axi_bvalid       (m_axi_bvalid),
        .m_axi_bready       (m_axi_bready),
        .m_axi_bresp        (m_axi_bresp),
        .wr_slot            (dma_wr_slot),
        .wr_row             (dma_wr_row),
        .wr_col_base        (dma_wr_col_base),
        .wr_data            (dma_wr_data),
        .wr_valid           (dma_wr_valid),
        .wr_use_16bits      (dma_wr_use_16bits),
        .rd_raw_data        (dma_raw_data),
        .rd_raw_valid       (dma_raw_valid),
        .rd_raw_row         (dma_raw_row),
        .rd_raw_col_base    (dma_raw_col_base),
        .rd_error           (dma_rd_error),
        .wr_error           (dma_wr_error)
    );

endmodule
