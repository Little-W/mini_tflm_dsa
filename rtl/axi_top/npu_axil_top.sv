`ifndef GEMMORA_PS_POOL_BYTES
`define GEMMORA_PS_POOL_BYTES 12288
`endif
module npu_axil_top #(
    parameter AXIL_DATA_WIDTH = 32,
    parameter AXIL_ADDR_WIDTH = 16,
    parameter WEIGHT_WIDTH    = 16,
    parameter DATA_WIDTH      = 16,
    parameter SIZE            = 16,
    parameter BUS_WIDTH       = 32,
    parameter REG_WIDTH       = 32,
    parameter AXI_ADDR_WIDTH  = 32,
    parameter NPU_ADDR_WIDTH  = AXI_ADDR_WIDTH,
    parameter IA_CACHE_BLOCKS = 4,
    parameter IA_COMPACT_ENABLE = 1,
    parameter SHARED_IA_PS_ENABLE = 1,
    parameter SHARED_BANK_BYTES = 2048,
    parameter SHARED_BANK_COUNT = 0,
    parameter SHARED_TOTAL_BYTES = SHARED_BANK_COUNT != 0 ? SHARED_BANK_COUNT * SHARED_BANK_BYTES :
        IA_CACHE_BLOCKS * SIZE * SIZE * DATA_WIDTH / 8 + `GEMMORA_PS_POOL_BYTES,
    parameter CONV_CACHE_SETS = 128,
    parameter CONV_CACHE_WAYS = 2,
    parameter CONV_LINE_BYTES = 16,
    parameter CONV_CACHE_POLICY = 3,
    parameter ENABLE_DW_POOL = 1,
    parameter DW_PE_COUNT = (SIZE < 8) ? SIZE : 8,
    parameter ENABLE_VECTOR_ENGINE = ENABLE_DW_POOL,
    parameter VECTOR_PE_COUNT = DW_PE_COUNT,
    parameter DW_MAX_TAPS = 49,
    parameter POOL_MAX_TAPS = 256,
    parameter PS_FRAME_COUNT  = SIZE,
    parameter PS_STORAGE_ROWS = ((3*SIZE)-1)*(PS_FRAME_COUNT+1),
    parameter OA_S16_FIFO_BANKS_MAX = 4,
    parameter int unsigned DMA_MAX_BYTES = 256 * (BUS_WIDTH / 8),
    parameter AXI_READ_OUTSTANDING = 4,
    parameter AXI_WRITE_OUTSTANDING = AXI_READ_OUTSTANDING,
    parameter ENABLE_IS_MODE = 1,
    parameter ENABLE_PER_CHANNEL = 1,
    parameter ENABLE_CLOCK_GATING = 1
) (
    input  wire clk,
    input  wire rst_n,

    input  wire [AXIL_ADDR_WIDTH-1:0] s_axil_awaddr,
    input  wire [2:0]                 s_axil_awprot,
    input  wire                       s_axil_awvalid,
    output wire                       s_axil_awready,
    input  wire [AXIL_DATA_WIDTH-1:0] s_axil_wdata,
    input  wire [AXIL_DATA_WIDTH/8-1:0] s_axil_wstrb,
    input  wire                       s_axil_wvalid,
    output wire                       s_axil_wready,
    output wire [1:0]                 s_axil_bresp,
    output wire                       s_axil_bvalid,
    input  wire                       s_axil_bready,
    input  wire [AXIL_ADDR_WIDTH-1:0] s_axil_araddr,
    input  wire [2:0]                 s_axil_arprot,
    input  wire                       s_axil_arvalid,
    output wire                       s_axil_arready,
    output wire [AXIL_DATA_WIDTH-1:0] s_axil_rdata,
    output wire [1:0]                 s_axil_rresp,
    output wire                       s_axil_rvalid,
    input  wire                       s_axil_rready,

    output wire                         m_axi_arvalid,
    input  wire                         m_axi_arready,
    output wire [AXI_ADDR_WIDTH-1:0]    m_axi_araddr,
    output wire [3:0]                   m_axi_arcache,
    output wire [2:0]                   m_axi_arprot,
    output wire [1:0]                   m_axi_arlock,
    output wire [1:0]                   m_axi_arburst,
    output wire [7:0]                   m_axi_arlen,
    output wire [2:0]                   m_axi_arsize,

    output wire                         m_axi_awvalid,
    input  wire                         m_axi_awready,
    output wire [AXI_ADDR_WIDTH-1:0]    m_axi_awaddr,
    output wire [3:0]                   m_axi_awcache,
    output wire [2:0]                   m_axi_awprot,
    output wire [1:0]                   m_axi_awlock,
    output wire [1:0]                   m_axi_awburst,
    output wire [7:0]                   m_axi_awlen,
    output wire [2:0]                   m_axi_awsize,

    input  wire                         m_axi_rvalid,
    output wire                         m_axi_rready,
    input  wire [BUS_WIDTH-1:0]         m_axi_rdata,
    input  wire [1:0]                   m_axi_rresp,
    input  wire                         m_axi_rlast,

    output wire                         m_axi_wvalid,
    input  wire                         m_axi_wready,
    output wire [BUS_WIDTH-1:0]         m_axi_wdata,
    output wire [BUS_WIDTH/8-1:0]       m_axi_wstrb,
    output wire                         m_axi_wlast,

    input  wire                         m_axi_bvalid,
    output wire                         m_axi_bready,
    input  wire [1:0]                   m_axi_bresp,

    output wire                         irq,
    output wire                         npu_busy
);

    wire [REG_WIDTH-1:0] lhs_base_reg;
    wire [REG_WIDTH-1:0] rhs_base_reg;
    wire [REG_WIDTH-1:0] dst_base_reg;
    wire [REG_WIDTH-1:0] bias_base_reg;
    wire [REG_WIDTH-1:0] k_reg;
    wire [REG_WIDTH-1:0] n_reg;
    wire [REG_WIDTH-1:0] m_reg;
    wire [REG_WIDTH-1:0] lhs_row_stride_b_reg;
    wire [REG_WIDTH-1:0] rhs_col_stride_b_reg;
    wire [REG_WIDTH-1:0] dst_row_stride_b_reg;
    wire signed [REG_WIDTH-1:0] lhs_zp_reg;
    wire signed [REG_WIDTH-1:0] rhs_zp_reg;
    wire signed [REG_WIDTH-1:0] dst_zp_reg;
    wire signed [REG_WIDTH-1:0] q_mult_pt_reg;
    wire signed [REG_WIDTH-1:0] q_shift_pt_reg;
    wire signed [REG_WIDTH-1:0] act_min_reg;
    wire signed [REG_WIDTH-1:0] act_max_reg;
    wire cfg_conv_enable_reg;
    wire cfg_vector_enable_reg, cfg_vector_s16_reg;
    wire [3:0] cfg_vector_op_reg;
    wire [31:0] cfg_vector_length_reg;
    wire signed [31:0] cfg_add_input1_multiplier_reg, cfg_add_input1_shift_reg;
    wire signed [31:0] cfg_add_input2_multiplier_reg, cfg_add_input2_shift_reg;
    wire signed [31:0] cfg_add_left_shift_reg;
    wire [31:0] vector_stat_cycles, vector_stat_compute, vector_stat_dma_wait;
    vector_engine_pkg::vector_engine_cfg_t cfg_vector_reg;
    always_comb begin
        cfg_vector_reg = '0;
        cfg_vector_reg.op = cfg_vector_op_reg;
        cfg_vector_reg.vector_s16 = cfg_vector_s16_reg;
        cfg_vector_reg.length = cfg_vector_length_reg;
        cfg_vector_reg.input_base = lhs_base_reg;
        cfg_vector_reg.rhs_base = rhs_base_reg;
        cfg_vector_reg.output_base = dst_base_reg;
        cfg_vector_reg.bias_base = bias_base_reg;
        cfg_vector_reg.multiplier_base = q_mult_pt_reg;
        cfg_vector_reg.shift_base = q_shift_pt_reg;
        cfg_vector_reg.output_offset = dst_zp_reg;
        cfg_vector_reg.activation_min = act_min_reg;
        cfg_vector_reg.activation_max = act_max_reg;
        cfg_vector_reg.image = cfg_conv_reg;
        cfg_vector_reg.add.input1_offset = lhs_zp_reg;
        cfg_vector_reg.add.input2_offset = rhs_zp_reg;
        cfg_vector_reg.add.input1_multiplier = cfg_add_input1_multiplier_reg;
        cfg_vector_reg.add.input1_shift = cfg_add_input1_shift_reg;
        cfg_vector_reg.add.input2_multiplier = cfg_add_input2_multiplier_reg;
        cfg_vector_reg.add.input2_shift = cfg_add_input2_shift_reg;
        cfg_vector_reg.add.left_shift = cfg_add_left_shift_reg;
        cfg_vector_reg.add.output_multiplier = q_mult_pt_reg;
        cfg_vector_reg.add.output_shift = q_shift_pt_reg;
    end
    conv_im2col_pkg::conv_cfg_t cfg_conv_reg;
    wire [31:0] conv_stat_hits, conv_stat_misses, conv_stat_read_bytes, conv_stat_cycles;
