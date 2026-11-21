module write_page_measure #(
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
    logic  s_awvalid_q;
    always_ff @(posedge clk) s_awvalid_q <= s_awvalid;
    logic  s_awready_d;
    always_ff @(posedge clk) s_awready <= s_awready_d;
    logic [ADDR_W-1:0] s_awaddr_q;
    always_ff @(posedge clk) s_awaddr_q <= s_awaddr;
    logic [7:0] s_awlen_q;
    always_ff @(posedge clk) s_awlen_q <= s_awlen;
    logic [2:0] s_awsize_q;
    always_ff @(posedge clk) s_awsize_q <= s_awsize;
    logic [1:0] s_awburst_q;
    always_ff @(posedge clk) s_awburst_q <= s_awburst;
    logic  s_wvalid_q;
    always_ff @(posedge clk) s_wvalid_q <= s_wvalid;
    logic  s_wready_d;
    always_ff @(posedge clk) s_wready <= s_wready_d;
    logic [DATA_W-1:0] s_wdata_q;
    always_ff @(posedge clk) s_wdata_q <= s_wdata;
    logic [DATA_W/8-1:0] s_wstrb_q;
    always_ff @(posedge clk) s_wstrb_q <= s_wstrb;
    logic  s_wlast_q;
    always_ff @(posedge clk) s_wlast_q <= s_wlast;
    logic  s_bvalid_d;
    always_ff @(posedge clk) s_bvalid <= s_bvalid_d;
    logic  s_bready_q;
    always_ff @(posedge clk) s_bready_q <= s_bready;
    logic [1:0] s_bresp_d;
    always_ff @(posedge clk) s_bresp <= s_bresp_d;
    logic  m_awvalid_d;
    always_ff @(posedge clk) m_awvalid <= m_awvalid_d;
    logic  m_awready_q;
    always_ff @(posedge clk) m_awready_q <= m_awready;
    logic [ADDR_W-1:0] m_awaddr_d;
    always_ff @(posedge clk) m_awaddr <= m_awaddr_d;
    logic [7:0] m_awlen_d;
    always_ff @(posedge clk) m_awlen <= m_awlen_d;
    logic [2:0] m_awsize_d;
    always_ff @(posedge clk) m_awsize <= m_awsize_d;
    logic [1:0] m_awburst_d;
    always_ff @(posedge clk) m_awburst <= m_awburst_d;
    logic  m_wvalid_d;
    always_ff @(posedge clk) m_wvalid <= m_wvalid_d;
    logic  m_wready_q;
    always_ff @(posedge clk) m_wready_q <= m_wready;
    logic [DATA_W-1:0] m_wdata_d;
    always_ff @(posedge clk) m_wdata <= m_wdata_d;
    logic [DATA_W/8-1:0] m_wstrb_d;
    always_ff @(posedge clk) m_wstrb <= m_wstrb_d;
    logic  m_wlast_d;
    always_ff @(posedge clk) m_wlast <= m_wlast_d;
    logic  m_bvalid_q;
    always_ff @(posedge clk) m_bvalid_q <= m_bvalid;
    logic  m_bready_d;
    always_ff @(posedge clk) m_bready <= m_bready_d;
    logic [1:0] m_bresp_q;
    always_ff @(posedge clk) m_bresp_q <= m_bresp;
    logic  idle_d;
    always_ff @(posedge clk) idle <= idle_d;
    axi_write_page_guard #(.ADDR_W(ADDR_W), .DATA_W(DATA_W), .WRITE_OUTSTANDING(WRITE_OUTSTANDING)) u_guard (
        .clk(clk),
        .rst_n(rst_n),
        .s_awvalid(s_awvalid_q),
        .s_awready(s_awready_d),
        .s_awaddr(s_awaddr_q),
        .s_awlen(s_awlen_q),
        .s_awsize(s_awsize_q),
        .s_awburst(s_awburst_q),
        .s_wvalid(s_wvalid_q),
        .s_wready(s_wready_d),
        .s_wdata(s_wdata_q),
        .s_wstrb(s_wstrb_q),
        .s_wlast(s_wlast_q),
        .s_bvalid(s_bvalid_d),
        .s_bready(s_bready_q),
        .s_bresp(s_bresp_d),
        .m_awvalid(m_awvalid_d),
        .m_awready(m_awready_q),
        .m_awaddr(m_awaddr_d),
        .m_awlen(m_awlen_d),
        .m_awsize(m_awsize_d),
        .m_awburst(m_awburst_d),
        .m_wvalid(m_wvalid_d),
        .m_wready(m_wready_q),
        .m_wdata(m_wdata_d),
        .m_wstrb(m_wstrb_d),
        .m_wlast(m_wlast_d),
        .m_bvalid(m_bvalid_q),
        .m_bready(m_bready_d),
        .m_bresp(m_bresp_q),
        .idle(idle_d)
    );
endmodule
