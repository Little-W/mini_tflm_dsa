// SPDX-License-Identifier: Apache-2.0
`default_nettype none
// 以六十四位双端口存储字承载两个三十二位访问接口，支持逐字节写入和两拍读取。
module axi_inferred_shared_ram_bank #(
    parameter RAM_STYLE = "ultra",
    parameter integer ADDR_WIDTH = 14,
    parameter integer DEPTH_WORDS = 16384
) (
    input wire clk /* 模块工作时钟。 */,
    input wire rsta /* A 端口读输出的高电平有效复位。 */,
    input wire ena /* A 端口访问使能。 */,
    input wire [3:0] wea /* A 端口写入字节使能。 */,
    input wire [ADDR_WIDTH-1:0] addra /* A 端口六十四位存储字地址。 */,
    input wire addra_hi /* A 端口选择六十四位存储字的高半字。 */,
    input wire [31:0] dina /* A 端口写入数据。 */,
    output wire [31:0] douta /* A 端口读取数据。 */,
    input wire rstb /* B 端口读输出的高电平有效复位。 */,
    input wire enb /* B 端口访问使能。 */,
    input wire [3:0] web /* B 端口写入字节使能。 */,
    input wire [ADDR_WIDTH-1:0] addrb /* B 端口六十四位存储字地址。 */,
    input wire addrb_hi /* B 端口选择六十四位存储字的高半字。 */,
    input wire [31:0] dinb /* B 端口写入数据。 */,
    output wire [31:0] doutb /* B 端口读取数据。 */
);
    wire [63:0] douta_wide, doutb_wide;
    reg addra_hi_q, addrb_hi_q;
    wire [7:0] wea_wide = addra_hi ? {wea, 4'b0000} : {4'b0000, wea};
    wire [63:0] dina_wide = addra_hi ? {dina, 32'b0} : {32'b0, dina};
    wire [7:0] web_wide = addrb_hi ? {web, 4'b0000} : {4'b0000, web};
    wire [63:0] dinb_wide = addrb_hi ? {dinb, 32'b0} : {32'b0, dinb};
    assign douta = addra_hi_q ? douta_wide[63:32] : douta_wide[31:0];
    assign doutb = addrb_hi_q ? doutb_wide[63:32] : doutb_wide[31:0];

    // XPM's TDP template makes the 64-bit URAM/BRAM geometry explicit while
    // retaining the handwritten 32-bit AXI BRAM interface and byte writes.
    xpm_memory_tdpram #(
        .ADDR_WIDTH_A(ADDR_WIDTH), .ADDR_WIDTH_B(ADDR_WIDTH),
        .AUTO_SLEEP_TIME(0),
        .BYTE_WRITE_WIDTH_A(8), .BYTE_WRITE_WIDTH_B(8),
        .CLOCKING_MODE("common_clock"),
        .ECC_MODE("no_ecc"),
        .MEMORY_INIT_FILE("none"), .MEMORY_INIT_PARAM("0"),
        .MEMORY_OPTIMIZATION("true"),
        .MEMORY_PRIMITIVE(RAM_STYLE), .MEMORY_SIZE(DEPTH_WORDS*64),
        .MESSAGE_CONTROL(0), .READ_DATA_WIDTH_A(64), .READ_DATA_WIDTH_B(64),
        .READ_LATENCY_A(2), .READ_LATENCY_B(2),
        .READ_RESET_VALUE_A("0"), .READ_RESET_VALUE_B("0"),
        .RST_MODE_A("SYNC"), .RST_MODE_B("SYNC"),
        .SIM_ASSERT_CHK(0), .USE_EMBEDDED_CONSTRAINT(0), .USE_MEM_INIT(0),
        .WAKEUP_TIME("disable_sleep"), .WRITE_DATA_WIDTH_A(64),
        .WRITE_DATA_WIDTH_B(64), .WRITE_MODE_A("no_change"),
        .WRITE_MODE_B("no_change"), .WRITE_PROTECT(1)
    ) mem (
        .sleep(1'b0),
        .clka(clk), .rsta(rsta), .ena(ena), .regcea(1'b1),
        .wea(wea_wide), .addra(addra), .dina(dina_wide),
        .injectsbiterra(1'b0), .injectdbiterra(1'b0),
        .douta(douta_wide), .sbiterra(), .dbiterra(),
        .clkb(clk), .rstb(rstb), .enb(enb), .regceb(1'b1),
        .web(web_wide), .addrb(addrb), .dinb(dinb_wide),
        .injectsbiterrb(1'b0), .injectdbiterrb(1'b0),
        .doutb(doutb_wide), .sbiterrb(), .dbiterrb()
    );

    always @(posedge clk) begin
        if (rsta) addra_hi_q <= 1'b0;
        else if (ena && (wea == 4'b0)) addra_hi_q <= addra_hi;
    end

    always @(posedge clk) begin
        if (rstb) addrb_hi_q <= 1'b0;
        else if (enb && (web == 4'b0)) addrb_hi_q <= addrb_hi;
    end
endmodule

`default_nettype wire
