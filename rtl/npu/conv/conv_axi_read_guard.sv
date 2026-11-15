// SPDX-License-Identifier: Apache-2.0
// The native block DMA aligns reads to complete words and may fetch tail
// padding. During Conv, restrict external reads to the four real allocations
// (OHWI weights, bias, multipliers, shifts), returning zero for padding lanes.
// Safe bursts remain bursts. Boundary requests use single word/byte transfers
// and therefore cannot cross 4 KiB. GEMM uses the original direct path.
module conv_axi_read_guard #(
    parameter int ADDR_W=32, DATA_W=32
) (
    input logic clk, rst_n, enable, cfg_valid,
    input logic [31:0] cfg_base[4],
    input logic [32:0] cfg_end[4],
    input logic s_arvalid, output logic s_arready,
    input logic [ADDR_W-1:0] s_araddr,
    input logic [7:0] s_arlen,
    input logic [2:0] s_arsize,
    input logic [1:0] s_arburst,
    output logic s_rvalid, input logic s_rready,
    output logic [DATA_W-1:0] s_rdata,
    output logic [1:0] s_rresp, output logic s_rlast,
    output logic m_arvalid, input logic m_arready,
    output logic [ADDR_W-1:0] m_araddr,
    output logic [7:0] m_arlen,
    output logic [2:0] m_arsize,
    output logic [1:0] m_arburst,
    input logic m_rvalid, output logic m_rready,
    input logic [DATA_W-1:0] m_rdata,
    input logic [1:0] m_rresp, input logic m_rlast,
    output logic idle
);
    typedef enum logic [2:0] {IDLE, FAST_AR, FAST_R, PREP, WORD_AR, WORD_R, OUT} state_t;
    state_t state;
    logic [31:0] base_q[4];
    logic [32:0] end_q[4];
    // Keep the carry while returning padded tail beats. A DMA burst starting
    // at 0xffff_fffc must never wrap into an unrelated low-address allocation.
    logic [32:0] addr_q;
    logic [7:0] len_q, beat_q;
    logic [3:0] pending_mask, allowed_mask;
    logic [1:0] lane;
    logic whole_word, error_q;
    logic [DATA_W-1:0] word_q;
    logic fast_legal;
    logic [32:0] request_end;
    always_comb begin
        request_end = 33'(s_araddr) + ((33'(s_arlen) + 33'd1) << 2);
        fast_legal = 1'b0;
        for (int i=0; i<4; i++)
            if (base_q[i] != 0 && 33'(s_araddr) >= {1'b0,base_q[i]} && request_end <= end_q[i])
                fast_legal = 1'b1;
        fast_legal = fast_legal && s_arsize == 3'd2 && s_arburst == 2'b01 &&
                     s_araddr[1:0] == 0 &&
                     ({1'b0,s_araddr[11:0]} + ((13'(s_arlen)+13'd1)<<2) <= 13'd4096);
        allowed_mask = '0;
        for (int b=0; b<4; b++)
            for (int i=0; i<4; i++)
                if (base_q[i] != 0 && (33'(addr_q)+33'(b)) >= {1'b0,base_q[i]} &&
                    (33'(addr_q)+33'(b)) < end_q[i]) allowed_mask[b] = 1'b1;
        lane = pending_mask[0] ? 2'd0 : pending_mask[1] ? 2'd1 :
               pending_mask[2] ? 2'd2 : 2'd3;
        whole_word = pending_mask == 4'b1111;
    end
    assign idle = state == IDLE;
    always_comb begin
        s_arready = m_arready; s_rvalid = m_rvalid; s_rdata = m_rdata;
        s_rresp = m_rresp; s_rlast = m_rlast;
        m_arvalid = s_arvalid; m_araddr = s_araddr; m_arlen = s_arlen;
        m_arsize = s_arsize; m_arburst = s_arburst; m_rready = s_rready;
        if (enable) begin
            s_arready = state == IDLE;
            s_rvalid = (state == FAST_R && m_rvalid) || state == OUT;
            s_rdata = state == OUT ? word_q : m_rdata;
            s_rresp = state == OUT ? (error_q ? 2'b10 : 2'b00) : m_rresp;
            s_rlast = state == OUT ? (beat_q == len_q) : m_rlast;
            m_arvalid = state == FAST_AR || state == WORD_AR;
            m_araddr = ADDR_W'(addr_q) + (state == WORD_AR && !whole_word ? ADDR_W'(lane) : ADDR_W'(0));
            m_arlen = state == FAST_AR ? len_q : 8'd0;
            m_arsize = (state == WORD_AR && !whole_word) ? 3'd0 : 3'd2;
            m_arburst = 2'b01;
            m_rready = state == FAST_R ? s_rready : state == WORD_R;
        end
    end
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= IDLE; addr_q <= '0; len_q <= '0; beat_q <= '0;
            word_q <= '0; pending_mask <= '0; error_q <= 1'b0;
            for (int i=0;i<4;i++) begin base_q[i]<='0; end_q[i]<='0; end
        end else begin
            if (cfg_valid) begin
                for (int i=0;i<4;i++) begin base_q[i]<=cfg_base[i]; end_q[i]<=cfg_end[i]; end
            end
            if (enable) case (state)
                IDLE: if (s_arvalid && s_arready) begin
                    addr_q <= 33'(s_araddr); len_q <= s_arlen; beat_q <= '0;
                    state <= fast_legal ? FAST_AR : PREP;
                end
                FAST_AR: if (m_arready) state <= FAST_R;
                FAST_R: if (m_rvalid && m_rready && m_rlast) state <= IDLE;
                PREP: begin
                    word_q <= '0; error_q <= 1'b0; pending_mask <= allowed_mask;
                    state <= allowed_mask == 0 ? OUT : WORD_AR;
                end
                WORD_AR: if (m_arready) state <= WORD_R;
                WORD_R: if (m_rvalid && m_rready) begin
                    error_q <= error_q || m_rresp[1] || !m_rlast;
                    if (whole_word) begin
                        word_q <= m_rdata; pending_mask <= '0; state <= OUT;
                    end else begin
                        word_q[8*lane +: 8] <= m_rdata[8*lane +: 8];
                        pending_mask <= pending_mask & ~(4'b1 << lane);
                        state <= (pending_mask & ~(4'b1 << lane)) == 0 ? OUT : WORD_AR;
                    end
                end
                OUT: if (s_rready) begin
                    if (beat_q == len_q) state <= IDLE;
                    else begin addr_q <= addr_q + 33'd4; beat_q <= beat_q + 8'd1; state <= PREP; end
                end
                default: state <= IDLE;
            endcase
        end
    end
`ifndef SYNTHESIS
    assert property (@(posedge clk) disable iff (!rst_n)
        m_arvalid && !m_arready |=> m_arvalid && $stable({m_araddr,m_arlen,m_arsize,m_arburst}));
    assert property (@(posedge clk) disable iff (!rst_n)
        s_rvalid && !s_rready |=> s_rvalid && $stable({s_rdata,s_rresp,s_rlast}));
    always_ff @(posedge clk) if (rst_n && enable && s_arvalid && s_arready)
        assert(s_arsize == 3'd2 && s_araddr[1:0] == 0 && s_arburst == 2'b01);
`endif
endmodule
