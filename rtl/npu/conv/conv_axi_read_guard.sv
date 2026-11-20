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
    output logic m_arvalid, o_arb_arvalid, input logic m_arready,
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
`ifdef SYNTHESIS
`ifdef ASIC_SYNTHESIS
    localparam bit p_fpga_page_range = 1'b0;
`else
    localparam bit p_fpga_page_range = 1'b1;
`endif
`else
    localparam bit p_fpga_page_range = 1'b0;
`endif
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
    logic [32:0] request_addr_ext;
    logic generic_page_fits;
    logic request_format_legal;
    logic direct_legal;
    logic [3:0] fast_allocation;
    logic [ADDR_W-1:0] word_addr;
    logic [ADDR_W-BUS_SHIFT-1:0] word_addr_upper_next;
    logic unused_word_addr_upper_carry;
    logic [BUS_SHIFT-1:0] selected_lane;
    logic [BUS_SHIFT:0] word_addr_low_sum;
    logic [ADDR_W-1:0] selected_word_addr;
    localparam int OUTS_W = READ_OUTSTANDING < 2 ? 1 : $clog2(READ_OUTSTANDING+1);
    logic [OUTS_W-1:0] direct_outstanding;
    wire direct_mode = SPLIT_GEMM_4K && !enable && state == IDLE;
    wire direct_ar = direct_mode && direct_legal && s_arvalid && m_arready;
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

    assign request_addr_ext = 33'(s_araddr);
    if (BUS_SHIFT <= 4) begin : g_page_range
        localparam int p_page_word_w = 12 - BUS_SHIFT;
        logic [p_page_word_w:0] request_last_word;
        logic request_end_wrap;

        // 页内末字索引只需首字索引加ARLEN，最高位直接表示请求是否跨页。
        assign request_last_word = {1'b0, request_addr_ext[11:BUS_SHIFT]} + (p_page_word_w+1)'(s_arlen);
        // ARLEN 最多为八位。页内高位未全置一时，整个突发都位于当前页。
        // 其余情况并行比较两个四位字段，直接得到跨页条件。
        if (p_fpga_page_range) begin : g_fpga_tail
            logic [3:0] page_generate, page_propagate;
            logic lower_carry, page_high_full;
            logic [5:0] direct_i_value;
            logic unused_direct_o5;

            if (p_page_word_w > 8) begin : g_page_high
                assign page_high_full = &request_addr_ext[11:BUS_SHIFT+8];
            end else begin : g_page_eight
                assign page_high_full = 1'b1;
            end

            // 每个查找表同时产生两位加法的进位与传播条件。
            // 页内地址与ARLEN之和的最高进位由两组并行关系得到。
            for (genvar group_index = 0; group_index < 4; group_index++) begin : g_group
                logic [1:0] range_i_address, range_i_length;
                localparam logic [63:0] p_range_init = group_index == 3 ?
                    64'hec80_0000_1248_0000 : 64'hec80_ec80_1248_1248;
                logic range_i_enable, range_i_one;

                assign range_i_address = request_addr_ext[BUS_SHIFT+2*group_index +: 2];
                assign range_i_length = s_arlen[2*group_index +: 2];
                // 最高两位的进位同时检查页内高位，其余分组保留完整加法关系。
                assign range_i_enable = group_index == 3 ? page_high_full : 1'b0;
                assign range_i_one = 1'b1;
                LUT6_2 #(.INIT(p_range_init)) u_page_group (
                    .I0(range_i_address[0]), .I1(range_i_address[1]),
                    .I2(range_i_length[0]), .I3(range_i_length[1]),
                    .I4(range_i_enable), .I5(range_i_one),
                    .O5(page_propagate[group_index]), .O6(page_generate[group_index])
                );
            end
            assign lower_carry = page_generate[1] ||
                (page_propagate[1] && page_generate[0]);
            // 末级同时判断请求格式与页范围，握手控制直接读取完整判断结果。
            assign direct_i_value = {request_format_legal, lower_carry, page_propagate[2],
                page_generate[2], page_propagate[3], page_generate[3]};
            LUT6_2 #(.INIT(64'h1115_1515_0000_0000)) u_direct_legal (
                .I0(direct_i_value[0]), .I1(direct_i_value[1]), .I2(direct_i_value[2]),
                .I3(direct_i_value[3]), .I4(direct_i_value[4]), .I5(direct_i_value[5]),
                .O5(unused_direct_o5), .O6(direct_legal)
            );
        end else begin : g_generic_tail
            logic request_tail_fits;

            assign request_tail_fits =
                (s_arlen[7:4] < ~request_addr_ext[BUS_SHIFT+4 +: 4]) ||
                ((s_arlen[7:4] == ~request_addr_ext[BUS_SHIFT+4 +: 4]) &&
                 (s_arlen[3:0] <= ~request_addr_ext[BUS_SHIFT +: 4]));
            if (p_page_word_w > 8) begin : g_page_high
                assign generic_page_fits = !(&request_addr_ext[11:BUS_SHIFT+8]) || request_tail_fits;
            end else begin : g_page_eight
                assign generic_page_fits = request_tail_fits;
            end
        end
        // 保留33位地址运算的回绕语义；32位地址配置会将此项化简为零。
        assign request_end_wrap = (&request_addr_ext[32:12]) && (&request_last_word[p_page_word_w-1:0]);
        for (genvar allocation=0; allocation<4; allocation++) begin : g_allocation
            // 结束地址是开区间端点。页号和页内末字并行比较，避免完整地址加法后再比较。
            assign fast_allocation[allocation] = base_q[allocation] != 0 &&
                request_addr_ext >= {1'b0, base_q[allocation]} &&
                (request_end_wrap || request_addr_ext[32:12] < end_q[allocation][32:12] ||
                 (request_addr_ext[32:12] == end_q[allocation][32:12] &&
                  request_last_word < {1'b0, end_q[allocation][11:BUS_SHIFT]}));
        end
    end else begin : g_wide_bus_range
        logic [32:0] request_end;

        assign request_end = request_addr_ext + ((33'(s_arlen) + 33'd1) << BUS_SHIFT);
        assign generic_page_fits = {1'b0, s_araddr[11:0]} + ((13'(s_arlen) + 13'd1) << BUS_SHIFT) <= 13'd4096;
        for (genvar allocation=0; allocation<4; allocation++) begin : g_allocation
            assign fast_allocation[allocation] = base_q[allocation] != 0 &&
                request_addr_ext >= {1'b0, base_q[allocation]} && request_end <= end_q[allocation];
        end
    end

    // 直接传输只检查 AXI 请求格式和页范围；分配区间检查由卷积请求使用。
    assign request_format_legal = s_arsize == 3'(BUS_SHIFT) &&
                                  s_arburst == 2'b01 && s_araddr[BUS_SHIFT-1:0] == 0;
    if (!p_fpga_page_range || BUS_SHIFT > 4) begin : g_generic_direct_legal
        assign direct_legal = request_format_legal && generic_page_fits;
    end
    assign fast_legal = direct_legal && (!enable || (|fast_allocation));
    always_comb begin
        lane = '0;
        for (int b=BUS_BYTES-1; b>=0; b--) if(pending_mask[b]) lane=BUS_SHIFT'(b);
        whole_word = &pending_mask;
    end
    // 字节偏移只影响地址低位；上部地址提前加一，低位进位仅选择已经计算的结果。
    assign word_addr = ADDR_W'(addr_q);
    assign {unused_word_addr_upper_carry, word_addr_upper_next} =
        {1'b0, word_addr[ADDR_W-1:BUS_SHIFT]} + (ADDR_W-BUS_SHIFT+1)'(1);
    assign selected_lane = state == WORD_AR && !whole_word ? lane : '0;
    assign word_addr_low_sum = {1'b0, word_addr[BUS_SHIFT-1:0]} + {1'b0, selected_lane};
    assign selected_word_addr = {
        word_addr_low_sum[BUS_SHIFT] ? word_addr_upper_next : word_addr[ADDR_W-1:BUS_SHIFT],
        word_addr_low_sum[BUS_SHIFT-1:0]};
    assign idle = state == IDLE && direct_outstanding == 0;
    // 通道仲裁直接读取保护模式的待发状态，直通请求继续使用完整格式和页范围检查。
    assign o_arb_arvalid = enable && (state == FAST_AR || state == WORD_AR);
    // 单字返回独立接收；直通与整段返回并行选择下游就绪状态。
    if (p_fpga_page_range) begin : g_fpga_response_ready
        localparam logic [63:0] p_ready_table = SPLIT_GEMM_4K ?
            64'hFFFF_CC40_FFFF_CC40 : 64'hEEEE_CC44_EEEE_CC44;
        logic [4:0] response_i_conditions;
        logic unused_response_ready;

        assign response_i_conditions = {state == WORD_R, state == FAST_R,
            state == IDLE, s_rready, enable};
        LUT6_2 #(.INIT(p_ready_table)) u_response_ready (
            .I0(response_i_conditions[0]), .I1(response_i_conditions[1]),
            .I2(response_i_conditions[2]), .I3(response_i_conditions[3]),
            .I4(response_i_conditions[4]), .I5(1'b0),
            .O5(m_rready), .O6(unused_response_ready)
        );
    end else if (SPLIT_GEMM_4K) begin : g_split_response_ready
        assign m_rready = state == WORD_R ||
            (s_rready && ((state == FAST_R) || (!enable && state == IDLE)));
    end else begin : g_response_ready
        assign m_rready = (enable && state == WORD_R) ||
            (s_rready && (!enable || state == FAST_R));
    end
    always_comb begin
        s_arready = m_arready; s_rvalid = m_rvalid; s_rdata = m_rdata;
        s_rresp = m_rresp; s_rlast = m_rlast;
        m_arvalid = s_arvalid; m_araddr = s_araddr; m_arlen = s_arlen;
        m_arsize = s_arsize; m_arburst = s_arburst;
        if (enable || SPLIT_GEMM_4K) begin
            s_arready = state == IDLE;
            s_rvalid = (state == FAST_R && m_rvalid) || state == OUT;
            s_rdata = state == OUT ? word_q : m_rdata;
            s_rresp = state == OUT ? (error_q ? 2'b10 : 2'b00) : m_rresp;
            s_rlast = state == OUT ? (beat_q == len_q) : m_rlast;
            m_arvalid = state == FAST_AR || state == WORD_AR;
            m_araddr = selected_word_addr;
            m_arlen = state == FAST_AR ? len_q : 8'd0;
            m_arsize = (state == WORD_AR && !whole_word) ? 3'd0 : 3'(BUS_SHIFT);
            m_arburst = 2'b01;
            if (direct_mode) begin
                s_arready = direct_legal ? m_arready : direct_outstanding == 0;
                m_arvalid = s_arvalid && direct_legal;
                m_araddr = s_araddr; m_arlen = s_arlen;
                m_arsize = s_arsize; m_arburst = s_arburst;
                s_rvalid = m_rvalid; s_rdata = m_rdata;
                s_rresp = m_rresp; s_rlast = m_rlast;
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