`ifdef GEMMORA_INT8_PROFILE
    localparam bit CONV_CAPABLE = 1'b0;
    localparam bit VECTOR_ENGINE_CAPABLE = 1'b0;
`else
    localparam bit VECTOR_ENGINE_CAPABLE = ENABLE_VECTOR_ENGINE != 0 && (BUS_WIDTH == 32 || BUS_WIDTH == 64) && REG_WIDTH == 32 &&
        SIZE >= 2 && SIZE <= 64 && ((SIZE & (SIZE-1)) == 0) &&
        DW_MAX_TAPS >= 1 && DW_MAX_TAPS <= 255 &&
        POOL_MAX_TAPS >= 1 && POOL_MAX_TAPS <= 65535 && VECTOR_PE_COUNT >= 1 &&
        VECTOR_PE_COUNT <= SIZE && ((VECTOR_PE_COUNT & (VECTOR_PE_COUNT-1)) == 0);
    localparam bit CONV_CAPABLE = DATA_WIDTH >= 16 && (BUS_WIDTH == 32 || BUS_WIDTH == 64) && REG_WIDTH == 32 && ENABLE_PER_CHANNEL != 0;
`endif
    // The normal core promotes KERNEL_DATA_WIDTH to at least 16 even when the
    // external weight parameter is 8. Profiles without that promotion already
    // have CONV_CAPABLE=0 above; advertise the capability of the actual datapath.
    localparam bit CONV_IS_CAPABLE = CONV_CAPABLE && ENABLE_IS_MODE != 0;
    localparam bit MATRIX_LAYOUT_CAPABLE = 1'b1;
    localparam int MATRIX_R_MAX = IA_CACHE_BLOCKS < 2 ? 1 : IA_CACHE_BLOCKS/2;
    localparam int MATRIX_OUTPUT_LIMIT = (ENABLE_IS_MODE == 0 && ENABLE_PER_CHANNEL == 0) ? 16 : 32;
    localparam int MATRIX_S8_BANKS = PS_FRAME_COUNT*MATRIX_R_MAX < MATRIX_OUTPUT_LIMIT ?
        PS_FRAME_COUNT*MATRIX_R_MAX : MATRIX_OUTPUT_LIMIT;
    localparam int MATRIX_S16_BANKS = OA_S16_FIFO_BANKS_MAX == 0 || MATRIX_S8_BANKS <= OA_S16_FIFO_BANKS_MAX ?
        MATRIX_S8_BANKS : OA_S16_FIFO_BANKS_MAX;
    wire cfg_16bits_ia_reg;
    wire cfg_16x8_reg;
    wire cfg_dataflow_mode_reg;
    wire cfg_lhs_tile_packed_reg, cfg_rhs_tile_packed_reg;
    wire use_per_channel_reg;
    wire [REG_WIDTH-1:0] cfg_ia_reuse_num_reg;
    wire [REG_WIDTH-1:0] cfg_w_reuse_num_reg;
    wire [REG_WIDTH-1:0] cfg_row_groups_reg;
    wire [REG_WIDTH-1:0] cfg_row_tail_tiles_reg;
    wire [REG_WIDTH-1:0] cfg_col_groups_reg;
    wire [REG_WIDTH-1:0] cfg_col_tail_tiles_reg;
    wire [31:0] cfg_ps_control_reg;
    wire [31:0] cfg_shared_ia_banks_reg;
    wire [31:0] ps_stat_commands, ps_stat_pressure_events, ps_stat_early_finish_frames;
`ifdef GEMPACT_PS_COMPRESS
    localparam bit SHARED_CAPABLE = SHARED_IA_PS_ENABLE != 0 && SIZE == 16 && DATA_WIDTH == 16 && (BUS_WIDTH == 32 || BUS_WIDTH == 64) &&
        (SHARED_BANK_BYTES == 1024 || SHARED_BANK_BYTES == 2048 || SHARED_BANK_BYTES == 4096) &&
        SHARED_TOTAL_BYTES >= 6 * SHARED_BANK_BYTES &&
        SHARED_TOTAL_BYTES <= 9 * SHARED_BANK_BYTES &&
        SHARED_TOTAL_BYTES % SHARED_BANK_BYTES == 0;
