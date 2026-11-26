/* 将 AXI-Lite 访问转换为 UART 数据与分频寄存器操作，连接串行收发端口。 */ module soc_axil_simpleuart #(
    parameter int unsigned AXIL_ADDR_WIDTH = 32,
    parameter int unsigned AXIL_DATA_WIDTH = 32
) (
    input  wire                         clk /* 模块工作时钟。 */,
    input  wire                         rst_n /* 低电平有效复位。 */,

    input  wire [AXIL_ADDR_WIDTH-1:0]   s_axil_awaddr /* AXI-Lite 从接口的写地址。 */,
    input  wire [2:0]                   s_axil_awprot /* AXI-Lite 从接口的写访问保护属性。 */,
    input  wire                         s_axil_awvalid /* AXI-Lite 从接口的写地址有效。 */,
    output wire                         s_axil_awready /* AXI-Lite 从接口的可接收写地址。 */,
    input  wire [AXIL_DATA_WIDTH-1:0]   s_axil_wdata /* AXI-Lite 从接口的写入数据。 */,
    input  wire [AXIL_DATA_WIDTH/8-1:0] s_axil_wstrb /* AXI-Lite 从接口的写入字节使能。 */,
    input  wire                         s_axil_wvalid /* AXI-Lite 从接口的写数据有效。 */,
    output wire                         s_axil_wready /* AXI-Lite 从接口的可接收写数据。 */,
    output logic [1:0]                  s_axil_bresp /* AXI-Lite 从接口的写响应状态。 */,
    output logic                        s_axil_bvalid /* AXI-Lite 从接口的写响应有效。 */,
    input  wire                         s_axil_bready /* AXI-Lite 从接口的可接收写响应。 */,
    input  wire [AXIL_ADDR_WIDTH-1:0]   s_axil_araddr /* AXI-Lite 从接口的读地址。 */,
    input  wire [2:0]                   s_axil_arprot /* AXI-Lite 从接口的读访问保护属性。 */,
    input  wire                         s_axil_arvalid /* AXI-Lite 从接口的读地址有效。 */,
    output wire                         s_axil_arready /* AXI-Lite 从接口的可接收读地址。 */,
    output logic [AXIL_DATA_WIDTH-1:0]  s_axil_rdata /* AXI-Lite 从接口的读取数据。 */,
    output logic [1:0]                  s_axil_rresp /* AXI-Lite 从接口的读响应状态。 */,
    output logic                        s_axil_rvalid /* AXI-Lite 从接口的读响应有效。 */,
    input  wire                         s_axil_rready /* AXI-Lite 从接口的可接收读响应。 */,

    output wire                         uart_tx /* UART 串行发送数据。 */,
    input  wire                         uart_rx /* UART 串行接收数据。 */,
    output wire [31:0]                  cfg_divider /* UART 波特率时钟分频配置。 */
);

    localparam logic [3:0] UART_CLKDIV_ADDR = 4'h4;
    localparam logic [3:0] UART_DATA_ADDR   = 4'h8;

    logic [AXIL_ADDR_WIDTH-1:0] awaddr_q;
    logic [AXIL_DATA_WIDTH-1:0] wdata_q;
    logic [AXIL_DATA_WIDTH/8-1:0] wstrb_q;
    logic aw_seen_q;
    logic w_seen_q;

    logic [31:0] uart_div_rdata;
    logic [31:0] uart_data_rdata;
    logic uart_data_wait;
    logic [3:0] uart_div_we;
    logic uart_data_we;
    logic uart_data_re_q;

    wire aw_fire = s_axil_awvalid && s_axil_awready;
    wire w_fire  = s_axil_wvalid  && s_axil_wready;
    wire ar_fire = s_axil_arvalid && s_axil_arready;
    wire wr_ready = (aw_seen_q || aw_fire) && (w_seen_q || w_fire) && !s_axil_bvalid;
    wire [AXIL_ADDR_WIDTH-1:0] wr_addr = aw_seen_q ? awaddr_q : s_axil_awaddr;
    wire [AXIL_DATA_WIDTH-1:0] wr_data = w_seen_q ? wdata_q : s_axil_wdata;
    wire [AXIL_DATA_WIDTH/8-1:0] wr_strb = w_seen_q ? wstrb_q : s_axil_wstrb;
    wire write_to_div  = wr_addr[3:0] == UART_CLKDIV_ADDR;
    wire write_to_data = wr_addr[3:0] == UART_DATA_ADDR;
    wire wr_accept = wr_ready && !(write_to_data && uart_data_wait);
    wire read_from_div = s_axil_araddr[3:0] == UART_CLKDIV_ADDR;
    wire read_from_data = s_axil_araddr[3:0] == UART_DATA_ADDR;

    assign s_axil_awready = !aw_seen_q && !s_axil_bvalid;
    assign s_axil_wready  = !w_seen_q && !s_axil_bvalid;
    assign s_axil_arready = !s_axil_rvalid;
    assign cfg_divider = uart_div_rdata;
    assign uart_div_we = (wr_accept && write_to_div) ? wr_strb[3:0] : 4'b0000;
    assign uart_data_we = wr_ready && write_to_data && (|wr_strb);

    simpleuart u_simpleuart (
        .clk          (clk),
        .resetn       (rst_n),
        .ser_tx       (uart_tx),
        .ser_rx       (uart_rx),
        .reg_div_we   (uart_div_we),
        .reg_div_di   (wr_data[31:0]),
        .reg_div_do   (uart_div_rdata),
        .reg_dat_we   (uart_data_we),
        .reg_dat_re   (uart_data_re_q),
        .reg_dat_di   (wr_data[31:0]),
        .reg_dat_do   (uart_data_rdata),
        .reg_dat_wait (uart_data_wait)
    );

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            awaddr_q       <= '0;
            wdata_q        <= '0;
            wstrb_q        <= '0;
            aw_seen_q      <= 1'b0;
            w_seen_q       <= 1'b0;
            s_axil_bresp   <= 2'b00;
            s_axil_bvalid  <= 1'b0;
            s_axil_rdata   <= '0;
            s_axil_rresp   <= 2'b00;
            s_axil_rvalid  <= 1'b0;
            uart_data_re_q <= 1'b0;
        end else begin
            uart_data_re_q <= 1'b0;

            if (aw_fire) begin
                awaddr_q  <= s_axil_awaddr;
                aw_seen_q <= 1'b1;
            end
            if (w_fire) begin
                wdata_q  <= s_axil_wdata;
                wstrb_q  <= s_axil_wstrb;
                w_seen_q <= 1'b1;
            end

            if (wr_accept) begin
                aw_seen_q     <= 1'b0;
                w_seen_q      <= 1'b0;
                s_axil_bvalid <= 1'b1;
                s_axil_bresp  <= 2'b00;
            end

            if (s_axil_bvalid && s_axil_bready) begin
                s_axil_bvalid <= 1'b0;
            end

            if (ar_fire) begin
                uart_data_re_q <= read_from_data;
                s_axil_rdata   <= read_from_div  ? uart_div_rdata :
                                  read_from_data ? uart_data_rdata : '0;
                s_axil_rresp   <= 2'b00;
                s_axil_rvalid  <= 1'b1;
            end else if (s_axil_rvalid && s_axil_rready) begin
                s_axil_rvalid <= 1'b0;
            end
        end
    end

    wire _unused = |s_axil_awprot | |s_axil_arprot;

endmodule
