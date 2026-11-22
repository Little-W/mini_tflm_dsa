`default_nettype none

// 同步 SRAM 功能模型，完整保存数据并检查物理端口同址冲突。
module regfile_sram_model #(
    parameter int p_address_width = 7
) (
    output logic [15:0] QA,
    input wire CLKA, CENA,
    input wire [p_address_width-1:0] AA,
    input wire CLKB, CENB,
    input wire [15:0] WENB,
    input wire [p_address_width-1:0] AB,
    input wire [15:0] DB
);
    logic [15:0] memory [0:(1 << p_address_width)-1];
    always @(posedge CLKA) begin
        if (!CENA) begin
            assert (!(!CENB && AA == AB && |(~WENB)))
                else $fatal(1, "SRAM read/write collision at %0d", AA);
            QA <= memory[AA];
        end
    end
    always @(posedge CLKB) begin
        if (!CENB) begin
            for (int bit_index = 0; bit_index < 16; bit_index++) begin
                if (!WENB[bit_index]) memory[AB][bit_index] <= DB[bit_index];
            end
        end
    end
endmodule

module RAMTP128X16 (
    output wire [15:0] QA,
    input wire CLKA, CENA,
    input wire [6:0] AA,
    input wire CLKB, CENB,
    input wire [15:0] WENB,
    input wire [6:0] AB,
    input wire [15:0] DB,
    input wire [2:0] EMAA, EMAB,
    input wire RET1N, COLLDISN
);
    regfile_sram_model #(.p_address_width(7)) u_model (
        .QA(QA), .CLKA(CLKA), .CENA(CENA), .AA(AA),
        .CLKB(CLKB), .CENB(CENB), .WENB(WENB), .AB(AB), .DB(DB)
    );
endmodule

module RAMTP1024X16 (
    output wire [15:0] QA,
    input wire CLKA, CENA,
    input wire [9:0] AA,
    input wire CLKB, CENB,
    input wire [15:0] WENB,
    input wire [9:0] AB,
    input wire [15:0] DB,
    input wire [2:0] EMAA, EMAB,
    input wire RET1N, COLLDISN
);
    regfile_sram_model #(.p_address_width(10)) u_model (
        .QA(QA), .CLKA(CLKA), .CENA(CENA), .AA(AA),
        .CLKB(CLKB), .CENB(CENB), .WENB(WENB), .AB(AB), .DB(DB)
    );
endmodule

`default_nettype wire
