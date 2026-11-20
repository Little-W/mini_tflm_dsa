// SPDX-License-Identifier: Apache-2.0
// 页内突发保持 AW/W/B 直接传递。跨页突发等待先前响应完成后，
// 按页拆分物理突发，并向原始 DMA 命令返回一次合并响应。
module axi_write_page_guard #(
    parameter int ADDR_W=32, DATA_W=32, WRITE_OUTSTANDING=4
) (
    input logic clk, rst_n,
    input logic s_awvalid, output logic s_awready,
    input logic [ADDR_W-1:0] s_awaddr,
    input logic [7:0] s_awlen,
    input logic [2:0] s_awsize,
    input logic [1:0] s_awburst,
    input logic s_wvalid, output logic s_wready,
    input logic [DATA_W-1:0] s_wdata,
    input logic [DATA_W/8-1:0] s_wstrb,
    input logic s_wlast,
    output logic s_bvalid, input logic s_bready,
    output logic [1:0] s_bresp,
    output logic m_awvalid, input logic m_awready,
    output logic [ADDR_W-1:0] m_awaddr,
    output logic [7:0] m_awlen,
    output logic [2:0] m_awsize,
    output logic [1:0] m_awburst,
    output logic m_wvalid, input logic m_wready,
    output logic [DATA_W-1:0] m_wdata,
    output logic [DATA_W/8-1:0] m_wstrb,
    output logic m_wlast,
    input logic m_bvalid, output logic m_bready,
    input logic [1:0] m_bresp,
    output logic idle
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

    // 长度字段表示最后一拍，页内字序号直接与该字段相加即可判断是否跨页。
    if (SIZE <= 4 && ADDR_W >= 12) begin : g_direct_page
        localparam int p_word_bits = 12 - SIZE;
        logic [p_word_bits:0] last_word;
        logic unaligned;
        if (SIZE == 0) begin : g_byte_bus
            assign unaligned = 1'b0;
        end else begin : g_word_bus
            assign unaligned = |s_awaddr[SIZE-1:0];
        end
        assign last_word = (p_word_bits+1)'(s_awaddr[11:SIZE]) + (p_word_bits+1)'(s_awlen);
        assign page_local = !(last_word[p_word_bits] || (unaligned && (&last_word[p_word_bits-1:0])));
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
