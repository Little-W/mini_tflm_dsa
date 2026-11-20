`default_nettype none

// SRAM 宏接口用于完整 NPU 的连接与层次展开，存储行为由独立功能测试验证。
(* blackbox *)
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
endmodule

(* blackbox *)
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
endmodule

`default_nettype wire
