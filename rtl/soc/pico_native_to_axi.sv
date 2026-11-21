module pico_native_to_axi #(
    parameter int unsigned ADDR_WIDTH = 32,
    parameter int unsigned DATA_WIDTH = 32,
    parameter int unsigned ICACHE_LINES = 64,
    parameter int unsigned ICACHE_LINE_WORDS = 4,
    parameter bit          ENABLE_ICACHE = 1'b1,
    parameter bit          REGISTER_RESPONSE = 1'b0
) (
    input  wire                       clk,
    input  wire                       rst_n,

    input  wire                       mem_valid,
    input  wire                       mem_instr,
    input  wire [ADDR_WIDTH-1:0]      mem_addr,
    input  wire [DATA_WIDTH-1:0]      mem_wdata,
    input  wire [DATA_WIDTH/8-1:0]    mem_wstrb,
    output wire                       mem_ready,
    output wire [DATA_WIDTH-1:0]      mem_rdata,

    output wire                       m_axi_arvalid,
    input  wire                       m_axi_arready,
    output wire [ADDR_WIDTH-1:0]      m_axi_araddr,
    output wire [3:0]                 m_axi_arcache,
    output wire [2:0]                 m_axi_arprot,
    output wire [1:0]                 m_axi_arlock,
    output wire [1:0]                 m_axi_arburst,
    output wire [7:0]                 m_axi_arlen,
    output wire [2:0]                 m_axi_arsize,

    output wire                       m_axi_awvalid,
    input  wire                       m_axi_awready,
    output wire [ADDR_WIDTH-1:0]      m_axi_awaddr,
    output wire [3:0]                 m_axi_awcache,
    output wire [2:0]                 m_axi_awprot,
    output wire [1:0]                 m_axi_awlock,
    output wire [1:0]                 m_axi_awburst,
    output wire [7:0]                 m_axi_awlen,
    output wire [2:0]                 m_axi_awsize,

    input  wire                       m_axi_rvalid,
    output wire                       m_axi_rready,
    input  wire [DATA_WIDTH-1:0]      m_axi_rdata,
    input  wire [1:0]                 m_axi_rresp,
    input  wire                       m_axi_rlast,

    output wire                       m_axi_wvalid,
    input  wire                       m_axi_wready,
    output wire [DATA_WIDTH-1:0]      m_axi_wdata,
    output wire [DATA_WIDTH/8-1:0]    m_axi_wstrb,
    output wire                       m_axi_wlast,

    input  wire                       m_axi_bvalid,
    output wire                       m_axi_bready,
    input  wire [1:0]                 m_axi_bresp
);

    localparam int unsigned BYTEW = DATA_WIDTH / 8;
    localparam int unsigned ADDR_LSB = $clog2(BYTEW);
    localparam logic [2:0] AXI_SIZE = (BYTEW <= 1) ? 3'd0 :
                                      (BYTEW <= 2) ? 3'd1 :
                                      (BYTEW <= 4) ? 3'd2 :
                                      (BYTEW <= 8) ? 3'd3 : 3'd4;
    localparam int unsigned IC_LINE_WORD_BITS =
        (ICACHE_LINE_WORDS <= 1) ? 1 : $clog2(ICACHE_LINE_WORDS);
    localparam int unsigned IC_INDEX_BITS =
        (ICACHE_LINES <= 1) ? 1 : $clog2(ICACHE_LINES);
    localparam int unsigned IC_WORD_ADDR_WIDTH = ADDR_WIDTH - ADDR_LSB;
    localparam int unsigned IC_TAG_WIDTH =
        (IC_WORD_ADDR_WIDTH > (IC_LINE_WORD_BITS + IC_INDEX_BITS))
            ? (IC_WORD_ADDR_WIDTH - IC_LINE_WORD_BITS - IC_INDEX_BITS) : 1;
    localparam int unsigned IC_LINE_BYTE_LSB = ADDR_LSB + IC_LINE_WORD_BITS;
    localparam int unsigned ICACHE_WORDS = ICACHE_LINES * ICACHE_LINE_WORDS;
    localparam int unsigned IC_DATA_ADDR_BITS = IC_INDEX_BITS + IC_LINE_WORD_BITS;

    logic [ADDR_WIDTH-1:0]   addr_q;
    logic [DATA_WIDTH-1:0]   wdata_q;
    logic [DATA_WIDTH/8-1:0] wstrb_q;
    logic                    instr_q;
    logic                    read_busy_q;
    logic                    ar_pending_q;
    logic [7:0]              arlen_q;
    logic                    ic_fill_q;
    logic [IC_INDEX_BITS-1:0]     ic_fill_index_q;
    logic [IC_TAG_WIDTH-1:0]      ic_fill_tag_q;
    logic [IC_LINE_WORD_BITS-1:0] ic_fill_beat_q;
    logic [IC_LINE_WORD_BITS-1:0] ic_fill_req_word_q;
    logic [DATA_WIDTH-1:0]        ic_fill_req_data_q;
    logic                    ic_req_q;
    logic                    rsp_valid_q;
    logic [DATA_WIDTH-1:0]   rsp_data_q;
    logic [ADDR_WIDTH-1:0]   ic_req_line_addr_q;
    logic [IC_INDEX_BITS-1:0]     ic_req_index_q;
    logic [IC_TAG_WIDTH-1:0]      ic_req_tag_q;
    logic [IC_LINE_WORD_BITS-1:0] ic_req_word_q;
    logic [DATA_WIDTH-1:0]        ic_lookup_data_q;
    logic [IC_TAG_WIDTH-1:0]      ic_lookup_tag_q;
    logic                         ic_lookup_valid_q;
    logic                    write_busy_q;
    logic                    aw_pending_q;
    logic                    w_pending_q;

    logic [DATA_WIDTH-1:0] ic_data_q [0:ICACHE_WORDS-1];
    logic [IC_TAG_WIDTH-1:0] ic_tag_q [0:ICACHE_LINES-1];
    logic ic_valid_q [0:ICACHE_LINES-1];

    wire bridge_idle   = !read_busy_q && !write_busy_q && !ic_req_q && !rsp_valid_q;
    wire mem_write_req = mem_valid && (mem_wstrb != '0);
    wire mem_read_req  = mem_valid && (mem_wstrb == '0);
    wire new_read_req  = bridge_idle && mem_read_req;
    wire new_write_req = bridge_idle && mem_write_req;

    wire [IC_WORD_ADDR_WIDTH-1:0] mem_word_addr =
        mem_addr[ADDR_WIDTH-1:ADDR_LSB];
    wire [IC_LINE_WORD_BITS-1:0] mem_ic_word =
        mem_word_addr[IC_LINE_WORD_BITS-1:0];
    wire [IC_INDEX_BITS-1:0] mem_ic_index =
        mem_word_addr[IC_LINE_WORD_BITS +: IC_INDEX_BITS];
    wire [IC_TAG_WIDTH-1:0] mem_ic_tag =
        mem_word_addr[IC_WORD_ADDR_WIDTH-1 -: IC_TAG_WIDTH];
    wire [ADDR_WIDTH-1:0] mem_ic_line_addr =
        {mem_addr[ADDR_WIDTH-1:IC_LINE_BYTE_LSB], {IC_LINE_BYTE_LSB{1'b0}}};
    wire icacheable_read = ENABLE_ICACHE && mem_instr && mem_read_req;
    wire new_ic_read_req = new_read_req && icacheable_read;
    wire new_direct_read_req = new_read_req && !icacheable_read;
    wire icache_hit = ic_req_q && ic_lookup_valid_q &&
                      (ic_lookup_tag_q == ic_req_tag_q);
    wire icache_miss = ic_req_q && !icache_hit;
    wire [ADDR_WIDTH-1:0] read_axi_addr = icache_miss ? ic_req_line_addr_q :
                                                         mem_addr;
    wire [7:0] read_axi_len = icache_miss ? 8'(ICACHE_LINE_WORDS - 1) :
                                            8'd0;
    wire read_axi_req = new_direct_read_req || icache_miss;
    wire [IC_DATA_ADDR_BITS-1:0] mem_ic_data_addr =
        {mem_ic_index, mem_ic_word};
    wire [IC_DATA_ADDR_BITS-1:0] fill_ic_data_addr =
        {ic_fill_index_q, ic_fill_beat_q};

    wire ar_fire = m_axi_arvalid && m_axi_arready;
    wire r_fire  = m_axi_rvalid && m_axi_rready;
    wire aw_fire = m_axi_awvalid && m_axi_awready;
    wire w_fire  = m_axi_wvalid && m_axi_wready;
    wire b_fire  = m_axi_bvalid && m_axi_bready;

    wire read_done_fire = r_fire && (!ic_fill_q || m_axi_rlast);
    wire ic_fill_req_current = ic_fill_q &&
                               (ic_fill_beat_q == ic_fill_req_word_q);
    wire [DATA_WIDTH-1:0] ic_fill_rsp_data =
        ic_fill_req_current ? m_axi_rdata : ic_fill_req_data_q;

    assign m_axi_arvalid = read_axi_req || ar_pending_q;
    assign m_axi_araddr  = read_axi_req ? read_axi_addr : addr_q;
    assign m_axi_arprot  = (new_direct_read_req ? mem_instr :
                            icache_miss ? 1'b1 : instr_q) ? 3'b100 : 3'b000;

    assign m_axi_awvalid = new_write_req || (write_busy_q && aw_pending_q);
    assign m_axi_awaddr  = new_write_req ? mem_addr : addr_q;
    assign m_axi_awprot  = 3'b000;
    assign m_axi_wvalid  = new_write_req || (write_busy_q && w_pending_q);
    assign m_axi_wdata   = new_write_req ? mem_wdata : wdata_q;
    assign m_axi_wstrb   = new_write_req ? mem_wstrb : wstrb_q;

    assign m_axi_rready = read_busy_q;
    assign m_axi_bready = write_busy_q || new_write_req;
    assign mem_ready = (!ENABLE_ICACHE && REGISTER_RESPONSE) ? rsp_valid_q :
        (rsp_valid_q || read_done_fire || b_fire);
    if (!ENABLE_ICACHE) begin : g_direct_response
        if (REGISTER_RESPONSE) begin : g_registered
            // 响应数据与完成标志同时保存，CPU 在下一周期接收完整结果。
            assign mem_rdata = rsp_data_q;
        end else begin : g_forwarded
            // CPU 只在读请求完成时采样数据，直接转发可分离握手控制与指令译码。
            assign mem_rdata = m_axi_rdata;
        end
    end else begin : g_cached_response
        assign mem_rdata = rsp_valid_q ? rsp_data_q :
                           read_done_fire ? (ic_fill_q ? ic_fill_rsp_data : m_axi_rdata) : '0;
    end

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            for (int i = 0; i < ICACHE_LINES; i++) begin
                ic_valid_q[i] <= 1'b0;
                ic_tag_q[i]   <= '0;
            end
            addr_q       <= '0;
            wdata_q      <= '0;
            wstrb_q      <= '0;
            instr_q      <= 1'b0;
            read_busy_q  <= 1'b0;
            ar_pending_q <= 1'b0;
            arlen_q      <= 8'd0;
            ic_fill_q    <= 1'b0;
            ic_fill_index_q <= '0;
            ic_fill_tag_q   <= '0;
            ic_fill_beat_q  <= '0;
            ic_fill_req_word_q <= '0;
            ic_fill_req_data_q <= '0;
            ic_req_q <= 1'b0;
            rsp_valid_q <= 1'b0;
            rsp_data_q <= '0;
            ic_req_line_addr_q <= '0;
            ic_req_index_q <= '0;
            ic_req_tag_q <= '0;
            ic_req_word_q <= '0;
            ic_lookup_tag_q <= '0;
            ic_lookup_valid_q <= 1'b0;
            write_busy_q <= 1'b0;
            aw_pending_q <= 1'b0;
            w_pending_q  <= 1'b0;
        end else begin
            rsp_valid_q <= 1'b0;
            if (!ENABLE_ICACHE && REGISTER_RESPONSE) begin
                rsp_valid_q <= read_done_fire || b_fire;
                if (read_done_fire) begin
                    rsp_data_q <= m_axi_rdata;
                end
            end

            if (new_ic_read_req) begin
                ic_req_q <= 1'b1;
                ic_req_line_addr_q <= mem_ic_line_addr;
                ic_req_index_q <= mem_ic_index;
                ic_req_tag_q <= mem_ic_tag;
                ic_req_word_q <= mem_ic_word;
                ic_lookup_tag_q <= ic_tag_q[mem_ic_index];
                ic_lookup_valid_q <= ic_valid_q[mem_ic_index];
                read_busy_q  <= 1'b0;
                ar_pending_q <= 1'b0;
                ic_fill_q    <= 1'b0;
            end else if (ic_req_q) begin
                if (icache_hit) begin
                    ic_req_q <= 1'b0;
                    rsp_valid_q <= 1'b1;
                    rsp_data_q <= ic_lookup_data_q;
                    read_busy_q  <= 1'b0;
                    ar_pending_q <= 1'b0;
                    ic_fill_q    <= 1'b0;
                end else begin
                    addr_q       <= ic_req_line_addr_q;
                    instr_q      <= 1'b1;
                    arlen_q      <= read_axi_len;
                    read_busy_q  <= 1'b1;
                    ar_pending_q <= !m_axi_arready;
                    ic_fill_q    <= 1'b1;
                    ic_fill_index_q <= ic_req_index_q;
                    ic_fill_tag_q   <= ic_req_tag_q;
                    ic_fill_beat_q  <= '0;
                    ic_fill_req_word_q <= ic_req_word_q;
                    ic_fill_req_data_q <= '0;
                    ic_req_q <= 1'b0;
                end
            end else if (new_direct_read_req) begin
                addr_q       <= mem_addr;
                instr_q      <= mem_instr;
                arlen_q      <= read_axi_len;
                read_busy_q  <= 1'b1;
                ar_pending_q <= !m_axi_arready;
                ic_fill_q    <= 1'b0;
                ic_fill_beat_q  <= '0;
                ic_fill_req_word_q <= '0;
                ic_fill_req_data_q <= '0;
            end else if (read_busy_q) begin
                if (ar_pending_q && m_axi_arready) begin
                    ar_pending_q <= 1'b0;
                end
                if (r_fire && ic_fill_q) begin
                    if (ic_fill_beat_q == ic_fill_req_word_q) begin
                        ic_fill_req_data_q <= m_axi_rdata;
                    end
                    ic_fill_beat_q <= ic_fill_beat_q + 1'b1;
                    if (m_axi_rlast) begin
                        ic_valid_q[ic_fill_index_q] <= 1'b1;
                        ic_tag_q[ic_fill_index_q] <= ic_fill_tag_q;
                        ic_fill_q <= 1'b0;
                        ic_fill_beat_q <= '0;
                    end
                end
                if (r_fire) begin
                    if (!ic_fill_q || m_axi_rlast) begin
                        read_busy_q  <= 1'b0;
                        ar_pending_q <= 1'b0;
                    end
                end
            end

            if (new_write_req) begin
                addr_q       <= mem_addr;
                wdata_q      <= mem_wdata;
                wstrb_q      <= mem_wstrb;
                write_busy_q <= !b_fire;
                aw_pending_q <= !aw_fire;
                w_pending_q  <= !w_fire;
                if (ENABLE_ICACHE) begin
                    ic_valid_q[mem_ic_index] <= 1'b0;
                end
            end else if (write_busy_q) begin
                if (aw_fire) begin
                    aw_pending_q <= 1'b0;
                end
                if (w_fire) begin
                    w_pending_q <= 1'b0;
                end
                if (b_fire) begin
                    write_busy_q <= 1'b0;
                    aw_pending_q <= 1'b0;
                    w_pending_q  <= 1'b0;
                end
            end
        end
    end

    always_ff @(posedge clk) begin
        if (new_ic_read_req) begin
            ic_lookup_data_q <= ic_data_q[mem_ic_data_addr];
        end
        if (r_fire && ic_fill_q) begin
            ic_data_q[fill_ic_data_addr] <= m_axi_rdata;
        end
    end

    assign m_axi_arcache = 4'b0011;
    assign m_axi_arlock  = 2'b00;
    assign m_axi_arburst = 2'b01;
    assign m_axi_arlen   = read_axi_req ? read_axi_len : arlen_q;
    assign m_axi_arsize  = AXI_SIZE;

    assign m_axi_awcache = 4'b0011;
    assign m_axi_awlock  = 2'b00;
    assign m_axi_awburst = 2'b01;
    assign m_axi_awlen   = 8'd0;
    assign m_axi_awsize  = AXI_SIZE;
    assign m_axi_wlast   = 1'b1;



    wire _unused_axi_resp = |m_axi_rresp | m_axi_rlast | |m_axi_bresp;

endmodule
