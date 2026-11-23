module smic40_sram_1r1w #(
    parameter integer DATA_WIDTH = 32,
    parameter integer DEPTH = 128,
    parameter integer ADDR_WIDTH = 7,
    parameter integer MACRO_DEPTH = (DEPTH <= 128) ? 128 : 1024,
    parameter integer BANKS = (DEPTH + MACRO_DEPTH - 1) / MACRO_DEPTH,
    parameter integer BANK_BITS = (BANKS <= 1) ? 1 : $clog2(BANKS),
    parameter integer LANES = (DATA_WIDTH + 15) / 16
) (
    input wire clk,
    input wire write_enable,
    input wire [ADDR_WIDTH-1:0] write_address,
    input wire [DATA_WIDTH-1:0] write_data,
    input wire [DATA_WIDTH-1:0] write_mask,
    input wire read_enable,
    input wire [ADDR_WIDTH-1:0] read_address,
    output wire [DATA_WIDTH-1:0] read_data
);
    wire [LANES*16-1:0] write_padded = {{(LANES*16-DATA_WIDTH){1'b0}}, write_data};
    wire [LANES*16-1:0] mask_padded = {{(LANES*16-DATA_WIDTH){1'b0}}, write_mask};
    wire [LANES*16-1:0] bank_data [0:BANKS-1];
    reg [BANK_BITS-1:0] read_bank;
    localparam integer LOW_BITS = (MACRO_DEPTH == 128) ? 7 : 10;
    always @(posedge clk)
        if (read_enable) read_bank <= BANK_BITS'(read_address >> LOW_BITS);
    assign read_data = DATA_WIDTH'(bank_data[read_bank]);

    genvar b, lane;
    generate for (b=0; b<BANKS; b=b+1) begin: g_bank
        wire rd = read_enable && ((read_address >> LOW_BITS) == b);
        wire wr = write_enable && ((write_address >> LOW_BITS) == b);
        for (lane=0; lane<LANES; lane=lane+1) begin: g_lane
            if (MACRO_DEPTH == 128) begin: g_128
                wire [6:0] ra = 7'(read_address);
                wire [6:0] wa = 7'(write_address);
                RAMTP128X16 u_sram (
                    .QA(bank_data[b][lane*16 +: 16]), .CLKA(clk), .CENA(~rd), .AA(ra),
                    .CLKB(clk), .CENB(~wr), .WENB(~mask_padded[lane*16 +: 16]), .AB(wa),
                    .DB(write_padded[lane*16 +: 16]), .EMAA(3'b010), .EMAB(3'b010),
                    .RET1N(1'b1), .COLLDISN(1'b1));
            end else begin: g_1024
                wire [9:0] ra = 10'(read_address);
                wire [9:0] wa = 10'(write_address);
                RAMTP1024X16 u_sram (
                    .QA(bank_data[b][lane*16 +: 16]), .CLKA(clk), .CENA(~rd), .AA(ra),
                    .CLKB(clk), .CENB(~wr), .WENB(~mask_padded[lane*16 +: 16]), .AB(wa),
                    .DB(write_padded[lane*16 +: 16]), .EMAA(3'b010), .EMAB(3'b010),
                    .RET1N(1'b1), .COLLDISN(1'b1));
            end
        end
    end endgenerate
endmodule
