/* 实现 AXI 突发读写存储器，处理字节使能、返回状态及仿真数据初始化。 */ module soc_axi_ram #(
    parameter int unsigned DP = 512,
    parameter int unsigned DW = 32,
    parameter int unsigned AW = 32,
    parameter string       MEM_PATH = "",
    parameter int unsigned MEM_WORD_WIDTH = DW,
    parameter int unsigned INIT_EN = 0,
    parameter int unsigned READ_OUTSTANDING = 4,
    parameter int unsigned WRITE_OUTSTANDING = READ_OUTSTANDING,
    parameter int unsigned READ_FIRST_LATENCY = 2
) (
    input  wire             clk /* 模块工作时钟。 */,
    input  wire             rst_n /* 低电平有效复位。 */,

    input  wire             s_axi_awvalid /* AXI 从接口的写地址有效。 */,
    output wire             s_axi_awready /* AXI 从接口的可接收写地址。 */,
    input  wire [AW-1:0]    s_axi_awaddr /* AXI 从接口的写地址。 */,
    input  wire [3:0]       s_axi_awcache /* AXI 从接口的写事务缓存属性。 */,
    input  wire [2:0]       s_axi_awprot /* AXI 从接口的写访问保护属性。 */,
    input  wire [1:0]       s_axi_awlock /* AXI 从接口的写事务锁定属性。 */,
    input  wire [1:0]       s_axi_awburst /* AXI 从接口的写突发地址模式。 */,
    input  wire [7:0]       s_axi_awlen /* AXI 从接口的写突发拍数减一。 */,
    input  wire [2:0]       s_axi_awsize /* AXI 从接口的写入每拍字节数的以二为底对数。 */,

    input  wire             s_axi_wvalid /* AXI 从接口的写数据有效。 */,
    output wire             s_axi_wready /* AXI 从接口的可接收写数据。 */,
    input  wire [DW-1:0]    s_axi_wdata /* AXI 从接口的写入数据。 */,
    input  wire [DW/8-1:0]  s_axi_wstrb /* AXI 从接口的写入字节使能。 */,
    input  wire             s_axi_wlast /* AXI 从接口的写突发的最后一拍。 */,

    output logic            s_axi_bvalid /* AXI 从接口的写响应有效。 */,
    input  wire             s_axi_bready /* AXI 从接口的可接收写响应。 */,
    output logic [1:0]      s_axi_bresp /* AXI 从接口的写响应状态。 */,

    input  wire             s_axi_arvalid /* AXI 从接口的读地址有效。 */,
    output wire             s_axi_arready /* AXI 从接口的可接收读地址。 */,
    input  wire [AW-1:0]    s_axi_araddr /* AXI 从接口的读地址。 */,
    input  wire [3:0]       s_axi_arcache /* AXI 从接口的读事务缓存属性。 */,
    input  wire [2:0]       s_axi_arprot /* AXI 从接口的读访问保护属性。 */,
    input  wire [1:0]       s_axi_arlock /* AXI 从接口的读事务锁定属性。 */,
    input  wire [1:0]       s_axi_arburst /* AXI 从接口的读突发地址模式。 */,
    input  wire [7:0]       s_axi_arlen /* AXI 从接口的读突发拍数减一。 */,
    input  wire [2:0]       s_axi_arsize /* AXI 从接口的读取每拍字节数的以二为底对数。 */,

    output logic            s_axi_rvalid /* AXI 从接口的读响应有效。 */,
    input  wire             s_axi_rready /* AXI 从接口的可接收读响应。 */,
    output logic [DW-1:0]   s_axi_rdata /* AXI 从接口的读取数据。 */,
    output logic [1:0]      s_axi_rresp /* AXI 从接口的读响应状态。 */,
    output logic            s_axi_rlast /* AXI 从接口的读突发的最后一拍。 */,

    input  wire             mem_reload_req /* 仿真存储初始化数据的重载请求。 */
);

    localparam int unsigned BYTEW = DW / 8;
    localparam int unsigned ADDR_LSB = (BYTEW <= 1) ? 0 : $clog2(BYTEW);
    localparam int unsigned ADDR_BITS = (DP <= 1) ? 1 : $clog2(DP);
    localparam int unsigned WORD_ADDR_BITS = AW - ADDR_LSB;
    localparam int unsigned RD_DEPTH = (READ_OUTSTANDING < 1) ? 1 : READ_OUTSTANDING;
    localparam int unsigned WR_DEPTH = (WRITE_OUTSTANDING < 1) ? 1 : WRITE_OUTSTANDING;
    localparam int unsigned RD_PTR_W = (RD_DEPTH < 2) ? 1 : $clog2(RD_DEPTH);
    localparam int unsigned WR_PTR_W = (WR_DEPTH < 2) ? 1 : $clog2(WR_DEPTH);
    localparam int unsigned RD_CNT_W = (RD_DEPTH < 2) ? 1 : $clog2(RD_DEPTH + 1);
    localparam int unsigned WR_CNT_W = (WR_DEPTH < 2) ? 1 : $clog2(WR_DEPTH + 1);
    localparam int unsigned RD_USED_W = RD_CNT_W + 1;
    localparam int unsigned WR_USED_W = WR_CNT_W + 1;

    logic [DW-1:0] mem_r [0:DP-1];

    // Independent saturating delays preserve the age of queued requests.
    localparam int RD_DELAY_W = (READ_FIRST_LATENCY <= 2) ? 1 : $clog2(READ_FIRST_LATENCY);
    logic [RD_DELAY_W-1:0] rd_delay_q [0:RD_DEPTH-1];
    logic [RD_DELAY_W-1:0] rd_delay_active_q;
    logic [AW-1:0] rd_addr_q [0:RD_DEPTH-1];
    logic [7:0]    rd_len_q  [0:RD_DEPTH-1];
    logic [2:0]    rd_size_q [0:RD_DEPTH-1];
    logic [1:0]    rd_burst_q[0:RD_DEPTH-1];
    logic          rd_bad_q  [0:RD_DEPTH-1];
    logic [RD_PTR_W-1:0] rd_wr_ptr_q;
    logic [RD_PTR_W-1:0] rd_rd_ptr_q;
    logic [RD_CNT_W-1:0] rd_count_q;
    logic rd_cmd_valid_q;
    // Retain the byte lane and transfer size, including a carry bit so that
    // an increment beyond the address space cannot alias a low RAM word.
    logic [AW:0] rd_byte_addr_q;
    logic [2:0] rd_size_active_q;
    logic [1:0] rd_burst_active_q;
    logic rd_cmd_error_q;
    logic [7:0] rd_len_active_q;
    logic [7:0] rd_beat_q;
    logic rd_error_accum_q;
    logic rd_resp_oob_q;
    logic [DW-1:0] mem_rd_data_q;

    logic [AW-1:0] wr_addr_q [0:WR_DEPTH-1];
    logic [7:0]    wr_len_q  [0:WR_DEPTH-1];
    logic [2:0]    wr_size_q [0:WR_DEPTH-1];
    logic [1:0]    wr_burst_q[0:WR_DEPTH-1];
    logic          wr_bad_q  [0:WR_DEPTH-1];
    logic [WR_PTR_W-1:0] wr_aw_wr_ptr_q;
    logic [WR_PTR_W-1:0] wr_aw_rd_ptr_q;
    logic [WR_CNT_W-1:0] wr_aw_count_q;
    logic wr_cmd_valid_q;
    logic [AW:0] wr_byte_addr_q;
    logic [2:0] wr_size_active_q;
    logic [1:0] wr_burst_active_q;
    logic wr_cmd_error_q;
    wire [WORD_ADDR_BITS:0] wr_word_addr_q = wr_byte_addr_q[AW:ADDR_LSB];
    logic [7:0] wr_len_active_q;
    logic [7:0] wr_beat_q;
    logic wr_error_accum_q;

    logic [1:0] wr_b_resp_q  [0:WR_DEPTH-1];
    logic [WR_PTR_W-1:0] wr_b_wr_ptr_q;
    logic [WR_PTR_W-1:0] wr_b_rd_ptr_q;
    logic [WR_CNT_W-1:0] wr_b_count_q;

    localparam int ddr_cmd_max_lat = 0;
    localparam int ddr_w_max_lat   = 0;
    localparam int ddr_rsp_max_lat = 0;
    localparam int ram_read_first_latency = READ_FIRST_LATENCY;

    wire ar_fire = s_axi_arvalid && s_axi_arready;
    wire r_fire  = s_axi_rvalid  && s_axi_rready;
    wire aw_fire = s_axi_awvalid && s_axi_awready;
    wire w_fire  = s_axi_wvalid  && s_axi_wready;
    wire b_fire  = s_axi_bvalid  && s_axi_bready;
    wire rd_active_mature = rd_delay_active_q == '0;
    wire rd_queue_mature = rd_delay_q[rd_rd_ptr_q] == '0;
    localparam logic [RD_DELAY_W-1:0] RD_INITIAL_DELAY =
        RD_DELAY_W'((READ_FIRST_LATENCY <= 2) ? 0 : READ_FIRST_LATENCY - 2);

