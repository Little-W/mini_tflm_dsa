`default_nettype none

// 功能模型保存全部宏存储位；同地址并发读写直接终止仿真。
// 模型只描述同步读取、输出保持及逐位写掩码。
module RAMTP128X16 (
    output logic [15:0] QA,
    input wire CLKA, CENA,
    input wire [6:0] AA,
    input wire CLKB, CENB,
    input wire [15:0] WENB,
    input wire [6:0] AB,
    input wire [15:0] DB,
    input wire [2:0] EMAA, EMAB,
    input wire RET1N, COLLDISN
);
    logic [15:0] memory [0:127];

    always @(posedge CLKA) begin
        if (!CENA) begin
            if (!CENB && AA == AB && |(~WENB))
                $fatal(1, "SRAM simultaneous read/write at address %0d", AA);
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

`default_nettype wire
