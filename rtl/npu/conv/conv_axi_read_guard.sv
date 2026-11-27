// SPDX-License-Identifier: Apache-2.0
// The native block DMA aligns reads to complete words and may fetch tail
// padding. During Conv, restrict external reads to the four real allocations
// (OHWI weights, bias, multipliers, shifts), returning zero for padding lanes.
// Safe bursts remain bursts. Boundary requests use single word/byte transfers.
// GEMM can retain its direct path while splitting bursts at 4 KiB boundaries.
module conv_axi_read_guard #( // 将外部读取限制在已配置的有效字节区间，并处理尾部补零和突发边界。
    parameter int ADDR_W=32, DATA_W=32,
    parameter bit SPLIT_GEMM_4K=1'b0,
    parameter int READ_OUTSTANDING=4
) (
    input logic clk /* 模块工作时钟。 */, rst_n /* 低有效复位输入。 */, enable /* 启用卷积有效字节区间保护。 */, cfg_valid /* 接收四个允许读取的地址区间。 */,
    input logic [31:0] cfg_base[4], // 四个允许读取区间的起始字节地址。
    input logic [32:0] cfg_end[4], // 四个读取区间的右端地址，不包含该地址。
    input logic s_arvalid /* 上游 AXI 接口：读地址请求有效。 */, output logic s_arready /* 上游 AXI 接口：能够接收读地址请求。 */,
    input logic [ADDR_W-1:0] s_araddr, // 上游 AXI 接口：读事务起始字节地址。
    input logic [7:0] s_arlen, // 上游 AXI 接口：读突发的传输拍数减一。
    input logic [2:0] s_arsize, // 上游 AXI 接口：每拍读取字节数的二进制对数。
    input logic [1:0] s_arburst, // 上游 AXI 接口：读事务的突发类型。
    output logic s_rvalid /* 上游 AXI 接口：返回的读取数据有效。 */, input logic s_rready /* 上游 AXI 接口：能够接收读取响应。 */,
    output logic [DATA_W-1:0] s_rdata, // 上游 AXI 接口：读取响应的数据。
    output logic [1:0] s_rresp /* 上游 AXI 接口：读取响应的状态编码。 */, output logic s_rlast /* 上游 AXI 接口：当前读突发的最后一拍。 */,
    output logic m_arvalid /* 外部 AXI 接口：读地址请求有效。 */, o_arb_arvalid /* 提供给共享读仲裁器的当前地址请求资格。 */, input logic m_arready /* 外部 AXI 接口：能够接收读地址请求。 */,
    output logic [ADDR_W-1:0] m_araddr, // 外部 AXI 接口：读事务起始字节地址。
    output logic [7:0] m_arlen, // 外部 AXI 接口：读突发的传输拍数减一。
    output logic [2:0] m_arsize, // 外部 AXI 接口：每拍读取字节数的二进制对数。
    output logic [1:0] m_arburst, // 外部 AXI 接口：读事务的突发类型。
    input logic m_rvalid /* 外部 AXI 接口：返回的读取数据有效。 */, output logic m_rready /* 外部 AXI 接口：能够接收读取响应。 */,
    input logic [DATA_W-1:0] m_rdata, // 外部 AXI 接口：读取响应的数据。
    input logic [1:0] m_rresp /* 外部 AXI 接口：读取响应的状态编码。 */, input logic m_rlast /* 外部 AXI 接口：当前读突发的最后一拍。 */,
    output logic idle // 地址保护逻辑及已接收读取事务均已空闲。
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
    logic [32:0] request_addr_ext;
    logic request_page_fits;
    logic request_format_legal;
    logic direct_legal;
    (* keep *) logic [3:0] fast_allocation;
    logic [ADDR_W-1:0] word_addr;
    logic [ADDR_W-BUS_SHIFT-1:0] word_addr_upper_next;
    logic [32:0] next_word_address;
    logic unused_word_addr_upper_carry;
    logic [BUS_SHIFT-1:0] selected_lane;
    logic [BUS_SHIFT:0] word_addr_low_sum;
    logic [ADDR_W-1:0] selected_word_addr;
    localparam int OUTS_W = READ_OUTSTANDING < 2 ? 1 : $clog2(READ_OUTSTANDING+1);
    logic [OUTS_W-1:0] direct_outstanding;
    wire direct_mode = SPLIT_GEMM_4K && !enable && state == IDLE;
    wire direct_ar = direct_mode && direct_legal && s_arvalid && m_arready;
    wire direct_last = direct_mode && m_rvalid && s_rready && m_rlast;
    (* keep = 1 *) logic [BUS_BYTES-1:0] allocation_mask [4];
    (* keep = 1 *) logic [3:0] allocation_has_byte;
    logic allowed_word_has_byte;
    // Accepted AXI words and the internal word cursor are bus aligned.
    // Share the word-address comparisons across every byte in each range.
    for (genvar allocation=0; allocation<4; allocation++) begin : g_allocation_mask
        wire base_present = base_q[allocation] != 0;
        localparam int p_word_width = 33 - BUS_SHIFT;
        logic [BUS_BYTES-1:0] before_end_byte_mask, overlapping_byte_mask;
        wire after_base_word, before_end_word;
        wire at_base_word, at_end_word;
        // 各字节分组并行比较完整字地址，范围选择只组合比较结果。
        (* keep_hierarchy = "yes" *) unsigned_compare #(.p_width(p_word_width)) u_base_word (
            .i_a({1'b0,base_q[allocation][31:BUS_SHIFT]}),
            .i_b(addr_q[32:BUS_SHIFT]),
            .o_less(after_base_word), .o_equal(at_base_word));
        (* keep_hierarchy = "yes" *) unsigned_compare #(.p_width(p_word_width)) u_end_word (
            .i_a(addr_q[32:BUS_SHIFT]), .i_b(end_q[allocation][32:BUS_SHIFT]),
            .o_less(before_end_word), .o_equal(at_end_word));
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
            assign before_end_byte_mask[byte_lane] = before_end_byte;
            assign overlapping_byte_mask[byte_lane] = after_base_byte && before_end_byte;
        end
        // 状态更新使用区间是否含有字节的条件，字节掩码独立保存到数据返回阶段。
        // 低位范围继续由逐字节比较归并，保留未知输入的四态行为。
        // 字内边界与完整字范围并行判断，再合并为状态推进条件。
        (* keep = 1 *) logic before_end_present, overlapping_present;
        (* keep = 1 *) logic allocation_before_end, allocation_at_end;
        assign before_end_present = |before_end_byte_mask;
        assign overlapping_present = |overlapping_byte_mask;
        assign allocation_before_end = before_end_word && (after_base_word || at_base_word);
        assign allocation_at_end = at_end_word &&
            ((after_base_word && before_end_present) || (at_base_word && overlapping_present));
        assign allocation_has_byte[allocation] = base_present &&
            (allocation_before_end || allocation_at_end);
    end
    assign allowed_mask = (!enable && !addr_q[32] ? {BUS_BYTES{1'b1}} : {BUS_BYTES{1'b0}}) |
        allocation_mask[0] | allocation_mask[1] | allocation_mask[2] | allocation_mask[3];
    assign allowed_word_has_byte = (!enable && !addr_q[32]) || (|allocation_has_byte);

    assign request_addr_ext = 33'(s_araddr);
    if (BUS_SHIFT <= 4) begin : g_page_range
        localparam int p_page_word_w = 12 - BUS_SHIFT;
        logic [p_page_word_w:0] request_last_word;
        logic request_end_wrap;

        // 页内末字索引只需首字索引加ARLEN，最高位直接表示请求是否跨页。
        // 页内末字使用三位分组进位，随后与各区间的结束位置并行比较。
        logic unused_last_word_carry;
        parallel_prefix_add #(.p_width(p_page_word_w+1), .p_group_width(3), .p_preserve_groups(1'b1)) u_last_word (
            .i_a({1'b0, request_addr_ext[11:BUS_SHIFT]}), .i_b((p_page_word_w+1)'(s_arlen)),
            .i_carry(1'b0), .o_sum(request_last_word), .o_carry(unused_last_word_carry));
        conv_guard_page_boundary #(.p_width(p_page_word_w)) u_page_boundary (
            .i_offset(request_addr_ext[11:BUS_SHIFT]), .i_length(s_arlen),
            .o_fits(request_page_fits)
        );
        // 保留33位地址运算的回绕语义；32位地址配置会将此项化简为零。
        assign request_end_wrap = (&request_addr_ext[32:12]) && (&request_last_word[p_page_word_w-1:0]);
        for (genvar allocation=0; allocation<4; allocation++) begin : g_allocation
            wire below_base, before_end_page;
            wire unused_base_equal, unused_page_equal;
            conv_guard_range_compare #(.p_width(33)) u_request_base (
                .i_a(request_addr_ext), .i_b({1'b0,base_q[allocation]}),
                .o_less(below_base), .o_equal(unused_base_equal));
            conv_guard_range_compare #(.p_width(21)) u_request_end_page (
                .i_a(request_addr_ext[32:12]), .i_b(end_q[allocation][32:12]),
                .o_less(before_end_page), .o_equal(unused_page_equal));
            // 结束地址为开区间端点，页号关系与页内末字同时计算。
            (* keep = 1 *) logic same_end_page, before_end_offset;
            assign same_end_page = request_addr_ext[32:12] == end_q[allocation][32:12];
            assign before_end_offset = request_last_word < {1'b0, end_q[allocation][11:BUS_SHIFT]};
            assign fast_allocation[allocation] = base_q[allocation] != 0 && !below_base &&
                (request_end_wrap || before_end_page || (same_end_page && before_end_offset));
        end
    end else begin : g_wide_bus_range
        logic [32:0] request_end;

        assign request_end = request_addr_ext + ((33'(s_arlen) + 33'd1) << BUS_SHIFT);
        assign request_page_fits = {1'b0, s_araddr[11:0]} + ((13'(s_arlen) + 13'd1) << BUS_SHIFT) <= 13'd4096;
        for (genvar allocation=0; allocation<4; allocation++) begin : g_allocation
            wire below_base, after_end;
            wire unused_base_equal, unused_end_equal;
            conv_guard_range_compare #(.p_width(33)) u_request_base (
                .i_a(request_addr_ext), .i_b({1'b0,base_q[allocation]}),
                .o_less(below_base), .o_equal(unused_base_equal));
            unsigned_compare #(.p_width(33)) u_request_end (
                .i_a(end_q[allocation]), .i_b(request_end),
                .o_less(after_end), .o_equal(unused_end_equal));
            assign fast_allocation[allocation] = base_q[allocation] != 0 &&
                !below_base && !after_end;
        end
    end

    // 直接传输只检查 AXI 请求格式和页范围；分配区间检查由卷积请求使用。
    assign request_format_legal = s_arsize == 3'(BUS_SHIFT) &&
                                  s_arburst == 2'b01 && s_araddr[BUS_SHIFT-1:0] == 0;
    assign direct_legal = request_format_legal && request_page_fits;
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
    // 下一字地址保留第三十三位，地址更新与保护范围比较分别使用完整结果。
    assign next_word_address = addr_q + 33'(BUS_BYTES);
    assign idle = state == IDLE && direct_outstanding == 0;
    // 通道仲裁直接读取保护模式的待发状态，直通请求继续使用完整格式和页范围检查。
    assign o_arb_arvalid = enable && (state == FAST_AR || state == WORD_AR);
    // 单字返回独立接收；直通与整段返回并行选择下游就绪状态。
    if (SPLIT_GEMM_4K) begin : g_split_response_ready
        assign m_rready = state == WORD_R ||
            (s_rready && ((state == FAST_R) || (!enable && state == IDLE)));
    end else begin : g_response_ready
        assign m_rready = (enable && state == WORD_R) ||
            (s_rready && (!enable || state == FAST_R));
    end
    logic m_arvalid_reference;
    logic parallel_read_valid;
    if (SPLIT_GEMM_4K) begin : g_parallel_read_valid
        logic stored_request, direct_request;
        assign stored_request = state == FAST_AR || state == WORD_AR;
        assign direct_request = !enable && state == IDLE && s_arvalid && request_format_legal;
        conv_guard_read_valid u_valid (
            .i_stored(stored_request), .i_direct(direct_request),
            .i_page(request_page_fits), .o_valid(parallel_read_valid)
        );
        always_comb begin
            case (^{enable,state,s_arvalid,request_format_legal,request_page_fits})
                1'b0, 1'b1: m_arvalid = parallel_read_valid;
                default: m_arvalid = m_arvalid_reference;
            endcase
        end
    end else begin : g_direct_read_valid
        assign parallel_read_valid = m_arvalid_reference;
        assign m_arvalid = m_arvalid_reference;
    end
    always_comb begin
        s_arready = m_arready; s_rvalid = m_rvalid; s_rdata = m_rdata;
        s_rresp = m_rresp; s_rlast = m_rlast;
        m_arvalid_reference = s_arvalid; m_araddr = s_araddr; m_arlen = s_arlen;
        m_arsize = s_arsize; m_arburst = s_arburst;
        if (enable || SPLIT_GEMM_4K) begin
            s_arready = state == IDLE;
            s_rvalid = (state == FAST_R && m_rvalid) || state == OUT;
            s_rdata = state == OUT ? word_q : m_rdata;
            s_rresp = state == OUT ? (error_q ? 2'b10 : 2'b00) : m_rresp;
            s_rlast = state == OUT ? (beat_q == len_q) : m_rlast;
            m_arvalid_reference = state == FAST_AR || state == WORD_AR;
            m_araddr = selected_word_addr;
            m_arlen = state == FAST_AR ? len_q : 8'd0;
            m_arsize = (state == WORD_AR && !whole_word) ? 3'd0 : 3'(BUS_SHIFT);
            m_arburst = 2'b01;
            if (direct_mode) begin
                s_arready = direct_legal ? m_arready : direct_outstanding == 0;
                m_arvalid_reference = s_arvalid && direct_legal;
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
                    state <= !allowed_word_has_byte ? OUT : WORD_AR;
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
                    else begin addr_q <= next_word_address; beat_q <= beat_q + 8'd1; state <= PREP; end
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
