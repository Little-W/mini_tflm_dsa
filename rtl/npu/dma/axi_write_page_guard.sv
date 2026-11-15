// SPDX-License-Identifier: Apache-2.0
// Preserve the direct AW/W/B path for page-local bursts. A crossing burst
// waits for earlier B responses, then emits page-local segments and one
// combined response to the original DMA command.
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
    wire direct_aw = state == DIRECT && page_local && s_awvalid && m_awready;
    wire direct_b = state == DIRECT && m_bvalid && s_bready;
    wire direct_last = state == DIRECT && direct_data_outstanding != 0 &&
                       s_wvalid && m_wready && s_wlast;

    always_comb begin
        page_local = ({1'b0,s_awaddr[11:0]} + ((13'(s_awlen)+13'd1)<<SIZE)) <= 13'd4096;
        page_beats = (13'd4096 - {1'b0,address_q[11:0]}) >> SIZE;
        segment_beats = 13'(remaining_q) < page_beats ? remaining_q : 9'(page_beats);
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
                    address_q <= address_q + (ADDR_W'(segment_beats)<<SIZE);
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
`ifndef SYNTHESIS
    assert property (@(posedge clk) disable iff (!rst_n)
        m_awvalid && !m_awready |=> m_awvalid && $stable({m_awaddr,m_awlen,m_awsize,m_awburst}));
    assert property (@(posedge clk) disable iff (!rst_n)
        m_wvalid && !m_wready |=> m_wvalid && $stable({m_wdata,m_wstrb,m_wlast}));
    assert property (@(posedge clk) disable iff (!rst_n)
        s_bvalid && !s_bready |=> s_bvalid && $stable(s_bresp));
    always_ff @(posedge clk) if (rst_n) begin
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
