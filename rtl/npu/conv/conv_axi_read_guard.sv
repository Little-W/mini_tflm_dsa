// SPDX-License-Identifier: Apache-2.0
// The native block DMA aligns reads to complete words and may fetch tail
// padding. During Conv, restrict external reads to the four real allocations
// (OHWI weights, bias, multipliers, shifts), returning zero for padding lanes.
// Safe bursts remain bursts. Boundary requests use single word/byte transfers.
// GEMM can retain its direct path while splitting bursts at 4 KiB boundaries.
module conv_axi_read_guard #(
    parameter int ADDR_W=32, DATA_W=32,
    parameter bit SPLIT_GEMM_4K=1'b0,
    parameter int READ_OUTSTANDING=4
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
    localparam int BUS_BYTES=DATA_W/8;
    localparam int BUS_SHIFT=$clog2(BUS_BYTES);
    typedef enum logic [2:0] {IDLE, FAST_AR, FAST_R, PREP, WORD_AR, WORD_R, OUT} state_t;
    state_t state;
    logic [31:0] base_q[4];
    logic [32:0] end_q[4];
    // Keep the carry while returning padded tail beats. A DMA burst starting
    // at 0xffff_fffc must never wrap into an unrelated low-address allocation.
    logic [32:0] addr_q;
    logic [7:0] len_q, beat_q;
    logic [BUS_BYTES-1:0] pending_mask, allowed_mask;
    logic [BUS_SHIFT-1:0] lane;
    logic whole_word, error_q;
    logic [DATA_W-1:0] word_q;
    logic fast_legal;
    logic [32:0] request_end;
    localparam int OUTS_W = READ_OUTSTANDING < 2 ? 1 : $clog2(READ_OUTSTANDING+1);
    logic [OUTS_W-1:0] direct_outstanding;
    wire direct_mode = SPLIT_GEMM_4K && !enable && state == IDLE;
    wire direct_ar = direct_mode && fast_legal && s_arvalid && m_arready;
    wire direct_last = direct_mode && m_rvalid && s_rready && m_rlast;
    logic [BUS_BYTES-1:0] allocation_mask [4];
    // Accepted AXI words and the internal word cursor are bus aligned.
    // Share the word-address comparisons across every byte in each range.
    for (genvar allocation=0; allocation<4; allocation++) begin : g_allocation_mask
        wire base_present = base_q[allocation] != 0;
        wire after_base_word = addr_q[32:BUS_SHIFT] > {1'b0,base_q[allocation][31:BUS_SHIFT]};
        wire at_base_word = addr_q[32:BUS_SHIFT] == {1'b0,base_q[allocation][31:BUS_SHIFT]};
        wire before_end_word = addr_q[32:BUS_SHIFT] < end_q[allocation][32:BUS_SHIFT];
        wire at_end_word = addr_q[32:BUS_SHIFT] == end_q[allocation][32:BUS_SHIFT];
        for (genvar byte_lane=0; byte_lane<BUS_BYTES; byte_lane++) begin : g_byte_lane
            wire after_base_byte, before_end_byte;
            if (byte_lane==BUS_BYTES-1) begin : g_last_byte
                assign after_base_byte = 1'b1;
                assign before_end_byte = 1'b0;
            end else begin : g_offset_compare
                assign after_base_byte = BUS_SHIFT'(byte_lane) >= base_q[allocation][BUS_SHIFT-1:0];
                assign before_end_byte = BUS_SHIFT'(byte_lane) < end_q[allocation][BUS_SHIFT-1:0];
            end
            assign allocation_mask[allocation][byte_lane] = base_present &&
                (after_base_word || (at_base_word && after_base_byte)) &&
                (before_end_word || (at_end_word && before_end_byte));
        end
    end
    assign allowed_mask = (!enable && !addr_q[32] ? {BUS_BYTES{1'b1}} : {BUS_BYTES{1'b0}}) |
        allocation_mask[0] | allocation_mask[1] | allocation_mask[2] | allocation_mask[3];
    always_comb begin
        request_end = 33'(s_araddr) + ((33'(s_arlen) + 33'd1) << BUS_SHIFT);
        fast_legal = !enable;
        for (int i=0; i<4; i++)
            if (base_q[i] != 0 && 33'(s_araddr) >= {1'b0,base_q[i]} && request_end <= end_q[i])
                fast_legal = 1'b1;
        fast_legal = fast_legal && s_arsize == 3'(BUS_SHIFT) && s_arburst == 2'b01 &&
                     s_araddr[BUS_SHIFT-1:0] == 0 &&
                     ({1'b0,s_araddr[11:0]} + ((13'(s_arlen)+13'd1)<<BUS_SHIFT) <= 13'd4096);
        lane = '0;
        for (int b=BUS_BYTES-1; b>=0; b--) if(pending_mask[b]) lane=BUS_SHIFT'(b);
        whole_word = &pending_mask;
    end
    assign idle = state == IDLE && direct_outstanding == 0;
    always_comb begin
        s_arready = m_arready; s_rvalid = m_rvalid; s_rdata = m_rdata;
        s_rresp = m_rresp; s_rlast = m_rlast;
        m_arvalid = s_arvalid; m_araddr = s_araddr; m_arlen = s_arlen;
        m_arsize = s_arsize; m_arburst = s_arburst; m_rready = s_rready;
        if (enable || SPLIT_GEMM_4K) begin
            s_arready = state == IDLE;
            s_rvalid = (state == FAST_R && m_rvalid) || state == OUT;
            s_rdata = state == OUT ? word_q : m_rdata;
            s_rresp = state == OUT ? (error_q ? 2'b10 : 2'b00) : m_rresp;
            s_rlast = state == OUT ? (beat_q == len_q) : m_rlast;
            m_arvalid = state == FAST_AR || state == WORD_AR;
            m_araddr = ADDR_W'(addr_q) + (state == WORD_AR && !whole_word ? ADDR_W'(lane) : ADDR_W'(0));
            m_arlen = state == FAST_AR ? len_q : 8'd0;
            m_arsize = (state == WORD_AR && !whole_word) ? 3'd0 : 3'(BUS_SHIFT);
            m_arburst = 2'b01;
            m_rready = state == FAST_R ? s_rready : state == WORD_R;
            if (direct_mode) begin
                s_arready = fast_legal ? m_arready : direct_outstanding == 0;
                m_arvalid = s_arvalid && fast_legal;
                m_araddr = s_araddr; m_arlen = s_arlen;
                m_arsize = s_arsize; m_arburst = s_arburst;
                s_rvalid = m_rvalid; s_rdata = m_rdata;
                s_rresp = m_rresp; s_rlast = m_rlast; m_rready = s_rready;
            end
        end
    end
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= IDLE; addr_q <= '0; len_q <= '0; beat_q <= '0;
            word_q <= '0; pending_mask <= '0; error_q <= 1'b0;
            direct_outstanding <= '0;
            for (int i=0;i<4;i++) begin base_q[i]<='0; end_q[i]<='0; end
        end else begin
            if (cfg_valid) begin
                for (int i=0;i<4;i++) begin base_q[i]<=cfg_base[i]; end_q[i]<=cfg_end[i]; end
            end
            case ({direct_ar,direct_last})
                2'b10: direct_outstanding <= direct_outstanding + 1'b1;
                2'b01: direct_outstanding <= direct_outstanding - 1'b1;
                default: ;
            endcase
            if (enable || SPLIT_GEMM_4K) case (state)
                IDLE: if (s_arvalid && s_arready) begin
                    if (!direct_mode || !fast_legal) begin
                        addr_q <= 33'(s_araddr); len_q <= s_arlen; beat_q <= '0;
                        state <= fast_legal ? FAST_AR : PREP;
                    end
                end
                FAST_AR: if (m_arready) state <= FAST_R;
                FAST_R: if (m_rvalid && m_rready && m_rlast) state <= IDLE;
                PREP: begin
                    word_q <= '0; error_q <= !enable && addr_q[32]; pending_mask <= allowed_mask;
                    state <= allowed_mask == 0 ? OUT : WORD_AR;
                end
                WORD_AR: if (m_arready) state <= WORD_R;
                WORD_R: if (m_rvalid && m_rready) begin
                    error_q <= error_q || m_rresp[1] || !m_rlast;
                    if (whole_word) begin
                        word_q <= m_rdata; pending_mask <= '0; state <= OUT;
                    end else begin
                        word_q[8*lane +: 8] <= m_rdata[8*lane +: 8];
                        pending_mask <= pending_mask & ~(BUS_BYTES'(1) << lane);
                        state <= (pending_mask & ~(BUS_BYTES'(1) << lane)) == 0 ? OUT : WORD_AR;
                    end
                end
                OUT: if (s_rready) begin
                    if (beat_q == len_q) state <= IDLE;
                    else begin addr_q <= addr_q + 33'(BUS_BYTES); beat_q <= beat_q + 8'd1; state <= PREP; end
                end
                default: state <= IDLE;
            endcase
        end
    end

`ifdef NPU_SIM_ASSERT
    initial begin : check_m_arvalid_stability
        logic stalled;
        logic [$bits({m_araddr,m_arlen,m_arsize,m_arburst})-1:0] held_payload;
        stalled=1'b0;
        forever begin
            @(posedge clk);
            if (!rst_n) stalled=1'b0;
            else begin
                if (stalled) assert(m_arvalid && {m_araddr,m_arlen,m_arsize,m_arburst}==held_payload);
                stalled=m_arvalid && !m_arready;
                held_payload={m_araddr,m_arlen,m_arsize,m_arburst};
            end
        end
    end
    initial begin : check_s_rvalid_stability
        logic stalled;
        logic [$bits({s_rdata,s_rresp,s_rlast})-1:0] held_payload;
        stalled=1'b0;
        forever begin
            @(posedge clk);
            if (!rst_n) stalled=1'b0;
            else begin
                if (stalled) assert(s_rvalid && {s_rdata,s_rresp,s_rlast}==held_payload);
                stalled=s_rvalid && !s_rready;
                held_payload={s_rdata,s_rresp,s_rlast};
            end
        end
    end
    initial forever @(posedge clk) if (rst_n && (enable || SPLIT_GEMM_4K) && s_arvalid && s_arready)
        assert(s_arsize == 3'(BUS_SHIFT) && s_araddr[BUS_SHIFT-1:0] == 0 && s_arburst == 2'b01);
    initial forever @(posedge clk) if (rst_n && SPLIT_GEMM_4K) begin
        assert(direct_outstanding <= OUTS_W'(READ_OUTSTANDING));
        if (direct_last) assert(direct_outstanding != 0 || direct_ar);
        if (enable || state != IDLE) assert(direct_outstanding == 0);
    end
`endif
endmodule
