// SPDX-License-Identifier: Apache-2.0
// 页内突发保持 AW/W/B 直接传递。跨页突发等待先前响应完成后，
// 按页拆分物理突发，并向原始 DMA 命令返回一次合并响应。
module axi_write_page_guard #(
    parameter int ADDR_W=32, DATA_W=32, WRITE_OUTSTANDING=4
) (
    input logic clk /* 工作时钟 */, rst_n /* 低有效复位 */,
    input logic s_awvalid /* 客户端 AXI：写地址请求有效 */, output logic s_awready /* 客户端 AXI：可接收写地址请求 */,
    input logic [ADDR_W-1:0] s_awaddr /* 客户端 AXI：写突发首字节地址 */,
    input logic [7:0] s_awlen /* 客户端 AXI：写突发传输拍数减一 */,
    input logic [2:0] s_awsize /* 客户端 AXI：每个写数据拍字节数的二进制对数 */,
    input logic [1:0] s_awburst /* 客户端 AXI：写突发地址递增类型 */,
    input logic s_wvalid /* 客户端 AXI：写数据有效 */, output logic s_wready /* 客户端 AXI：可接收写数据 */,
    input logic [DATA_W-1:0] s_wdata /* 客户端 AXI：待写入的总线数据 */,
    input logic [DATA_W/8-1:0] s_wstrb /* 客户端 AXI：写数据逐字节使能 */,
    input logic s_wlast /* 客户端 AXI：当前写突发的最后一个数据拍 */,
    output logic s_bvalid /* 客户端 AXI：写响应有效 */, input logic s_bready /* 客户端 AXI：可接收写响应 */,
    output logic [1:0] s_bresp /* 客户端 AXI：写响应状态码 */,
    output logic m_awvalid /* 存储侧 AXI：写地址请求有效 */, input logic m_awready /* 存储侧 AXI：可接收写地址请求 */,
    output logic [ADDR_W-1:0] m_awaddr /* 存储侧 AXI：写突发首字节地址 */,
    output logic [7:0] m_awlen /* 存储侧 AXI：写突发传输拍数减一 */,
    output logic [2:0] m_awsize /* 存储侧 AXI：每个写数据拍字节数的二进制对数 */,
    output logic [1:0] m_awburst /* 存储侧 AXI：写突发地址递增类型 */,
    output logic m_wvalid /* 存储侧 AXI：写数据有效 */, input logic m_wready /* 存储侧 AXI：可接收写数据 */,
    output logic [DATA_W-1:0] m_wdata /* 存储侧 AXI：待写入的总线数据 */,
    output logic [DATA_W/8-1:0] m_wstrb /* 存储侧 AXI：写数据逐字节使能 */,
    output logic m_wlast /* 存储侧 AXI：当前写突发的最后一个数据拍 */,
    input logic m_bvalid /* 存储侧 AXI：写响应有效 */, output logic m_bready /* 存储侧 AXI：可接收写响应 */,
    input logic [1:0] m_bresp /* 存储侧 AXI：写响应状态码 */,
    output logic idle /* 当前没有待发送的拆分写请求或待接收写响应 */
);
    localparam int BYTES=DATA_W/8;
    localparam int SIZE=$clog2(BYTES);
    localparam int OUTS_W=WRITE_OUTSTANDING<2 ? 1 : $clog2(WRITE_OUTSTANDING+1);
    typedef enum logic [2:0] {DIRECT, ADDRESS, DATA, RESPONSE, COMPLETE} state_t;
    state_t state;
    logic [OUTS_W-1:0] direct_outstanding;
    logic [OUTS_W-1:0] direct_data_outstanding;
    logic [ADDR_W-1:0] address_q;
    logic [8:0] remaining_q, segment_left_q, segment_beats;
    logic [12:0] page_beats;
    logic [1:0] response_q;
    logic page_local;
    logic [ADDR_W-1:0] address_nxt;
    wire direct_aw = state == DIRECT && page_local && s_awvalid && m_awready;
    wire direct_b = state == DIRECT && m_bvalid && s_bready;
    wire direct_last = state == DIRECT && direct_data_outstanding != 0 &&
                       s_wvalid && m_wready && s_wlast;

    // 页内字序号与剩余拍数并行相加，越过页末时直接构造截短后的地址。
    // 非整字地址保留最低字节位，分页计算仍取完整总线拍数。
    if (SIZE < 12 && ADDR_W >= 12) begin : g_page_words
        localparam int p_word_bits = 12 - SIZE;
        localparam int p_sum_bits = p_word_bits > 9 ? p_word_bits + 1 : 10;
        logic [p_sum_bits-1:0] word_sum;
        logic [p_word_bits:0] word_space;
        logic unaligned, reaches_page;
        logic [11:0] offset_nxt;

        if (SIZE == 0) begin : g_byte_bus
            assign unaligned = 1'b0;
        end else begin : g_word_bus
            assign unaligned = |address_q[SIZE-1:0];
            assign offset_nxt[SIZE-1:0] = address_q[SIZE-1:0];
        end
        assign word_sum = p_sum_bits'(address_q[11:SIZE]) + p_sum_bits'(remaining_q);
        assign word_space = {1'b0, ~address_q[11:SIZE]} + (p_word_bits+1)'(!unaligned);
        assign reaches_page = (|word_sum[p_sum_bits-1:p_word_bits]) ||
            (unaligned && (&word_sum[p_word_bits-1:0]));
        assign page_beats = 13'(word_space);
        assign segment_beats = reaches_page ? 9'(word_space) : remaining_q;
        assign offset_nxt[11:SIZE] = reaches_page ?
            {p_word_bits{unaligned}} : word_sum[p_word_bits-1:0];
        if (ADDR_W > 12) begin : g_page_number
            logic [ADDR_W-13:0] page_nxt;
            logic unused_page_carry;
            assign {unused_page_carry, page_nxt} =
                {1'b0, address_q[ADDR_W-1:12]} + (ADDR_W-11)'(1);
            assign address_nxt = {
                (reaches_page && !unaligned) ? page_nxt : address_q[ADDR_W-1:12],
                offset_nxt
            };
        end else begin : g_page_only
            assign address_nxt = offset_nxt;
        end
    end else begin : g_wide_transfer
        assign page_beats = (13'd4096 - {1'b0,address_q[11:0]}) >> SIZE;
        assign segment_beats = 13'(remaining_q) < page_beats ? remaining_q : 9'(page_beats);
        assign address_nxt = address_q + (ADDR_W'(segment_beats) << SIZE);
    end

    // 长度字段与页内剩余字数并行比较，最高地址组独立判断是否保留整页余量。
    if (SIZE <= 4 && ADDR_W >= 12) begin : g_direct_page
        localparam int p_word_bits = 12 - SIZE;
        logic [p_word_bits:0] last_word;
        logic [7:0] remaining_words;
        logic unaligned, upper_full;
        (* keep = 1 *) logic [2:0] length_less, length_equal;
        (* keep = 1 *) logic lower_allowed;
        if (SIZE == 0) begin : g_byte_bus
            assign unaligned = 1'b0;
        end else begin : g_word_bus
            assign unaligned = |s_awaddr[SIZE-1:0];
        end
        if (SIZE < 4) begin : g_upper_words
            assign upper_full = &s_awaddr[11:SIZE+8];
        end else begin : g_full_length
            assign upper_full = 1'b1;
        end
        assign remaining_words = ~s_awaddr[SIZE+:8];
        for (genvar group_index = 0; group_index < 3; group_index++) begin : g_length
            localparam int p_low = group_index * 3;
            localparam int p_bits = group_index == 2 ? 2 : 3;
            assign length_less[group_index] =
                s_awlen[p_low+:p_bits] < remaining_words[p_low+:p_bits];
            assign length_equal[group_index] =
                s_awlen[p_low+:p_bits] == remaining_words[p_low+:p_bits];
        end
        assign lower_allowed = length_less[0] || (length_equal[0] && !unaligned);
        always_comb begin
            page_local = !upper_full || length_less[2] ||
                (length_equal[2] && length_less[1]) ||
                (length_equal[2] && length_equal[1] && lower_allowed);
`ifndef SYNTHESIS
            // 四态输入采用完整模加表达式，保留部分未知地址的传播结果。
            if ((^{s_awaddr[11:0], s_awlen}) === 1'bx)
                page_local = !(last_word[p_word_bits] ||
                    (unaligned && (&last_word[p_word_bits-1:0])));
`endif
        end
        assign last_word = (p_word_bits+1)'(s_awaddr[11:SIZE]) + (p_word_bits+1)'(s_awlen);
    end else begin : g_direct_wide_transfer
        assign page_local = ({1'b0,s_awaddr[11:0]} + ((13'(s_awlen)+13'd1)<<SIZE)) <= 13'd4096;
    end

    always_comb begin
        s_awready = page_local ? m_awready : direct_outstanding == 0;
        m_awvalid = s_awvalid && page_local;
        m_awaddr = s_awaddr; m_awlen = s_awlen;
        m_awsize = s_awsize; m_awburst = s_awburst;
        s_wready = m_wready && direct_data_outstanding != 0;
        m_wvalid = s_wvalid && direct_data_outstanding != 0;
        m_wdata = s_wdata; m_wstrb = s_wstrb; m_wlast = s_wlast;
        s_bvalid = m_bvalid; s_bresp = m_bresp; m_bready = s_bready;
        if (state != DIRECT) begin
            s_awready = 1'b0;
            m_awvalid = state == ADDRESS;
            m_awaddr = address_q; m_awlen = 8'(segment_beats-9'd1);
            m_awsize = 3'(SIZE); m_awburst = 2'b01;
            s_wready = state == DATA && m_wready;
            m_wvalid = state == DATA && s_wvalid;
            m_wlast = segment_left_q == 1;
            s_bvalid = state == COMPLETE; s_bresp = response_q;
            m_bready = state == RESPONSE;
        end
    end
    assign idle = state == DIRECT && direct_outstanding == 0;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= DIRECT; direct_outstanding <= '0; direct_data_outstanding <= '0; address_q <= '0;
            remaining_q <= '0; segment_left_q <= '0; response_q <= '0;
        end else begin
            case ({direct_aw,direct_b})
                2'b10: direct_outstanding <= direct_outstanding + 1'b1;
                2'b01: direct_outstanding <= direct_outstanding - 1'b1;
                default: ;
            endcase
            case ({direct_aw,direct_last})
                2'b10: direct_data_outstanding <= direct_data_outstanding + 1'b1;
                2'b01: direct_data_outstanding <= direct_data_outstanding - 1'b1;
                default: ;
            endcase
            case (state)
                DIRECT: if (s_awvalid && s_awready && !page_local) begin
                    address_q <= s_awaddr; remaining_q <= {1'b0,s_awlen}+9'd1;
                    response_q <= 2'b00; state <= ADDRESS;
                end
                ADDRESS: if (m_awready) begin
                    segment_left_q <= segment_beats;
                    address_q <= address_nxt;
                    state <= DATA;
                end
                DATA: if (s_wvalid && m_wready) begin
                    remaining_q <= remaining_q - 9'd1;
                    segment_left_q <= segment_left_q - 9'd1;
                    if (segment_left_q == 1) state <= RESPONSE;
                end
                RESPONSE: if (m_bvalid) begin
                    if (m_bresp != 0 && response_q == 0) response_q <= m_bresp;
                    state <= remaining_q == 0 ? COMPLETE : ADDRESS;
                end
                COMPLETE: if (s_bready) state <= DIRECT;
                default: state <= DIRECT;
            endcase
        end
    end

`ifdef NPU_SIM_ASSERT
    initial begin : check_m_awvalid_stability
        logic stalled;
        logic [$bits({m_awaddr,m_awlen,m_awsize,m_awburst})-1:0] held_payload;
        stalled=1'b0;
        forever begin
            @(posedge clk);
            if (!rst_n) stalled=1'b0;
            else begin
                if (stalled) assert(m_awvalid && {m_awaddr,m_awlen,m_awsize,m_awburst}==held_payload);
                stalled=m_awvalid && !m_awready;
                held_payload={m_awaddr,m_awlen,m_awsize,m_awburst};
            end
        end
    end
    initial begin : check_m_wvalid_stability
        logic stalled;
        logic [$bits({m_wdata,m_wstrb,m_wlast})-1:0] held_payload;
        stalled=1'b0;
        forever begin
            @(posedge clk);
            if (!rst_n) stalled=1'b0;
            else begin
                if (stalled) assert(m_wvalid && {m_wdata,m_wstrb,m_wlast}==held_payload);
                stalled=m_wvalid && !m_wready;
                held_payload={m_wdata,m_wstrb,m_wlast};
            end
        end
    end
    initial begin : check_s_bvalid_stability
        logic stalled;
        logic [$bits(s_bresp)-1:0] held_payload;
        stalled=1'b0;
        forever begin
            @(posedge clk);
            if (!rst_n) stalled=1'b0;
            else begin
                if (stalled) assert(s_bvalid && s_bresp==held_payload);
                stalled=s_bvalid && !s_bready;
                held_payload=s_bresp;
            end
        end
    end
    initial forever @(posedge clk) if (rst_n) begin
        assert(direct_outstanding <= OUTS_W'(WRITE_OUTSTANDING));
        assert(direct_data_outstanding <= direct_outstanding);
        if (direct_b) assert(direct_outstanding != 0 || direct_aw);
        if (state != DIRECT) assert(direct_outstanding == 0 && direct_data_outstanding == 0);
        if (s_awvalid && s_awready)
            assert(s_awsize == 3'(SIZE) && (s_awaddr & ADDR_W'(BYTES-1)) == 0 && s_awburst == 2'b01);
        if (state == DATA && s_wvalid && s_wready)
            assert(s_wlast == (remaining_q == 1));
        if (m_awvalid && m_awready)
            assert(({1'b0,m_awaddr[11:0]} + ((13'(m_awlen)+13'd1)<<SIZE)) <= 13'd4096);
    end
`endif
endmodule