`ifdef GEMMORA_PS_FORCE_RAW
    localparam bit PS_RAW_ONLY = 1'b1;
`elsif PS_FORCE_RAW
    localparam bit PS_RAW_ONLY = 1'b1;
`else
    localparam bit PS_RAW_ONLY = 1'b0;
`endif
    localparam logic [31:0] PS_CAPS = SIZE == 16 ?
        {8'd1, 8'(PS_FRAME_COUNT), 11'd0, SHARED_CAPABLE, PS_RAW_ONLY,
         1'(IA_COMPACT_ENABLE != 0 && DATA_WIDTH == 16), 2'b11} : 32'd0;
    localparam int unsigned PS_POOL_BYTES = SIZE == 16 ? `GEMMORA_PS_POOL_BYTES : 0;
`else
    localparam bit SHARED_CAPABLE = 1'b0;
    localparam logic [31:0] PS_CAPS = 32'd0;
    localparam int unsigned PS_POOL_BYTES = 0;
`endif
    localparam logic [31:0] SHARED_IA_BANK_MASK = SHARED_CAPABLE ?
        (32'h0000_0002 |
         ((SHARED_TOTAL_BYTES / SHARED_BANK_BYTES > 2) ? 32'h0000_0004 : 32'd0) |
         ((SHARED_TOTAL_BYTES / SHARED_BANK_BYTES > 4) ? 32'h0000_0010 : 32'd0)) : 32'd0;
    wire calc_start_pulse;
    wire npu_sa_ready;
    wire npu_done_valid;
    wire npu_done_ready;
    wire [1:0] npu_err_code;
    wire [31:0] status_bits;
    wire [NPU_ADDR_WIDTH-1:0] npu_m_axi_araddr;
    wire [NPU_ADDR_WIDTH-1:0] npu_m_axi_awaddr;
    wire npu_core_clk;
    logic [1:0] npu_clk_reset_warmup_q;
    logic npu_clk_req_q;
    logic npu_start_pending_q;
    logic npu_start_warmup_q;
    logic npu_done_seen_q;
    wire npu_clk_gate_en;
    wire npu_core_calc_start;
    wire npu_done_fire;
    wire npu_axi_idle;

    assign npu_done_fire = npu_done_valid && npu_done_ready;
    assign npu_axi_idle = !m_axi_arvalid && !m_axi_awvalid && !m_axi_wvalid &&
                          !m_axi_rready && !m_axi_bready &&
                          !m_axi_rvalid && !m_axi_bvalid;

    generate
        if (ENABLE_CLOCK_GATING != 0) begin : g_npu_clock_gate
            assign npu_clk_gate_en = (|npu_clk_reset_warmup_q) ||
                                     npu_clk_req_q ||
                                     calc_start_pulse ||
                                     npu_start_pending_q ||
                                     npu_busy ||
                                     !npu_axi_idle;
`ifdef XILINX_FPGA
            BUFGCE #(
                .SIM_DEVICE("7SERIES")
            ) u_npu_clk_bufgce (
                .I (clk),
                .CE(npu_clk_gate_en),
                .O (npu_core_clk)
            );