`ifdef NPU_SIM_ASSERT
    initial begin
        assert(READ_FIRST_LATENCY >= 1)
            else $fatal(1,"READ_FIRST_LATENCY must be at least one clock cycle");
    end
`endif


    function automatic [RD_PTR_W-1:0] inc_rd_ptr(input [RD_PTR_W-1:0] ptr);
        if (RD_DEPTH <= 1) inc_rd_ptr = '0;
        else if (ptr == RD_PTR_W'(RD_DEPTH - 1)) inc_rd_ptr = '0;
        else inc_rd_ptr = ptr + 1'b1;
    endfunction

    function automatic [WR_PTR_W-1:0] inc_wr_ptr(input [WR_PTR_W-1:0] ptr);
        if (WR_DEPTH <= 1) inc_wr_ptr = '0;
        else if (ptr == WR_PTR_W'(WR_DEPTH - 1)) inc_wr_ptr = '0;
        else inc_wr_ptr = ptr + 1'b1;
    endfunction

    function automatic [7:0] ram_response_delay(input integer max_lat);
        ram_response_delay = 8'd0;
    endfunction

    // Supported AXI transfers: FIXED and INCR, up to the physical bus width.
    // Unaligned first beats use the addressed byte lanes; subsequent INCR
    // beats begin on the transfer-size boundary, as required by AXI.
    // 高位字节独立递增，组合边界避免字节内前缀与整地址进位重新串联。
    function automatic logic [AW:0] axi_increment_high_bytes(input logic [AW:0] byte_addr);
        logic [7:0] byte_value;
        logic [7:0] byte_prefix;
        begin
            axi_increment_high_bytes = '0;
            for (int byte_start=8; byte_start<=AW; byte_start+=8) begin
                byte_value = 8'(byte_addr >> byte_start) ^ 8'h00;
                for (int bit_index=0; bit_index<8; bit_index++) begin
                    byte_prefix = (8'd1 << bit_index) - 8'd1;
                    if (byte_start+bit_index <= AW) begin
                        axi_increment_high_bytes[byte_start+bit_index] = byte_value[bit_index] ^
                            (&(byte_value | ~byte_prefix));
                    end
                end
            end
        end
    endfunction

    function automatic logic [AW:0] axi_next_addr(
        input logic [AW:0] byte_addr, input logic [2:0] size,
        input logic [1:0] burst, input logic [AW:0] high_bytes_incremented);
        logic [7:0] low_keep_mask;
        logic [7:0] low_address;
        logic [7:0] low_carry_bits;
        logic [7:0] low_prefix_mask;
        logic [7:0] low_next;
        logic [AW:0] incremented_addr;
        localparam int p_high_groups = (AW > 7) ? (AW-2)/6 : 1;
        localparam int p_high_bytes = (AW >= 8) ? AW/8 : 1;
`ifdef SYNTHESIS
        (* keep = 1 *)
`endif
        logic [p_high_bytes*p_high_groups-1:0] high_prefix_groups;
        logic [7:0] high_byte_address;
        logic high_byte_carry;
        begin
            // 步长最高为 128 字节，低于传输边界的地址位清零并退出进位判断。
            low_keep_mask = 8'hff << size;
            low_address = 8'(byte_addr);
            low_carry_bits = low_address | ~low_keep_mask;
            for (int bit_index=0; bit_index<8; bit_index++) begin
                low_prefix_mask = (8'd1 << bit_index) - 8'd1;
                low_next[bit_index] = low_keep_mask[bit_index] &
                    (low_address[bit_index] ^ (&(low_carry_bits | ~low_prefix_mask)));
            end
            incremented_addr = (AW+1)'(low_next);
            // 每个高位字节的进位前缀按六位并行归并，再选择保持值或递增值。
            high_prefix_groups = '1;
            for (int byte_start=8; byte_start<=AW; byte_start+=8) begin
                for (int group=0; group<p_high_groups; group++) begin
                    for (int group_bit=0; group_bit<6; group_bit++) begin
                        if (8+group*6+group_bit < byte_start)
                            high_prefix_groups[(byte_start/8-1)*p_high_groups+group] &=
                                byte_addr[8+group*6+group_bit];
                    end
                end
                // 异或零保持高位地址经过逻辑运算时的四态传播。
                high_byte_address = 8'(byte_addr >> byte_start) ^ 8'h00;
                high_byte_carry = (&low_carry_bits) &&
                    (&high_prefix_groups[(byte_start/8-1)*p_high_groups+:p_high_groups]);
                for (int bit_index=0; bit_index<8; bit_index++) begin
                    if (byte_start+bit_index <= AW)
                        incremented_addr[byte_start+bit_index] = high_byte_carry ?
                            high_bytes_incremented[byte_start+bit_index] : high_byte_address[bit_index];
                end
            end
            axi_next_addr = (burst == 2'b00) ? byte_addr : incremented_addr;
        end
    endfunction

    function automatic logic axi_command_bad(
        input logic [AW-1:0] byte_addr, input logic [7:0] len,
        input logic [2:0] size, input logic [1:0] burst);
        logic [11:0] page_address;
        logic page_word_high_full;
        logic [8:0] page_last_word;
`ifdef SYNTHESIS
        (* keep = 1 *)
`endif
        logic [4:0] page_carry;
        logic [31:0] step, page_start, page_end;
        begin
            if (ADDR_LSB <= 4) begin
                // 各传输宽度分别计算末拍进位，尺寸字段只选择已经形成的跨页条件。
                page_address = 12'(byte_addr);
                for (int byte_shift=0; byte_shift<5; byte_shift++)
                    page_carry[byte_shift] = 1'(({1'b0, 8'(page_address >> byte_shift)} + {1'b0, len}) >> 8);
                page_last_word = '0;
                page_word_high_full = 1'b0;
                case (size)
                    3'd0: begin
                        page_last_word[8] = page_carry[0];
                        page_word_high_full = &page_address[11:8];
                    end
                    3'd1: begin
                        page_last_word[8] = page_carry[1];
                        page_word_high_full = &page_address[11:9];
                    end
                    3'd2: begin
                        page_last_word[8] = page_carry[2];
                        page_word_high_full = &page_address[11:10];
                    end
                    3'd3: begin
                        page_last_word[8] = page_carry[3];
                        page_word_high_full = page_address[11];
                    end
                    3'd4: begin
                        page_last_word[8] = page_carry[4];
                        page_word_high_full = 1'b1;
                    end
                    default: begin end
                endcase
                axi_command_bad = (32'(size) > ADDR_LSB) || (burst > 2'b01) ||
                    ((burst == 2'b00) && len > 8'd15) ||
                    ((burst == 2'b01) && page_word_high_full && page_last_word[8]);
            end else begin
                step = 32'd1 << size;
                page_start = (32'(byte_addr) & 32'hfff) & ~(step-1'b1);
                page_end = page_start + ((burst == 2'b00) ? step : ((32'(len)+1'b1) << size));
                axi_command_bad = (32'(size) > ADDR_LSB) || (burst > 2'b01) ||
                    ((burst == 2'b00) && len > 8'd15) || (page_end > 32'd4096);
            end
        end
    endfunction

    function automatic logic addr_oob(input logic [AW-1:0] byte_addr);
        if (AW > (ADDR_LSB + ADDR_BITS)) begin
            addr_oob = |byte_addr[AW-1:ADDR_LSB + ADDR_BITS];
        end else begin
            addr_oob = 1'b0;
        end
    endfunction

    function automatic logic [ADDR_BITS-1:0] word_idx(input logic [AW-1:0] byte_addr);
        word_idx = byte_addr[ADDR_LSB + ADDR_BITS - 1:ADDR_LSB];
    endfunction

    (* keep = "true" *) logic [AW:0] rd_high_bytes_incremented;
    logic [AW:0] wr_high_bytes_incremented;
    assign rd_high_bytes_incremented = axi_increment_high_bytes(rd_byte_addr_q);
    assign wr_high_bytes_incremented = axi_increment_high_bytes(wr_byte_addr_q);

    wire rd_pipe_cmd_mode = 1'b1;
    wire ar_ready_delay_clear = 1'b1;
    wire r_rsp_delay_clear = 1'b1;
    wire aw_ready_delay_clear = 1'b1;
    wire w_ready_delay_clear = 1'b1;
    wire rd_pipe_beat = s_axi_rvalid && s_axi_rready && !s_axi_rlast;
    wire rd_pipe_cmd_base = rd_pipe_cmd_mode && s_axi_rvalid && s_axi_rready && s_axi_rlast;
    wire rd_pipe_cmd_from_queue = rd_pipe_cmd_base && (rd_count_q != '0) && rd_queue_mature;
    wire rd_pipe_cmd_from_ar = rd_pipe_cmd_base && (rd_count_q == '0) && ar_fire && ram_read_first_latency == 1;
    wire rd_start_cmd_from_ar = !rd_cmd_valid_q && !s_axi_rvalid &&
        (rd_count_q == '0) && ar_fire && ram_read_first_latency == 1;
    wire rd_pipe_cmd = rd_pipe_cmd_from_queue || rd_pipe_cmd_from_ar || rd_start_cmd_from_ar;
    wire [AW:0] rd_pipe_cmd_byte_addr =
        rd_pipe_cmd_from_queue ? {1'b0,rd_addr_q[rd_rd_ptr_q]} : {1'b0,s_axi_araddr};
    wire [7:0] rd_pipe_cmd_len =
        rd_pipe_cmd_from_queue ? rd_len_q[rd_rd_ptr_q] : s_axi_arlen;
    wire rd_pipe_cmd_bad = rd_pipe_cmd_from_queue ? rd_bad_q[rd_rd_ptr_q] :
        axi_command_bad(s_axi_araddr,s_axi_arlen,s_axi_arsize,s_axi_arburst);
    wire [7:0] rd_issue_beat = rd_pipe_cmd ? 8'd0 :
                               rd_pipe_beat ? (rd_beat_q + 8'd1) : rd_beat_q;
    wire [7:0] rd_issue_len = rd_pipe_cmd ? rd_pipe_cmd_len : rd_len_active_q;
    wire [AW:0] rd_issue_byte_addr = rd_pipe_cmd ? rd_pipe_cmd_byte_addr :
        rd_pipe_beat ? axi_next_addr(rd_byte_addr_q,rd_size_active_q,rd_burst_active_q,rd_high_bytes_incremented) : rd_byte_addr_q;
    wire [WORD_ADDR_BITS:0] rd_issue_word_addr = rd_issue_byte_addr[AW:ADDR_LSB];
    // Compare against the actual word count, also for non-power-of-two RAMs.
    logic rd_issue_oob;
    // 二次幂容量只需检查高地址位；其余容量保留完整无符号比较。
    if (((DP & (DP-1)) == 0) && ((WORD_ADDR_BITS+1)'(DP) != '0) &&
        ADDR_LSB + $clog2(DP) >= 8) begin : g_read_predicted_bound
        localparam int p_capacity_bits = ADDR_LSB + $clog2(DP);
        logic [7:0] lower_keep_mask;
        // 地址归约独立于突发选择，保留晚到控制信号之前的组合边界。
        (* keep = 1 *) logic lower_carry;
        logic middle_carry;
        (* keep = 1 *) logic current_oob, upper_all_ones;
        logic next_oob, command_oob;

        // 容量边界以下的进位与边界以上的地址独立归约，直接预测下一拍越界状态。
        // 最高扩展位参与判断，地址空间末端的定宽回绕也保留相同结果。
        assign lower_keep_mask = 8'hff << rd_size_active_q;
        assign lower_carry = &(rd_byte_addr_q[7:0] | ~lower_keep_mask);
        if (p_capacity_bits > 8) begin : g_middle
            localparam int p_middle_groups = (p_capacity_bits - 8 + 2) / 3;
            logic [p_middle_groups-1:0] middle_full;
            // 各组三位独立归约，再合并容量边界以下的连续进位条件。
            for (genvar group_index = 0; group_index < p_middle_groups; group_index++) begin : g_group
                localparam int p_low = 8 + 3 * group_index;
                localparam int p_width = (p_capacity_bits - p_low < 3) ? p_capacity_bits - p_low : 3;
                assign middle_full[group_index] = &rd_byte_addr_q[p_low +: p_width];
            end
            assign middle_carry = &middle_full;
        end else begin : g_no_middle
            assign middle_carry = 1'b1;
        end
        assign current_oob = |rd_byte_addr_q[AW:p_capacity_bits];
        assign upper_all_ones = &rd_byte_addr_q[AW:p_capacity_bits];
        assign next_oob = rd_burst_active_q == 2'b00 ? current_oob :
            ((lower_carry && middle_carry) ? !upper_all_ones : current_oob);
        assign command_oob = |rd_pipe_cmd_byte_addr[AW:p_capacity_bits];
        assign rd_issue_oob = rd_pipe_cmd ? command_oob :
            (rd_pipe_beat ? next_oob : current_oob);
    end else if (((DP & (DP-1)) == 0) && ((WORD_ADDR_BITS+1)'(DP) != '0)) begin : g_read_power_bound
        localparam int p_groups = (WORD_ADDR_BITS + 4) / 4;
        logic [WORD_ADDR_BITS:0] high_address;
        (* keep = 1 *) logic [p_groups-1:0] group_nonzero;
        assign high_address = rd_issue_word_addr >> $clog2(DP);
        // 各四位地址组独立判断，末级只归约组结果。
        for (genvar group_i = 0; group_i < p_groups; group_i++) begin : g_group
            localparam int p_low = 4 * group_i;
            localparam int p_width = WORD_ADDR_BITS + 1 - p_low < 4 ?
                WORD_ADDR_BITS + 1 - p_low : 4;
            assign group_nonzero[group_i] = |high_address[p_low +: p_width];
        end
        assign rd_issue_oob = |group_nonzero;
    end else begin : g_read_arbitrary_bound
        assign rd_issue_oob = rd_issue_word_addr >= (WORD_ADDR_BITS+1)'(DP);
    end
    wire rd_issue_fault = rd_issue_oob || (rd_pipe_cmd ? rd_pipe_cmd_bad : rd_cmd_error_q);
    wire rd_can_issue = rd_cmd_valid_q && rd_active_mature &&
                        (!s_axi_rvalid || rd_pipe_beat || rd_pipe_cmd) && r_rsp_delay_clear;
    wire rd_issue_any = rd_can_issue || rd_pipe_cmd;
    (* keep = 1 *) logic rd_current_last, rd_following_last, rd_queue_last, rd_ar_last;
    logic rd_issue_last;
    // 各来源的末拍条件并行比较，响应握手只选择已经形成的一位结果。
    assign rd_current_last = rd_beat_q == rd_len_active_q;
`ifdef SYNTHESIS
    (* keep = 1 *) logic [7:0] rd_following_bit_equal;
    // 末拍等式按相邻位的进位一致性并行计算，响应选择不参与计数运算。
    assign rd_following_bit_equal[0] = ~(rd_beat_q[0] ^ rd_len_active_q[0] ^ 1'b1);
    for (genvar bit_index = 1; bit_index < 8; bit_index++) begin : g_following_last
        assign rd_following_bit_equal[bit_index] =
            ~((rd_beat_q[bit_index] ^ rd_len_active_q[bit_index]) ^
              (rd_beat_q[bit_index-1] & ~rd_len_active_q[bit_index-1]));
    end
    assign rd_following_last = &rd_following_bit_equal;
`else
    assign rd_following_last = (rd_beat_q + 8'd1) == rd_len_active_q;
`endif
    assign rd_queue_last = rd_len_q[rd_rd_ptr_q] == 8'd0;
    assign rd_ar_last = s_axi_arlen == 8'd0;
    always_comb begin
        rd_issue_last = rd_pipe_cmd ?
            (rd_pipe_cmd_from_queue ? rd_queue_last : rd_ar_last) :
            (rd_pipe_beat ? rd_following_last : rd_current_last);
`ifndef SYNTHESIS
        // 部分未知的来源选择使用完整字节比较，保持四态数据合并的结果。
        if ((^{rd_pipe_cmd, rd_pipe_cmd_from_queue, rd_pipe_beat,
               rd_beat_q, rd_len_active_q, rd_len_q[rd_rd_ptr_q], s_axi_arlen}) === 1'bx)
            rd_issue_last = rd_issue_beat == rd_issue_len;
`endif
    end
    wire [1:0] rd_issue_resp =
        ((rd_pipe_cmd ? 1'b0 : rd_error_accum_q) || rd_issue_fault) ? 2'b10 : 2'b00;
    // Keep the synchronous RAM read pipeline enabled for every issued beat.
    // Invalid requests are zeroed at R, while a non-power-of-two physical
    // array clamps an unused index to zero to avoid an out-of-array access.
    wire mem_rd_en = rd_issue_any;
    wire [ADDR_BITS-1:0] mem_rd_addr = ((DP & (DP-1)) == 0) ?
        rd_issue_word_addr[ADDR_BITS-1:0] :
        (rd_issue_oob ? '0 : rd_issue_word_addr[ADDR_BITS-1:0]);

    wire [RD_USED_W-1:0] rd_slots_used =
        RD_USED_W'(rd_count_q) + (rd_cmd_valid_q ? RD_USED_W'(1) : RD_USED_W'(0));
    wire [WR_USED_W-1:0] wr_aw_slots_used =
        WR_USED_W'(wr_aw_count_q) + (wr_cmd_valid_q ? WR_USED_W'(1) : WR_USED_W'(0));
    wire rd_queue_full = (rd_slots_used >= RD_USED_W'(RD_DEPTH));
    wire wr_aw_queue_full = (wr_aw_slots_used >= WR_USED_W'(WR_DEPTH));
    wire wr_b_queue_full = (wr_b_count_q == WR_CNT_W'(WR_DEPTH));
    wire wr_b_pop = b_fire;
    wire wr_has_addr_for_w = wr_cmd_valid_q;
    logic wr_active_oob;
    logic [31:0] wr_lane_first;
    logic [31:0] wr_transfer_block;
    logic [BYTEW-1:0] wr_legal_lanes;
    assign wr_active_oob = ((DP & (DP-1)) == 0) && ((WORD_ADDR_BITS+1)'(DP) != '0) ?
        (|(wr_word_addr_q >> $clog2(DP))) :
        (wr_word_addr_q >= (WORD_ADDR_BITS+1)'(DP));
    assign wr_lane_first = 32'(wr_byte_addr_q) & (BYTEW-1);
    assign wr_transfer_block = wr_lane_first >> wr_size_active_q;
    // 有效字节位于起始字节之后，且与起始地址属于同一个传输块。
    always_comb begin
        for (int i=0; i<BYTEW; i++) begin
            wr_legal_lanes[i] = (32'(i) >= wr_lane_first) &&
                ((32'(i) >> wr_size_active_q) == wr_transfer_block);
        end
    end
    wire wr_strobe_error = |(s_axi_wstrb & ~wr_legal_lanes);
    wire wr_last_expected = (wr_beat_q == wr_len_active_q);

    assign s_axi_arready = !rd_queue_full && ar_ready_delay_clear;
    assign s_axi_awready = !wr_aw_queue_full && aw_ready_delay_clear;
    assign s_axi_wready  = wr_has_addr_for_w &&
                            ((wr_b_count_q < WR_CNT_W'(WR_DEPTH)) || wr_b_pop) &&
                            w_ready_delay_clear;
    assign s_axi_rdata = rd_resp_oob_q ? '0 : mem_rd_data_q;

    always @(posedge clk) begin
        if (mem_rd_en) begin
            mem_rd_data_q <= mem_r[mem_rd_addr];
        end
    end

    always @(posedge clk) begin
        if (w_fire && !wr_active_oob && !wr_cmd_error_q && !wr_strobe_error) begin
            for (int i = 0; i < DW/8; i++) begin
                if (s_axi_wstrb[i]) begin
                    mem_r[wr_word_addr_q[ADDR_BITS-1:0]][8*i +: 8] <=
                        s_axi_wdata[8*i +: 8];
                end
            end
        end
    end

    always @(posedge clk) begin
        if (!rst_n) begin
            rd_wr_ptr_q       <= '0;
            rd_rd_ptr_q       <= '0;
            rd_count_q        <= '0;
            rd_cmd_valid_q    <= 1'b0;
            rd_byte_addr_q    <= '0;
            rd_delay_active_q <= '0;
            for (int i = 0; i < RD_DEPTH; i++) rd_delay_q[i] <= '0;
            rd_size_active_q  <= 3'(ADDR_LSB);
            rd_burst_active_q <= 2'b01;
            rd_cmd_error_q    <= 1'b0;
            rd_len_active_q   <= 8'd0;
            rd_beat_q         <= 8'd0;
            rd_error_accum_q  <= 1'b0;
            rd_resp_oob_q     <= 1'b0;
            s_axi_rvalid      <= 1'b0;
            s_axi_rresp       <= 2'b00;
            s_axi_rlast       <= 1'b0;
        end else begin
            logic rd_cmd_finish;
            logic rd_cmd_can_load;
            logic rd_cmd_load_from_queue;
            logic rd_cmd_load_from_ar;
            logic rd_enqueue;
            logic rd_dequeue;

            rd_cmd_finish = r_fire && s_axi_rlast;
            rd_cmd_can_load = !rd_cmd_valid_q || rd_cmd_finish;
            rd_cmd_load_from_queue = rd_cmd_can_load && (rd_count_q != '0);
            rd_cmd_load_from_ar = rd_cmd_can_load && (rd_count_q == '0) && ar_fire;
            rd_enqueue = ar_fire && !rd_cmd_load_from_ar;
            rd_dequeue = rd_cmd_load_from_queue;

            for (int i = 0; i < RD_DEPTH; i++) begin
                if (rd_delay_q[i] != '0) rd_delay_q[i] <= rd_delay_q[i] - 1'b1;
            end
            if (rd_delay_active_q != '0) rd_delay_active_q <= rd_delay_active_q - 1'b1;

            if (ar_fire && !rd_cmd_load_from_ar) begin
                rd_addr_q[rd_wr_ptr_q] <= s_axi_araddr;
                rd_delay_q[rd_wr_ptr_q] <= RD_INITIAL_DELAY;
                rd_len_q[rd_wr_ptr_q]  <= s_axi_arlen;
                rd_size_q[rd_wr_ptr_q] <= s_axi_arsize;
                rd_burst_q[rd_wr_ptr_q] <= s_axi_arburst;
                rd_bad_q[rd_wr_ptr_q] <= axi_command_bad(s_axi_araddr,s_axi_arlen,s_axi_arsize,s_axi_arburst);
                rd_wr_ptr_q <= inc_rd_ptr(rd_wr_ptr_q);
            end

            unique case ({rd_enqueue, rd_dequeue})
                2'b10: rd_count_q <= rd_count_q + 1'b1;
                2'b01: rd_count_q <= rd_count_q - 1'b1;
                default: rd_count_q <= rd_count_q;
            endcase

            if (rd_issue_any) begin
                s_axi_rvalid <= 1'b1;
                s_axi_rlast  <= rd_issue_last;
                s_axi_rresp  <= rd_issue_resp;
                rd_resp_oob_q <= rd_issue_fault;
                if (rd_issue_fault) rd_error_accum_q <= 1'b1;
            end

            if (r_fire) begin
                if (!rd_issue_any) begin
                    s_axi_rvalid <= 1'b0;
                    s_axi_rlast  <= 1'b0;
                end
                if (s_axi_rlast) begin
                    rd_cmd_valid_q   <= 1'b0;
                    rd_beat_q        <= 8'd0;
                    rd_error_accum_q <= 1'b0;
                end else begin
                    rd_beat_q      <= rd_beat_q + 8'd1;
                    rd_byte_addr_q <= axi_next_addr(rd_byte_addr_q,rd_size_active_q,rd_burst_active_q,rd_high_bytes_incremented);
                end
            end

            if (rd_cmd_load_from_queue) begin
                rd_cmd_valid_q  <= 1'b1;
                rd_byte_addr_q  <= {1'b0,rd_addr_q[rd_rd_ptr_q]};
                rd_delay_active_q <= rd_delay_q[rd_rd_ptr_q] == '0 ? '0 :
                    rd_delay_q[rd_rd_ptr_q] - 1'b1;
                rd_size_active_q <= rd_size_q[rd_rd_ptr_q];
                rd_burst_active_q <= rd_burst_q[rd_rd_ptr_q];
                rd_cmd_error_q <= rd_bad_q[rd_rd_ptr_q];
                rd_len_active_q <= rd_len_q[rd_rd_ptr_q];
                rd_beat_q       <= 8'd0;
                rd_error_accum_q <= rd_pipe_cmd ? rd_issue_fault : 1'b0;
                rd_rd_ptr_q <= inc_rd_ptr(rd_rd_ptr_q);
            end else if (rd_cmd_load_from_ar) begin
                rd_cmd_valid_q  <= 1'b1;
                rd_byte_addr_q  <= {1'b0,s_axi_araddr};
                rd_delay_active_q <= RD_INITIAL_DELAY;
                rd_size_active_q <= s_axi_arsize;
                rd_burst_active_q <= s_axi_arburst;
                rd_cmd_error_q <= axi_command_bad(s_axi_araddr,s_axi_arlen,s_axi_arsize,s_axi_arburst);
                rd_len_active_q <= s_axi_arlen;
                rd_beat_q       <= 8'd0;
                rd_error_accum_q <= rd_pipe_cmd ? rd_issue_fault : 1'b0;
            end
        end
    end

    always @(posedge clk) begin
        if (!rst_n) begin
            wr_aw_wr_ptr_q    <= '0;
            wr_aw_rd_ptr_q    <= '0;
            wr_aw_count_q     <= '0;
            wr_cmd_valid_q    <= 1'b0;
            wr_byte_addr_q    <= '0;
            wr_size_active_q  <= 3'(ADDR_LSB);
            wr_burst_active_q <= 2'b01;
            wr_cmd_error_q    <= 1'b0;
            wr_len_active_q   <= 8'd0;
            wr_beat_q         <= 8'd0;
            wr_error_accum_q  <= 1'b0;
            wr_b_wr_ptr_q     <= '0;
            wr_b_rd_ptr_q     <= '0;
            wr_b_count_q      <= '0;
            s_axi_bvalid      <= 1'b0;
            s_axi_bresp       <= 2'b00;
        end else begin
            logic wr_cmd_finish;
            logic wr_cmd_can_load;
            logic wr_cmd_load_from_queue;
            logic wr_cmd_load_from_aw;
            logic wr_aw_enqueue;
            logic wr_aw_dequeue;
            logic wr_b_push;
            logic [1:0] wr_b_push_resp;

            wr_cmd_finish = w_fire && (s_axi_wlast || wr_last_expected);
            wr_cmd_can_load = !wr_cmd_valid_q || wr_cmd_finish;
            wr_cmd_load_from_queue = wr_cmd_can_load && (wr_aw_count_q != '0);
            wr_cmd_load_from_aw = wr_cmd_can_load && (wr_aw_count_q == '0) && aw_fire;
            wr_aw_enqueue = aw_fire && !wr_cmd_load_from_aw;
            wr_aw_dequeue = wr_cmd_load_from_queue;
            wr_b_push = 1'b0;
            wr_b_push_resp = 2'b00;

            if (aw_fire && !wr_cmd_load_from_aw) begin
                wr_addr_q[wr_aw_wr_ptr_q] <= s_axi_awaddr;
                wr_len_q[wr_aw_wr_ptr_q]  <= s_axi_awlen;
                    wr_size_q[wr_aw_wr_ptr_q] <= s_axi_awsize;
                    wr_burst_q[wr_aw_wr_ptr_q] <= s_axi_awburst;
                    wr_bad_q[wr_aw_wr_ptr_q] <= axi_command_bad(s_axi_awaddr,s_axi_awlen,s_axi_awsize,s_axi_awburst);
                wr_aw_wr_ptr_q <= inc_wr_ptr(wr_aw_wr_ptr_q);
            end

            if (w_fire) begin
                logic wr_oob;
                logic wr_error_next;

                wr_oob = wr_active_oob;
                wr_error_next = wr_error_accum_q | wr_oob | wr_cmd_error_q | wr_strobe_error | (s_axi_wlast != wr_last_expected);

                if (s_axi_wlast || wr_last_expected) begin
                    wr_b_push_resp = wr_error_next ? 2'b10 : 2'b00;
                    wr_b_push = 1'b1;
                    wr_cmd_valid_q <= 1'b0;
                    wr_beat_q <= 8'd0;
                    wr_error_accum_q <= 1'b0;
                end else begin
                    wr_beat_q <= wr_beat_q + 8'd1;
                    wr_byte_addr_q <= axi_next_addr(wr_byte_addr_q,wr_size_active_q,wr_burst_active_q,wr_high_bytes_incremented);
                    wr_error_accum_q <= wr_error_next;
                end
            end

            unique case ({wr_aw_enqueue, wr_aw_dequeue})
                2'b10: wr_aw_count_q <= wr_aw_count_q + 1'b1;
                2'b01: wr_aw_count_q <= wr_aw_count_q - 1'b1;
                default: wr_aw_count_q <= wr_aw_count_q;
            endcase

            if (wr_cmd_load_from_queue) begin
                wr_cmd_valid_q  <= 1'b1;
                wr_byte_addr_q  <= {1'b0,wr_addr_q[wr_aw_rd_ptr_q]};
                wr_size_active_q <= wr_size_q[wr_aw_rd_ptr_q];
                wr_burst_active_q <= wr_burst_q[wr_aw_rd_ptr_q];
                wr_cmd_error_q <= wr_bad_q[wr_aw_rd_ptr_q];
                wr_len_active_q <= wr_len_q[wr_aw_rd_ptr_q];
                wr_beat_q       <= 8'd0;
                wr_error_accum_q <= 1'b0;
                wr_aw_rd_ptr_q <= inc_wr_ptr(wr_aw_rd_ptr_q);
            end else if (wr_cmd_load_from_aw) begin
                wr_cmd_valid_q  <= 1'b1;
                wr_byte_addr_q  <= {1'b0,s_axi_awaddr};
                wr_size_active_q <= s_axi_awsize;
                wr_burst_active_q <= s_axi_awburst;
                wr_cmd_error_q <= axi_command_bad(s_axi_awaddr,s_axi_awlen,s_axi_awsize,s_axi_awburst);
                wr_len_active_q <= s_axi_awlen;
                wr_beat_q       <= 8'd0;
                wr_error_accum_q <= 1'b0;
            end

            if (b_fire) begin
                s_axi_bvalid <= 1'b0;
                wr_b_rd_ptr_q <= inc_wr_ptr(wr_b_rd_ptr_q);
            end

            if (!s_axi_bvalid && (wr_b_count_q != '0)) begin
                s_axi_bvalid <= 1'b1;
                s_axi_bresp  <= wr_b_resp_q[wr_b_rd_ptr_q];
            end

            if (wr_b_push) begin
                wr_b_resp_q[wr_b_wr_ptr_q] <= wr_b_push_resp;
                wr_b_wr_ptr_q <= inc_wr_ptr(wr_b_wr_ptr_q);
            end

            unique case ({wr_b_push, b_fire})
                2'b10: wr_b_count_q <= wr_b_count_q + 1'b1;
                2'b01: wr_b_count_q <= wr_b_count_q - 1'b1;
                default: wr_b_count_q <= wr_b_count_q;
            endcase
        end
    end

    initial begin
        if ((INIT_EN != 0) && (MEM_PATH != "")) begin
`ifdef NPU_SIM_ASSERT
            assert(MEM_WORD_WIDTH == DW);
`endif
            $readmemh(MEM_PATH, mem_r);
        end
    end

    wire _unused_axi_attr =
        |s_axi_awcache | |s_axi_awprot | |s_axi_awlock |
        |s_axi_arcache | |s_axi_arprot | |s_axi_arlock;

endmodule
