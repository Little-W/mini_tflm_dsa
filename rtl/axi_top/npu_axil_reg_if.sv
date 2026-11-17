module npu_axil_reg_if #(
    parameter int unsigned AXIL_DATA_WIDTH = 32,
    parameter int unsigned AXIL_ADDR_WIDTH = 16,
    parameter int unsigned REG_WIDTH       = 32,
    parameter int unsigned AXI_DATA_BITS = 32,
    parameter int unsigned DMA_MAX_BYTES = 256 * (AXI_DATA_BITS / 8),
    parameter bit CONV_CAPABLE = 1'b1,
    parameter bit CONV_IS_CAPABLE = 1'b0,
    parameter bit DW_POOL_CAPABLE = 1'b0,
    parameter int unsigned DW_PE_COUNT = 8,
    parameter bit VECTOR_ENGINE_CAPABLE = DW_POOL_CAPABLE,
    parameter int unsigned VECTOR_PE_COUNT = DW_PE_COUNT,
    parameter int unsigned DW_MAX_TAPS = 49,
    parameter int unsigned POOL_MAX_TAPS = 256,
    parameter int unsigned SOFTMAX_MAX_DEPTH = 16,
    parameter int unsigned MATRIX_SIZE = 16,
    parameter bit MATRIX_LAYOUT_CAPABLE = 1'b1,
    parameter bit MATRIX_IS_CAPABLE = 1'b1,
    parameter int unsigned MATRIX_IA_CACHE_BLOCKS = 4,
    parameter int unsigned MATRIX_PS_FRAMES = 16,
    parameter int unsigned MATRIX_PS_ROWS = 799,
    parameter int unsigned MATRIX_S8_BANKS = 32,
    parameter int unsigned MATRIX_S16_BANKS = 32,
    parameter logic [31:0] PS_CAPS = 0,
    parameter int unsigned PS_POOL_BYTES = 0,
    parameter int unsigned IA_CACHE_BYTES = 0,
    parameter int unsigned CONV_CACHE_BYTES = 4096,
    parameter int unsigned SHARED_TOTAL_BYTES = 0,
    parameter int unsigned SHARED_BANK_BYTES = 0,
    parameter logic [31:0] SHARED_IA_BANK_MASK = 0,
    parameter int unsigned PS_DIRECTORY_ROWS = 0
) (
    input  wire                         clk,
    input  wire                         rst_n,

    input  wire [AXIL_ADDR_WIDTH-1:0]   s_axil_awaddr,
    input  wire [2:0]                   s_axil_awprot,
    input  wire                         s_axil_awvalid,
    output wire                         s_axil_awready,
    input  wire [AXIL_DATA_WIDTH-1:0]   s_axil_wdata,
    input  wire [AXIL_DATA_WIDTH/8-1:0] s_axil_wstrb,
    input  wire                         s_axil_wvalid,
    output wire                         s_axil_wready,
    output wire [1:0]                   s_axil_bresp,
    output wire                         s_axil_bvalid,
    input  wire                         s_axil_bready,
    input  wire [AXIL_ADDR_WIDTH-1:0]   s_axil_araddr,
    input  wire [2:0]                   s_axil_arprot,
    input  wire                         s_axil_arvalid,
    output wire                         s_axil_arready,
    output wire [AXIL_DATA_WIDTH-1:0]   s_axil_rdata,
    output wire [1:0]                   s_axil_rresp,
    output wire                         s_axil_rvalid,
    input  wire                         s_axil_rready,

    output logic                        calc_start,
    output logic                        cfg_conv_enable,
    output logic                        cfg_vector_enable,
    output logic [3:0]                  cfg_vector_op,
    output logic                        cfg_vector_s16,
    output logic [31:0]                 cfg_vector_length,
    output logic signed [31:0]          cfg_add_input1_multiplier,
    output logic signed [31:0]          cfg_add_input1_shift,
    output logic signed [31:0]          cfg_add_input2_multiplier,
    output logic signed [31:0]          cfg_add_input2_shift,
    output logic signed [31:0]          cfg_add_left_shift,
    input logic [31:0] vector_stat_cycles = '0,
    input logic [31:0] vector_stat_compute = '0,
    input logic [31:0] vector_stat_dma_wait = '0,
    output conv_im2col_pkg::conv_cfg_t    cfg_conv,
    input logic [31:0] conv_stat_hits = '0,
    input logic [31:0] conv_stat_misses = '0,
    input logic [31:0] conv_stat_read_bytes = '0,
    input logic [31:0] conv_stat_cycles = '0,
    output logic                        cfg_16bits_ia,
    output logic                        cfg_16x8,
    output logic                        cfg_dataflow_mode,
    output logic                        cfg_lhs_tile_packed,
    output logic                        cfg_rhs_tile_packed,
    output logic                        use_per_channel,
    output logic [REG_WIDTH-1:0]        cfg_ia_reuse_num,
    output logic [REG_WIDTH-1:0]        cfg_w_reuse_num,
    output logic [REG_WIDTH-1:0] cfg_row_groups,
    output logic [REG_WIDTH-1:0] cfg_row_tail_tiles,
    output logic [REG_WIDTH-1:0] cfg_col_groups,
    output logic [REG_WIDTH-1:0] cfg_col_tail_tiles,
    output logic [31:0] cfg_ps_control,
    output logic [31:0] cfg_shared_ia_banks,
    input logic [31:0] ps_stat_commands = 32'd0,
    input logic [31:0] ps_stat_pressure_events = 32'd0,
    input logic [31:0] ps_stat_early_finish_frames = 32'd0,

    output logic [REG_WIDTH-1:0]        lhs_base,
    output logic [REG_WIDTH-1:0]        rhs_base,
    output logic [REG_WIDTH-1:0]        dst_base,
    output logic [REG_WIDTH-1:0]        bias_base,
    output logic signed [REG_WIDTH-1:0] lhs_zp,
    output logic signed [REG_WIDTH-1:0] rhs_zp,
    output logic signed [REG_WIDTH-1:0] dst_zp,
    output logic signed [REG_WIDTH-1:0] q_mult_pt,
    output logic signed [REG_WIDTH-1:0] q_shift_pt,
    output logic [REG_WIDTH-1:0]        k,
    output logic [REG_WIDTH-1:0]        n,
    output logic [REG_WIDTH-1:0]        m,
    output logic [REG_WIDTH-1:0]        lhs_row_stride_b,
    output logic [REG_WIDTH-1:0]        rhs_col_stride_b,
    output logic [REG_WIDTH-1:0]        dst_row_stride_b,
    output logic signed [REG_WIDTH-1:0] act_min,
    output logic signed [REG_WIDTH-1:0] act_max,

    input  wire                         npu_sa_ready,
    input  wire                         npu_done_valid,
    output wire                         npu_done_ready,
    input  wire [1:0]                   npu_err_code,

    output wire                         irq,
    output wire                         npu_busy,
    output wire [31:0]                  status_bits
);

    localparam int unsigned STRB_WIDTH = AXIL_DATA_WIDTH / 8;

    localparam logic [11:0] REG_CTRL         = 12'h000; // 0x000
    localparam logic [11:0] REG_STATUS       = 12'h001; // 0x004
    localparam logic [11:0] REG_WB_DATA      = 12'h002; // 0x008
    localparam logic [11:0] REG_LHS_BASE     = 12'h004; // 0x010
    localparam logic [11:0] REG_RHS_BASE     = 12'h005; // 0x014
    localparam logic [11:0] REG_DST_BASE     = 12'h006; // 0x018
    localparam logic [11:0] REG_BIAS_BASE    = 12'h007; // 0x01c
    localparam logic [11:0] REG_K            = 12'h008; // 0x020
    localparam logic [11:0] REG_N            = 12'h009; // 0x024
    localparam logic [11:0] REG_M            = 12'h00a; // 0x028
    localparam logic [11:0] REG_LHS_STRIDE_B = 12'h00b; // 0x02c
    localparam logic [11:0] REG_RHS_STRIDE_B = 12'h00c; // 0x030
    localparam logic [11:0] REG_DST_STRIDE_B = 12'h00d; // 0x034
    localparam logic [11:0] REG_LHS_ZP       = 12'h00e; // 0x038
    localparam logic [11:0] REG_RHS_ZP       = 12'h00f; // 0x03c
    localparam logic [11:0] REG_DST_ZP       = 12'h010; // 0x040
    localparam logic [11:0] REG_Q_MULT       = 12'h011; // 0x044
    localparam logic [11:0] REG_Q_SHIFT      = 12'h012; // 0x048
    localparam logic [11:0] REG_ACT_MIN      = 12'h013; // 0x04c
    localparam logic [11:0] REG_ACT_MAX      = 12'h014; // 0x050
    localparam logic [11:0] REG_IA_REUSE     = 12'h015; // 0x054
    localparam logic [11:0] REG_W_REUSE      = 12'h016; // 0x058
    localparam logic [11:0] REG_DATAFLOW     = 12'h017; // 0x05c
    localparam logic [11:0] REG_ROW_GROUPS = 12'h018; // 0x060
    localparam logic [11:0] REG_ROW_TAIL_TILES = 12'h019; // 0x064
    localparam logic [11:0] REG_COL_GROUPS = 12'h01a; // 0x068
    localparam logic [11:0] REG_COL_TAIL_TILES = 12'h01b; // 0x06c
    localparam logic [11:0] REG_CONFIG_ABI = 12'h01c; // 0x070, read-only
    localparam logic [11:0] REG_VECTOR_OP = 12'h02c;
    localparam logic [11:0] REG_VECTOR_LENGTH = 12'h02d;
    localparam logic [11:0] REG_VECTOR_CAPS = 12'h02e;
    localparam logic [11:0] REG_VECTOR_CYCLES = 12'h02f;
    localparam logic [11:0] REG_VECTOR_COMPUTE = 12'h030;
    localparam logic [11:0] REG_VECTOR_DMA_WAIT = 12'h031;
    localparam logic [11:0] REG_POOL_MAX_TAPS = 12'h032; // 0x0c8, read-only
    localparam logic [11:0] REG_ADD_INPUT1_MULT = 12'h033; // 0x0cc
    localparam logic [11:0] REG_ADD_INPUT1_SHIFT = 12'h034; // 0x0d0
    localparam logic [11:0] REG_ADD_INPUT2_MULT = 12'h035; // 0x0d4
    localparam logic [11:0] REG_ADD_INPUT2_SHIFT = 12'h036; // 0x0d8
    localparam logic [11:0] REG_ADD_LEFT_SHIFT = 12'h037; // 0x0dc
    localparam logic [11:0] REG_SOFTMAX_MAX_DEPTH = 12'h038; // 0x0e0, read-only
    localparam logic [11:0] REG_MATRIX_CAPS = 12'h039; // 0x0e4, read-only
    localparam logic [11:0] REG_MATRIX_PS_ROWS = 12'h03a; // 0x0e8, read-only
    localparam logic [11:0] REG_MATRIX_OUTPUT_BANKS = 12'h03b; // 0x0ec, read-only
    localparam logic [11:0] REG_DMA_MAX_BYTES = 12'h03c; // 0x0f0, read-only
    localparam logic [11:0] REG_AXI_DATA_BITS = 12'h03d; // 0x0f4, read-only
    localparam logic [11:0] REG_PS_CONTROL = 12'h048;
    localparam logic [11:0] REG_PS_CAPS = 12'h049;
    localparam logic [11:0] REG_PS_COMMANDS = 12'h04a;
    localparam logic [11:0] REG_PS_PRESSURE = 12'h04b;
    localparam logic [11:0] REG_PS_EARLY_FINISH = 12'h04c;
    localparam logic [11:0] REG_PS_POOL_BYTES = 12'h04d;
    localparam logic [11:0] REG_IA_CACHE_BYTES = 12'h04e;
    localparam logic [11:0] REG_IM2COL_CACHE_BYTES = 12'h04f; // 0x13c, read-only
    localparam logic [11:0] REG_ID           = 12'h03f; // 0x0fc
    localparam logic [11:0] REG_SHARED_TOTAL_BYTES = 12'h040;
    localparam logic [11:0] REG_SHARED_BANK_BYTES = 12'h041;
    localparam logic [11:0] REG_SHARED_IA_BANKS = 12'h042;
    localparam logic [11:0] REG_SHARED_IA_BANK_MASK = 12'h043;
    localparam logic [11:0] REG_PS_DIRECTORY_ROWS = 12'h044;
    localparam logic [REG_WIDTH-1:0] NPU_ID  = 32'h4e50_5531;
    localparam bit SHARED_CAPABLE = PS_CAPS[4] &&
        (SHARED_BANK_BYTES == 2048 || SHARED_BANK_BYTES == 4096 || SHARED_BANK_BYTES == 8192) &&
        SHARED_TOTAL_BYTES >= 6 * SHARED_BANK_BYTES &&
        SHARED_TOTAL_BYTES <= 9 * SHARED_BANK_BYTES &&
        SHARED_TOTAL_BYTES % SHARED_BANK_BYTES == 0 && SHARED_IA_BANK_MASK[1];

    logic [AXIL_ADDR_WIDTH-1:0] awaddr_q;
    logic                       awvalid_q;
    logic [AXIL_DATA_WIDTH-1:0] wdata_q;
    logic [STRB_WIDTH-1:0]      wstrb_q;
    logic                       wvalid_q;
    logic                       bvalid_q;
    logic [1:0] bresp_q;
    logic [AXIL_DATA_WIDTH-1:0] rdata_q;
    logic                       rvalid_q;

    logic [REG_WIDTH-1:0]       last_done_data;
    logic                       irq_enable;
    logic                       done_sticky;
    logic                       npu_busy_q;
    logic [1:0] last_err_code;

    wire aw_accept = s_axil_awvalid && s_axil_awready;
    wire w_accept  = s_axil_wvalid  && s_axil_wready;
    wire ar_accept = s_axil_arvalid && s_axil_arready;

    wire [AXIL_ADDR_WIDTH-1:0] wr_addr = awaddr_q;
    wire [AXIL_DATA_WIDTH-1:0] wr_data = wdata_q;
    wire [STRB_WIDTH-1:0]      wr_strb = wstrb_q;
    wire write_commit = !bvalid_q && awvalid_q && wvalid_q;

    wire [11:0] wr_word_addr = wr_addr[13:2];
    wire [11:0] rd_word_addr = s_axil_araddr[13:2];
    wire ctrl_start_commit = write_commit && !npu_busy_q && npu_sa_ready && (wr_word_addr == REG_CTRL) && wr_strb[0] && wr_data[0];

    logic [AXIL_DATA_WIDTH-1:0] read_data_next;
    wire [31:0] shared_ia_banks_next = apply_wstrb(cfg_shared_ia_banks, wr_data, wr_strb);
    wire shared_allocation_valid = SHARED_CAPABLE && shared_ia_banks_next < 32 &&
        SHARED_IA_BANK_MASK[shared_ia_banks_next[4:0]];

    assign s_axil_awready = !awvalid_q && !bvalid_q;
    assign s_axil_wready  = !wvalid_q && !bvalid_q;
    assign s_axil_bresp   = bresp_q;
    assign s_axil_bvalid  = bvalid_q;

    assign s_axil_arready = !rvalid_q;
    assign s_axil_rdata   = rdata_q;
    assign s_axil_rresp   = 2'b00;
    assign s_axil_rvalid  = rvalid_q;

    assign npu_done_ready = 1'b1;
    assign npu_busy = npu_busy_q;
    assign irq = done_sticky && irq_enable;
    assign status_bits = {26'b0, 1'b1, last_err_code,
                          done_sticky, npu_busy_q, npu_sa_ready};

    function automatic [REG_WIDTH-1:0] apply_wstrb(
        input [REG_WIDTH-1:0] old_data,
        input [AXIL_DATA_WIDTH-1:0] new_data,
        input [STRB_WIDTH-1:0] strb
    );
        integer byte_idx;
        begin
            apply_wstrb = old_data;
            for (byte_idx = 0; byte_idx < (REG_WIDTH / 8); byte_idx = byte_idx + 1) begin
                if (strb[byte_idx]) begin
                    apply_wstrb[byte_idx*8 +: 8] = new_data[byte_idx*8 +: 8];
                end
            end
        end
    endfunction

    always_comb begin
        read_data_next = '0;
        case (rd_word_addr)
            REG_CTRL: begin
                read_data_next[10:9] = {cfg_rhs_tile_packed, cfg_lhs_tile_packed};
                read_data_next[8] = cfg_vector_enable;
                read_data_next[7:1] = {cfg_conv.bypass_cache, cfg_conv_enable, cfg_16x8, irq_enable, cfg_dataflow_mode,
                                       use_per_channel, cfg_16bits_ia};
            end
            REG_VECTOR_OP: read_data_next = {23'b0, cfg_vector_s16, 4'b0, cfg_vector_op};
            REG_MATRIX_CAPS: read_data_next = {8'(MATRIX_SIZE), 8'(MATRIX_PS_FRAMES),
                                               8'(MATRIX_IA_CACHE_BLOCKS),
                                               8'((MATRIX_LAYOUT_CAPABLE ? 3 : 0) |
                                                  (MATRIX_IS_CAPABLE ? 4 : 0))};
            REG_MATRIX_PS_ROWS: read_data_next = MATRIX_PS_ROWS;
            REG_MATRIX_OUTPUT_BANKS: read_data_next = {16'(MATRIX_S16_BANKS), 16'(MATRIX_S8_BANKS)};
            REG_DMA_MAX_BYTES: read_data_next = DMA_MAX_BYTES;
            REG_AXI_DATA_BITS: read_data_next = AXI_DATA_BITS;
            REG_VECTOR_LENGTH: read_data_next = cfg_vector_length;
            REG_VECTOR_CAPS: read_data_next = VECTOR_ENGINE_CAPABLE ?
                {8'd1, 8'(DW_MAX_TAPS), 8'(VECTOR_PE_COUNT), 8'h7f} : 32'd0;
            REG_VECTOR_CYCLES: read_data_next = vector_stat_cycles;
            REG_VECTOR_COMPUTE: read_data_next = vector_stat_compute;
            REG_VECTOR_DMA_WAIT: read_data_next = vector_stat_dma_wait;
            REG_SOFTMAX_MAX_DEPTH: read_data_next = VECTOR_ENGINE_CAPABLE ? 32'(SOFTMAX_MAX_DEPTH) : 32'd0;
            REG_POOL_MAX_TAPS: read_data_next = VECTOR_ENGINE_CAPABLE ? 32'(POOL_MAX_TAPS) : 32'd0;
            REG_ADD_INPUT1_MULT: read_data_next = cfg_add_input1_multiplier;
            REG_ADD_INPUT1_SHIFT: read_data_next = cfg_add_input1_shift;
            REG_ADD_INPUT2_MULT: read_data_next = cfg_add_input2_multiplier;
            REG_ADD_INPUT2_SHIFT: read_data_next = cfg_add_input2_shift;
            REG_ADD_LEFT_SHIFT: read_data_next = cfg_add_left_shift;
            REG_STATUS:       read_data_next[7:0] = status_bits[7:0];
            REG_WB_DATA:      read_data_next = last_done_data;
            REG_LHS_BASE:     read_data_next = lhs_base;
            REG_RHS_BASE:     read_data_next = rhs_base;
            REG_DST_BASE:     read_data_next = dst_base;
            REG_BIAS_BASE:    read_data_next = bias_base;
            REG_K:            read_data_next = k;
            REG_N:            read_data_next = n;
            REG_M:            read_data_next = m;
            REG_LHS_STRIDE_B: read_data_next = lhs_row_stride_b;
            REG_RHS_STRIDE_B: read_data_next = rhs_col_stride_b;
            REG_DST_STRIDE_B: read_data_next = dst_row_stride_b;
            REG_LHS_ZP:       read_data_next = lhs_zp;
            REG_RHS_ZP:       read_data_next = rhs_zp;
            REG_DST_ZP:       read_data_next = dst_zp;
            REG_Q_MULT:       read_data_next = q_mult_pt;
            REG_Q_SHIFT:      read_data_next = q_shift_pt;
            REG_ACT_MIN:      read_data_next = act_min;
            REG_ACT_MAX:      read_data_next = act_max;
            REG_IA_REUSE:     read_data_next = cfg_ia_reuse_num;
            REG_W_REUSE:      read_data_next = cfg_w_reuse_num;
            REG_DATAFLOW:     read_data_next[0] = cfg_dataflow_mode;
            REG_ROW_GROUPS: read_data_next = cfg_row_groups;
            REG_ROW_TAIL_TILES: read_data_next = cfg_row_tail_tiles;
            REG_COL_GROUPS: read_data_next = cfg_col_groups;
            REG_COL_TAIL_TILES: read_data_next = cfg_col_tail_tiles;
            REG_CONFIG_ABI: read_data_next = 32'd2;
            REG_PS_CONTROL: read_data_next = cfg_ps_control;
            REG_PS_CAPS: read_data_next = PS_CAPS;
            REG_PS_COMMANDS: read_data_next = ps_stat_commands;
            REG_PS_PRESSURE: read_data_next = ps_stat_pressure_events;
            REG_PS_EARLY_FINISH: read_data_next = ps_stat_early_finish_frames;
            REG_PS_POOL_BYTES: read_data_next = SHARED_CAPABLE ?
                32'(SHARED_TOTAL_BYTES) - cfg_shared_ia_banks * 32'(SHARED_BANK_BYTES) : 32'(PS_POOL_BYTES);
            REG_IA_CACHE_BYTES: read_data_next = SHARED_CAPABLE ?
                cfg_shared_ia_banks * 32'(SHARED_BANK_BYTES) : 32'(IA_CACHE_BYTES);
            REG_IM2COL_CACHE_BYTES: read_data_next = CONV_CAPABLE ? 32'(CONV_CACHE_BYTES) : 32'd0;
            REG_SHARED_TOTAL_BYTES: read_data_next = SHARED_CAPABLE ? 32'(SHARED_TOTAL_BYTES) : 32'd0;
            REG_SHARED_BANK_BYTES: read_data_next = SHARED_CAPABLE ? 32'(SHARED_BANK_BYTES) : 32'd0;
            REG_SHARED_IA_BANKS: read_data_next = cfg_shared_ia_banks;
            REG_SHARED_IA_BANK_MASK: read_data_next = SHARED_CAPABLE ? SHARED_IA_BANK_MASK : 32'd0;
            REG_PS_DIRECTORY_ROWS: read_data_next = SHARED_CAPABLE ? 32'(PS_DIRECTORY_ROWS) : 32'd0;
            12'h01d: read_data_next = cfg_conv.input_base;
            12'h01e: read_data_next = {cfg_conv.input_w, cfg_conv.input_h};
            12'h01f: read_data_next = {cfg_conv.group_c, cfg_conv.input_c};
            12'h020: read_data_next = {16'b0, cfg_conv.group_offset};
            12'h021: read_data_next = {cfg_conv.kernel_w, cfg_conv.kernel_h};
            12'h022: read_data_next = {cfg_conv.output_w, cfg_conv.output_h};
            12'h023: read_data_next = {cfg_conv.stride_w, cfg_conv.stride_h};
            12'h024: read_data_next = {cfg_conv.dilation_w, cfg_conv.dilation_h};
            12'h025: read_data_next = {cfg_conv.pad_left, cfg_conv.pad_top};
            12'h026: read_data_next = {{16{cfg_conv.input_offset[15]}}, cfg_conv.input_offset};
            12'h027: read_data_next = CONV_CAPABLE ?
                (32'h0001_0003 | (CONV_IS_CAPABLE ? 32'h0000_0004 : 32'b0)) : 32'b0;
            12'h028: read_data_next = conv_stat_hits;
            12'h029: read_data_next = conv_stat_misses;
            12'h02a: read_data_next = conv_stat_read_bytes;
            12'h02b: read_data_next = conv_stat_cycles;
            REG_ID:           read_data_next = NPU_ID;
            default: begin
            end
        endcase
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            awaddr_q            <= '0;
            awvalid_q           <= 1'b0;
            wdata_q             <= '0;
            wstrb_q             <= '0;
            wvalid_q            <= 1'b0;
            bvalid_q            <= 1'b0;
            bresp_q             <= 2'b00;
            rdata_q             <= '0;
            rvalid_q            <= 1'b0;
            lhs_base            <= '0;
            rhs_base            <= '0;
            dst_base            <= '0;
            bias_base           <= '0;
            k                   <= '0;
            n                   <= '0;
            m                   <= '0;
            lhs_row_stride_b    <= '0;
            rhs_col_stride_b    <= '0;
            dst_row_stride_b    <= '0;
            lhs_zp              <= '0;
            rhs_zp              <= '0;
            dst_zp              <= '0;
            q_mult_pt           <= '0;
            q_shift_pt          <= '0;
            act_min             <= '0;
            act_max             <= '0;
            cfg_16bits_ia       <= 1'b0;
            cfg_conv_enable     <= 1'b0;
            cfg_vector_enable       <= 1'b0;
            cfg_vector_op           <= '0;
            cfg_vector_s16   <= 1'b0;
            cfg_vector_length       <= '0;
            cfg_add_input1_multiplier <= '0;
            cfg_add_input1_shift <= '0;
            cfg_add_input2_multiplier <= '0;
            cfg_add_input2_shift <= '0;
            cfg_add_left_shift <= '0;
            cfg_conv            <= '0;
            cfg_conv.windowed <= 1'b1;
            cfg_conv.prefetch_enable <= 1'b1;
            last_err_code       <= '0;
            cfg_16x8            <= 1'b0;
            cfg_dataflow_mode   <= 1'b0;
            cfg_lhs_tile_packed <= 1'b0;
            cfg_rhs_tile_packed <= 1'b0;
            use_per_channel     <= 1'b0;
            irq_enable          <= 1'b0;
            cfg_ia_reuse_num    <= '0;
            cfg_w_reuse_num     <= '0;
            cfg_row_groups <= '0;
            cfg_row_tail_tiles <= '0;
            cfg_col_groups <= '0;
            cfg_col_tail_tiles <= '0;
            cfg_ps_control <= '0;
            cfg_shared_ia_banks <= SHARED_CAPABLE ? 32'd1 : 32'd0;
            calc_start          <= 1'b0;
            npu_busy_q          <= 1'b0;
            done_sticky         <= 1'b0;
            last_done_data      <= '0;
        end else begin
            calc_start <= 1'b0;

            if (s_axil_bready && bvalid_q) begin
                bvalid_q <= 1'b0;
            end

            if (aw_accept) begin
                awaddr_q  <= s_axil_awaddr;
                awvalid_q <= 1'b1;
            end

            if (w_accept) begin
                wdata_q  <= s_axil_wdata;
                wstrb_q  <= s_axil_wstrb;
                wvalid_q <= 1'b1;
            end

            if (write_commit) begin
                awvalid_q <= 1'b0;
                wvalid_q  <= 1'b0;
                bvalid_q  <= 1'b1;

                // Reject configuration changes and duplicate starts while a
                // task is active. STATUS W1C remains available during execution.
                bresp_q <= 2'b00;
                if (npu_busy_q && wr_word_addr != REG_STATUS) begin
                    bresp_q <= 2'b10;
                end else if (wr_word_addr == REG_CTRL && wr_strb[0] && wr_data[0] && !npu_sa_ready) begin
                    bresp_q <= 2'b10;
                end else case (wr_word_addr)
                    REG_CTRL: begin
                        if (wr_strb[1]) begin
                            cfg_vector_enable <= wr_data[8];
                            cfg_lhs_tile_packed <= wr_data[9];
                            cfg_rhs_tile_packed <= wr_data[10];
                        end
                        if (wr_strb[0]) begin
                            cfg_16bits_ia     <= wr_data[1];
                            use_per_channel   <= wr_data[2];
                            cfg_dataflow_mode <= wr_data[3];
                            irq_enable        <= wr_data[4];
                            cfg_16x8           <= wr_data[5];
                            cfg_conv_enable     <= wr_data[6];
                            cfg_conv.bypass_cache <= wr_data[7];
                            if (wr_data[0]) begin
                                calc_start    <= 1'b1;
                                npu_busy_q    <= 1'b1;
                                done_sticky   <= 1'b0;
                                last_err_code <= 2'b00;
                            end
                        end
                    end
                    REG_VECTOR_OP: begin
                        if (wr_strb[0]) cfg_vector_op <= wr_data[3:0];
                        if (wr_strb[1]) cfg_vector_s16 <= wr_data[8];
                    end
                    REG_VECTOR_LENGTH: cfg_vector_length <= apply_wstrb(cfg_vector_length, wr_data, wr_strb);
                    REG_ADD_INPUT1_MULT: cfg_add_input1_multiplier <= apply_wstrb(cfg_add_input1_multiplier, wr_data, wr_strb);
                    REG_ADD_INPUT1_SHIFT: cfg_add_input1_shift <= apply_wstrb(cfg_add_input1_shift, wr_data, wr_strb);
                    REG_ADD_INPUT2_MULT: cfg_add_input2_multiplier <= apply_wstrb(cfg_add_input2_multiplier, wr_data, wr_strb);
                    REG_ADD_INPUT2_SHIFT: cfg_add_input2_shift <= apply_wstrb(cfg_add_input2_shift, wr_data, wr_strb);
                    REG_ADD_LEFT_SHIFT: cfg_add_left_shift <= apply_wstrb(cfg_add_left_shift, wr_data, wr_strb);
                    REG_STATUS: begin
                        if (wr_strb[0]) begin
                            if (wr_data[2]) begin
                                done_sticky <= 1'b0;
                            end
                        end
                    end
                    REG_LHS_BASE:     lhs_base <= apply_wstrb(lhs_base, wr_data, wr_strb);
                    REG_RHS_BASE:     rhs_base <= apply_wstrb(rhs_base, wr_data, wr_strb);
                    REG_DST_BASE:     dst_base <= apply_wstrb(dst_base, wr_data, wr_strb);
                    REG_BIAS_BASE:    bias_base <= apply_wstrb(bias_base, wr_data, wr_strb);
                    REG_K:            k <= apply_wstrb(k, wr_data, wr_strb);
                    REG_N:            n <= apply_wstrb(n, wr_data, wr_strb);
                    REG_M:            m <= apply_wstrb(m, wr_data, wr_strb);
                    REG_LHS_STRIDE_B: lhs_row_stride_b <= apply_wstrb(lhs_row_stride_b, wr_data, wr_strb);
                    REG_RHS_STRIDE_B: rhs_col_stride_b <= apply_wstrb(rhs_col_stride_b, wr_data, wr_strb);
                    REG_DST_STRIDE_B: dst_row_stride_b <= apply_wstrb(dst_row_stride_b, wr_data, wr_strb);
                    REG_LHS_ZP:       lhs_zp <= apply_wstrb(lhs_zp, wr_data, wr_strb);
                    REG_RHS_ZP:       rhs_zp <= apply_wstrb(rhs_zp, wr_data, wr_strb);
                    REG_DST_ZP:       dst_zp <= apply_wstrb(dst_zp, wr_data, wr_strb);
                    REG_Q_MULT:       q_mult_pt <= apply_wstrb(q_mult_pt, wr_data, wr_strb);
                    REG_Q_SHIFT:      q_shift_pt <= apply_wstrb(q_shift_pt, wr_data, wr_strb);
                    REG_ACT_MIN:      act_min <= apply_wstrb(act_min, wr_data, wr_strb);
                    REG_ACT_MAX:      act_max <= apply_wstrb(act_max, wr_data, wr_strb);
                    REG_IA_REUSE:     cfg_ia_reuse_num <= apply_wstrb(cfg_ia_reuse_num, wr_data, wr_strb);
                    REG_W_REUSE:      cfg_w_reuse_num <= apply_wstrb(cfg_w_reuse_num, wr_data, wr_strb);
                    REG_ROW_GROUPS: cfg_row_groups <= apply_wstrb(cfg_row_groups, wr_data, wr_strb);
                    REG_ROW_TAIL_TILES: cfg_row_tail_tiles <= apply_wstrb(cfg_row_tail_tiles, wr_data, wr_strb);
                    REG_COL_GROUPS: cfg_col_groups <= apply_wstrb(cfg_col_groups, wr_data, wr_strb);
                    REG_COL_TAIL_TILES: cfg_col_tail_tiles <= apply_wstrb(cfg_col_tail_tiles, wr_data, wr_strb);
                    REG_PS_CONTROL: cfg_ps_control <= apply_wstrb(cfg_ps_control, wr_data, wr_strb);
                    REG_SHARED_IA_BANKS: begin
                        if (shared_allocation_valid) cfg_shared_ia_banks <= shared_ia_banks_next;
                        else bresp_q <= 2'b10;
                    end
                    12'h01d: cfg_conv.input_base <= apply_wstrb(cfg_conv.input_base, wr_data, wr_strb);
                    12'h01e: {cfg_conv.input_w,cfg_conv.input_h} <= apply_wstrb({cfg_conv.input_w,cfg_conv.input_h}, wr_data, wr_strb);
                    12'h01f: {cfg_conv.group_c,cfg_conv.input_c} <= apply_wstrb({cfg_conv.group_c,cfg_conv.input_c}, wr_data, wr_strb);
                    12'h020: cfg_conv.group_offset <= 16'(apply_wstrb({16'b0,cfg_conv.group_offset}, wr_data, wr_strb));
                    12'h021: {cfg_conv.kernel_w,cfg_conv.kernel_h} <= apply_wstrb({cfg_conv.kernel_w,cfg_conv.kernel_h}, wr_data, wr_strb);
                    12'h022: {cfg_conv.output_w,cfg_conv.output_h} <= apply_wstrb({cfg_conv.output_w,cfg_conv.output_h}, wr_data, wr_strb);
                    12'h023: {cfg_conv.stride_w,cfg_conv.stride_h} <= apply_wstrb({cfg_conv.stride_w,cfg_conv.stride_h}, wr_data, wr_strb);
                    12'h024: {cfg_conv.dilation_w,cfg_conv.dilation_h} <= apply_wstrb({cfg_conv.dilation_w,cfg_conv.dilation_h}, wr_data, wr_strb);
                    12'h025: {cfg_conv.pad_left,cfg_conv.pad_top} <= apply_wstrb({cfg_conv.pad_left,cfg_conv.pad_top}, wr_data, wr_strb);
                    12'h026: cfg_conv.input_offset <= 16'(apply_wstrb({{16{cfg_conv.input_offset[15]}},cfg_conv.input_offset}, wr_data, wr_strb));
                    REG_DATAFLOW: begin
                        if (wr_strb[0]) begin
                            cfg_dataflow_mode <= wr_data[0];
                        end
                    end
                    default: begin
                    end
                endcase
            end

            if (rvalid_q && s_axil_rready) begin
                rvalid_q <= 1'b0;
            end

            if (ar_accept) begin
                rdata_q  <= read_data_next;
                rvalid_q <= 1'b1;
            end

            if (calc_start) begin
                npu_busy_q <= 1'b1;
            end

            if (npu_done_valid && npu_done_ready && !ctrl_start_commit) begin
                npu_busy_q    <= 1'b0;
                done_sticky   <= 1'b1;
                last_done_data <= {{(REG_WIDTH-2){1'b0}}, npu_err_code};
                last_err_code <= npu_err_code;
            end
        end
    end

    wire unused_axil_prot = ^{s_axil_awprot, s_axil_arprot};

endmodule