`elsif XILINX_CLK_WIZ_IP
            BUFGCE #(
                .SIM_DEVICE("7SERIES")
            ) u_npu_clk_bufgce (
                .I (clk),
                .CE(npu_clk_gate_en),
                .O (npu_core_clk)
            );
`else
            logic npu_clk_gate_latch;

            always_latch begin
                if (!rst_n) begin
                    npu_clk_gate_latch <= 1'b1;
                end else if (!clk) begin
                    npu_clk_gate_latch <= npu_clk_gate_en;
                end
            end

            assign npu_core_clk = clk & npu_clk_gate_latch;
`endif
        end else begin : g_npu_clock_direct
            assign npu_clk_gate_en = 1'b1;
            assign npu_core_clk = clk;
        end
    endgenerate

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            npu_clk_reset_warmup_q <= 2'b11;
            npu_clk_req_q          <= 1'b0;
            npu_start_pending_q    <= 1'b0;
            npu_start_warmup_q     <= 1'b0;
            npu_done_seen_q        <= 1'b0;
        end else begin
            npu_clk_reset_warmup_q <= {npu_clk_reset_warmup_q[0], 1'b0};

            if (calc_start_pulse) begin
                npu_clk_req_q       <= 1'b1;
                npu_start_pending_q <= 1'b1;
                npu_start_warmup_q  <= (ENABLE_CLOCK_GATING != 0);
                npu_done_seen_q     <= 1'b0;
            end else begin
                if (npu_clk_req_q) begin
                    npu_start_warmup_q <= 1'b0;
                end
                if (npu_core_calc_start) begin
                    npu_start_pending_q <= 1'b0;
                end
                if (npu_done_fire) begin
                    npu_done_seen_q <= 1'b1;
                end
                if (npu_done_seen_q && npu_sa_ready && !npu_done_valid && npu_axi_idle) begin
                    npu_clk_req_q       <= 1'b0;
                    npu_start_pending_q <= 1'b0;
                    npu_start_warmup_q  <= 1'b0;
                    npu_done_seen_q     <= 1'b0;
                end
            end
        end
    end

    assign npu_core_calc_start = (ENABLE_CLOCK_GATING != 0)
                               ? (npu_start_pending_q && !npu_start_warmup_q && npu_sa_ready)
                               : calc_start_pulse;

    generate
        if (AXI_ADDR_WIDTH > NPU_ADDR_WIDTH) begin : g_extend_npu_addr
            assign m_axi_araddr = {{(AXI_ADDR_WIDTH - NPU_ADDR_WIDTH){1'b0}}, npu_m_axi_araddr};
            assign m_axi_awaddr = {{(AXI_ADDR_WIDTH - NPU_ADDR_WIDTH){1'b0}}, npu_m_axi_awaddr};
        end else if (AXI_ADDR_WIDTH == NPU_ADDR_WIDTH) begin : g_direct_npu_addr
            assign m_axi_araddr = npu_m_axi_araddr;
            assign m_axi_awaddr = npu_m_axi_awaddr;
        end else begin : g_truncate_npu_addr
            assign m_axi_araddr = npu_m_axi_araddr[AXI_ADDR_WIDTH-1:0];
            assign m_axi_awaddr = npu_m_axi_awaddr[AXI_ADDR_WIDTH-1:0];
        end
    endgenerate

    assign m_axi_arcache = 4'b0011;
    assign m_axi_arprot  = 3'b000;
    assign m_axi_arlock  = npu_busy ? 2'b01 : 2'b00;
    assign m_axi_awcache = 4'b0011;
    assign m_axi_awprot  = 3'b000;
    assign m_axi_awlock  = npu_busy ? 2'b01 : 2'b00;

    npu_axil_reg_if #(
        .DMA_MAX_BYTES(DMA_MAX_BYTES),
        .AXI_DATA_BITS(BUS_WIDTH),
        .AXIL_DATA_WIDTH(AXIL_DATA_WIDTH),
        .AXIL_ADDR_WIDTH(AXIL_ADDR_WIDTH),
        .REG_WIDTH(REG_WIDTH), .CONV_CAPABLE(CONV_CAPABLE), .CONV_IS_CAPABLE(CONV_IS_CAPABLE),
        .VECTOR_ENGINE_CAPABLE(VECTOR_ENGINE_CAPABLE), .VECTOR_PE_COUNT(VECTOR_PE_COUNT), .DW_MAX_TAPS(DW_MAX_TAPS), .POOL_MAX_TAPS(POOL_MAX_TAPS), .SOFTMAX_MAX_DEPTH(SIZE),
        .MATRIX_SIZE(SIZE), .MATRIX_LAYOUT_CAPABLE(MATRIX_LAYOUT_CAPABLE),
        .MATRIX_IS_CAPABLE(ENABLE_IS_MODE != 0), .MATRIX_IA_CACHE_BLOCKS(IA_CACHE_BLOCKS),
        .MATRIX_PS_FRAMES(PS_FRAME_COUNT),
        .MATRIX_PS_ROWS(PS_STORAGE_ROWS != 0 ? PS_STORAGE_ROWS :
            ((((IA_CACHE_BLOCKS < 2 ? 1 : IA_CACHE_BLOCKS/2) + 1) * SIZE - 1) * (PS_FRAME_COUNT + 1))),
        .MATRIX_S8_BANKS(MATRIX_S8_BANKS), .MATRIX_S16_BANKS(MATRIX_S16_BANKS),
        .PS_CAPS(PS_CAPS), .PS_POOL_BYTES(PS_POOL_BYTES),
        .IA_CACHE_BYTES(IA_CACHE_BLOCKS * SIZE * SIZE * DATA_WIDTH / 8),
        .SHARED_TOTAL_BYTES(SHARED_CAPABLE ? SHARED_TOTAL_BYTES : 0),
        .SHARED_BANK_BYTES(SHARED_CAPABLE ? SHARED_BANK_BYTES : 0),
        .SHARED_IA_BANK_MASK(SHARED_IA_BANK_MASK),
        .PS_DIRECTORY_ROWS(SHARED_CAPABLE ? 1024 : 0)
    ) u_npu_axil_reg_if (
        .clk(clk),
        .rst_n(rst_n),
        .s_axil_awaddr(s_axil_awaddr),
        .s_axil_awprot(s_axil_awprot),
        .s_axil_awvalid(s_axil_awvalid),
        .s_axil_awready(s_axil_awready),
        .s_axil_wdata(s_axil_wdata),
        .s_axil_wstrb(s_axil_wstrb),
        .s_axil_wvalid(s_axil_wvalid),
        .s_axil_wready(s_axil_wready),
        .s_axil_bresp(s_axil_bresp),
        .s_axil_bvalid(s_axil_bvalid),
        .s_axil_bready(s_axil_bready),
        .s_axil_araddr(s_axil_araddr),
        .s_axil_arprot(s_axil_arprot),
        .s_axil_arvalid(s_axil_arvalid),
        .s_axil_arready(s_axil_arready),
        .s_axil_rdata(s_axil_rdata),
        .s_axil_rresp(s_axil_rresp),
        .s_axil_rvalid(s_axil_rvalid),
        .s_axil_rready(s_axil_rready),
        .calc_start(calc_start_pulse),
        .cfg_vector_enable(cfg_vector_enable_reg), .cfg_vector_op(cfg_vector_op_reg),
        .cfg_vector_s16(cfg_vector_s16_reg), .cfg_vector_length(cfg_vector_length_reg),
        .cfg_add_input1_multiplier(cfg_add_input1_multiplier_reg),
        .cfg_add_input1_shift(cfg_add_input1_shift_reg),
        .cfg_add_input2_multiplier(cfg_add_input2_multiplier_reg),
        .cfg_add_input2_shift(cfg_add_input2_shift_reg),
        .cfg_add_left_shift(cfg_add_left_shift_reg),
        .vector_stat_cycles(vector_stat_cycles), .vector_stat_compute(vector_stat_compute),
        .vector_stat_dma_wait(vector_stat_dma_wait),
        .cfg_16bits_ia(cfg_16bits_ia_reg),
        .cfg_conv_enable(cfg_conv_enable_reg), .cfg_conv(cfg_conv_reg),
        .conv_stat_hits(conv_stat_hits), .conv_stat_misses(conv_stat_misses),
        .conv_stat_read_bytes(conv_stat_read_bytes), .conv_stat_cycles(conv_stat_cycles),
        .cfg_16x8(cfg_16x8_reg),
        .cfg_dataflow_mode(cfg_dataflow_mode_reg),
        .cfg_lhs_tile_packed(cfg_lhs_tile_packed_reg), .cfg_rhs_tile_packed(cfg_rhs_tile_packed_reg),
        .use_per_channel(use_per_channel_reg),
        .cfg_ia_reuse_num(cfg_ia_reuse_num_reg),
        .cfg_w_reuse_num(cfg_w_reuse_num_reg),
        .cfg_row_groups(cfg_row_groups_reg),
        .cfg_row_tail_tiles(cfg_row_tail_tiles_reg),
        .cfg_col_groups(cfg_col_groups_reg),
        .cfg_col_tail_tiles(cfg_col_tail_tiles_reg),
        .cfg_ps_control(cfg_ps_control_reg),
        .cfg_shared_ia_banks(cfg_shared_ia_banks_reg),
        .ps_stat_commands(ps_stat_commands), .ps_stat_pressure_events(ps_stat_pressure_events),
        .ps_stat_early_finish_frames(ps_stat_early_finish_frames),
        .lhs_base(lhs_base_reg),
        .rhs_base(rhs_base_reg),
        .dst_base(dst_base_reg),
        .bias_base(bias_base_reg),
        .lhs_zp(lhs_zp_reg),
        .rhs_zp(rhs_zp_reg),
        .dst_zp(dst_zp_reg),
        .q_mult_pt(q_mult_pt_reg),
        .q_shift_pt(q_shift_pt_reg),
        .k(k_reg),
        .n(n_reg),
        .m(m_reg),
        .lhs_row_stride_b(lhs_row_stride_b_reg),
        .rhs_col_stride_b(rhs_col_stride_b_reg),
        .dst_row_stride_b(dst_row_stride_b_reg),
        .act_min(act_min_reg),
        .act_max(act_max_reg),
        .npu_sa_ready(npu_sa_ready),
        .npu_done_valid(npu_done_valid),
        .npu_done_ready(npu_done_ready),
        .npu_err_code(npu_err_code),
        .irq(irq),
        .npu_busy(npu_busy),
        .status_bits(status_bits)
    );

    npu_top #(
        .DMA_MAX_BYTES(DMA_MAX_BYTES),
        .SHARED_IA_PS_ENABLE(SHARED_IA_PS_ENABLE),
        .SHARED_BANK_BYTES(SHARED_BANK_BYTES),
        .SHARED_BANK_COUNT(SHARED_BANK_COUNT),
        .SHARED_TOTAL_BYTES(SHARED_TOTAL_BYTES),
        .WEIGHT_WIDTH(WEIGHT_WIDTH),
        .DATA_WIDTH(DATA_WIDTH),
        .SIZE(SIZE),
        .BUS_WIDTH(BUS_WIDTH),
        .REG_WIDTH(REG_WIDTH),
        .ADDR_WIDTH(NPU_ADDR_WIDTH),
        .IA_CACHE_BLOCKS(IA_CACHE_BLOCKS),
        .IA_COMPACT_ENABLE(IA_COMPACT_ENABLE),
        .CONV_CACHE_SETS(CONV_CACHE_SETS),
        .CONV_CACHE_WAYS(CONV_CACHE_WAYS),
        .CONV_LINE_BYTES(CONV_LINE_BYTES),
        .CONV_CACHE_POLICY(CONV_CACHE_POLICY),
        .ENABLE_VECTOR_ENGINE(ENABLE_VECTOR_ENGINE), .VECTOR_PE_COUNT(VECTOR_PE_COUNT), .DW_MAX_TAPS(DW_MAX_TAPS), .POOL_MAX_TAPS(POOL_MAX_TAPS),
        .PS_FRAME_COUNT(PS_FRAME_COUNT),
        .PS_STORAGE_ROWS(PS_STORAGE_ROWS),
        .OA_S16_FIFO_BANKS_MAX(OA_S16_FIFO_BANKS_MAX),
        .AXI_READ_OUTSTANDING(AXI_READ_OUTSTANDING),
        .AXI_WRITE_OUTSTANDING(AXI_WRITE_OUTSTANDING),
        .ENABLE_IS_MODE(ENABLE_IS_MODE),
        .ENABLE_PER_CHANNEL(ENABLE_PER_CHANNEL)
    ) u_npu_top (
        .clk(npu_core_clk),
        .rst_n(rst_n),
        .cfg_operand_fetch64(1'b0),
        .cfg_lhs_tile_packed(cfg_lhs_tile_packed_reg), .cfg_rhs_tile_packed(cfg_rhs_tile_packed_reg),
        .calc_start(npu_core_calc_start),
        .cfg_vector_enable(cfg_vector_enable_reg), .cfg_vector(cfg_vector_reg),
        .vector_stat_cycles(vector_stat_cycles), .vector_stat_compute(vector_stat_compute),
        .vector_stat_dma_wait(vector_stat_dma_wait),
        .cfg_16bits_ia(cfg_16bits_ia_reg),
        .cfg_conv_enable(cfg_conv_enable_reg), .cfg_conv(cfg_conv_reg),
        .conv_stat_hits(conv_stat_hits), .conv_stat_misses(conv_stat_misses),
        .conv_stat_read_bytes(conv_stat_read_bytes), .conv_stat_cycles(conv_stat_cycles),
        .cfg_16x8(cfg_16x8_reg),
        .cfg_dataflow_mode(cfg_dataflow_mode_reg),
        .cfg_ia_reuse_num(cfg_ia_reuse_num_reg),
        .cfg_w_reuse_num(cfg_w_reuse_num_reg),
        .cfg_row_groups(cfg_row_groups_reg),
        .cfg_row_tail_tiles(cfg_row_tail_tiles_reg),
        .cfg_col_groups(cfg_col_groups_reg),
        .cfg_col_tail_tiles(cfg_col_tail_tiles_reg),
        .cfg_ps_control(cfg_ps_control_reg),
        .cfg_shared_ia_banks(cfg_shared_ia_banks_reg),
        .ps_stat_commands(ps_stat_commands), .ps_stat_pressure_events(ps_stat_pressure_events),
        .ps_stat_early_finish_frames(ps_stat_early_finish_frames),
        .sa_ready(npu_sa_ready),
        .done_valid(npu_done_valid),
        .done_ready(npu_done_ready),
        .err_code(npu_err_code),
        .lhs_base(lhs_base_reg),
        .rhs_base(rhs_base_reg),
        .dst_base(dst_base_reg),
        .bias_base(bias_base_reg),
        .lhs_zp(lhs_zp_reg),
        .rhs_zp(rhs_zp_reg),
        .dst_zp(dst_zp_reg),
        .q_mult_pt(q_mult_pt_reg),
        .q_shift_pt(q_shift_pt_reg),
        .use_per_channel(use_per_channel_reg),
        .k(k_reg),
        .n(n_reg),
        .m(m_reg),
        .lhs_row_stride_b(lhs_row_stride_b_reg),
        .dst_row_stride_b(dst_row_stride_b_reg),
        .rhs_col_stride_b(rhs_col_stride_b_reg),
        .act_min(act_min_reg),
        .act_max(act_max_reg),
        .m_axi_arvalid(m_axi_arvalid),
        .m_axi_arready(m_axi_arready),
        .m_axi_araddr(npu_m_axi_araddr),
        .m_axi_arlen(m_axi_arlen),
        .m_axi_arsize(m_axi_arsize),
        .m_axi_arburst(m_axi_arburst),
        .m_axi_rvalid(m_axi_rvalid),
        .m_axi_rready(m_axi_rready),
        .m_axi_rdata(m_axi_rdata),
        .m_axi_rresp(m_axi_rresp),
        .m_axi_rlast(m_axi_rlast),
        .m_axi_awvalid(m_axi_awvalid),
        .m_axi_awready(m_axi_awready),
        .m_axi_awaddr(npu_m_axi_awaddr),
        .m_axi_awlen(m_axi_awlen),
        .m_axi_awsize(m_axi_awsize),
        .m_axi_awburst(m_axi_awburst),
        .m_axi_wvalid(m_axi_wvalid),
        .m_axi_wready(m_axi_wready),
        .m_axi_wdata(m_axi_wdata),
        .m_axi_wstrb(m_axi_wstrb),
        .m_axi_wlast(m_axi_wlast),
        .m_axi_bvalid(m_axi_bvalid),
        .m_axi_bready(m_axi_bready),
        .m_axi_bresp(m_axi_bresp)
    );

endmodule
