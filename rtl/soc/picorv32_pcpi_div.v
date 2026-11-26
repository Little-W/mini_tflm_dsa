/*
 *  PicoRV32 -- A Small RISC-V (RV32I) Processor Core
 *
 *  Copyright (C) 2015  Claire Xenia Wolf <claire@yosyshq.com>
 *
 *  Permission to use, copy, modify, and/or distribute this software for any
 *  purpose with or without fee is hereby granted, provided that the above
 *  copyright notice and this permission notice appear in all copies.
 *
 *  THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
 *  WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
 *  MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
 *  ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
 *  WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
 *  ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
 *  OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
 *
 */

// 通过 PCPI 接口逐步计算有符号或无符号除法及余数。
`timescale 1 ns / 1 ps
/* verilator lint_off WIDTH */
/* verilator lint_off PINMISSING */
/* verilator lint_off CASEOVERLAP */
/* verilator lint_off CASEINCOMPLETE */

module picorv32_pcpi_div (
	input clk /* 模块工作时钟。 */, resetn /* 低电平有效复位。 */,

	input             pcpi_valid /* 协处理器指令请求有效。 */,
	input      [31:0] pcpi_insn /* 待执行的协处理器指令编码。 */,
	input      [31:0] pcpi_rs1 /* 协处理器第一源操作数。 */,
	input      [31:0] pcpi_rs2 /* 协处理器第二源操作数。 */,
	output reg        pcpi_wr /* 协处理器结果需写回目标寄存器。 */,
	output reg [31:0] pcpi_rd /* 协处理器返回的目标寄存器数据。 */,
	output reg        pcpi_wait /* 协处理器正在处理请求。 */,
	output reg        pcpi_ready /* 协处理器指令已完成。 */
);
	reg instr_div, instr_divu, instr_rem, instr_remu;
	wire instr_any_div_rem = |{instr_div, instr_divu, instr_rem, instr_remu};

	reg pcpi_wait_q;
	wire start = pcpi_wait && !pcpi_wait_q;

	always @(posedge clk) begin
		instr_div <= 0;
		instr_divu <= 0;
		instr_rem <= 0;
		instr_remu <= 0;

		if (resetn && pcpi_valid && !pcpi_ready && pcpi_insn[6:0] == 7'b0110011 && pcpi_insn[31:25] == 7'b0000001) begin
			case (pcpi_insn[14:12])
				3'b100: instr_div <= 1;
				3'b101: instr_divu <= 1;
				3'b110: instr_rem <= 1;
				3'b111: instr_remu <= 1;
			endcase
		end

		pcpi_wait <= instr_any_div_rem && resetn;
		pcpi_wait_q <= pcpi_wait && resetn;
	end

	reg [31:0] dividend;
	reg [62:0] divisor;
	reg [31:0] quotient;
	reg [31:0] quotient_msk;
	reg running;
	reg outsign;

    // 输入符号变换、余数递减和结果符号变换分别使用完整定宽算术。
    wire [31:0] negative_rs1 = 32'd0 - pcpi_rs1;
    wire [31:0] negative_rs2 = 32'd0 - pcpi_rs2;
    wire [32:0] remainder_difference =
        {1'b0, dividend} - {1'b0, divisor[31:0]};
    wire remainder_less;
    wire unused_remainder_equal;
    wire subtract_permitted = !(|divisor[62:32]) && !remainder_less;
    // 商位资格独立比较，余数减法只承担数据计算。
    unsigned_compare #(.p_width(32)) u_remainder_compare (
        .i_a(dividend), .i_b(divisor[31:0]),
        .o_less(remainder_less), .o_equal(unused_remainder_equal)
    );
    wire [31:0] unsigned_result = (instr_div || instr_divu) ? quotient : dividend;
    logic [31:0] negative_result;
    // 符号变换并行检查各位以下是否存在一，保持完整的三十二位模运算。
    pico_result_negation u_result_negation (
        .i_value(unsigned_result), .o_value(negative_result)
    );

	always @(posedge clk) begin
		pcpi_ready <= 0;
		pcpi_wr <= 0;
		pcpi_rd <= 'bx;

		if (!resetn) begin
			running <= 0;
		end else
		if (start) begin
			running <= 1;
			dividend <= (instr_div || instr_rem) && pcpi_rs1[31] ? negative_rs1 : pcpi_rs1;
			divisor <= ((instr_div || instr_rem) && pcpi_rs2[31] ? negative_rs2 : pcpi_rs2) << 31;
			outsign <= (instr_div && (pcpi_rs1[31] != pcpi_rs2[31]) && |pcpi_rs2) || (instr_rem && pcpi_rs1[31]);
			quotient <= 0;
			quotient_msk <= 1 << 31;
		end else
		if (!quotient_msk && running) begin
			running <= 0;
			pcpi_ready <= 1;
			pcpi_wr <= 1;
`ifdef RISCV_FORMAL_ALTOPS
			case (1)
				instr_div:  pcpi_rd <= (pcpi_rs1 - pcpi_rs2) ^ 32'h7f8529ec;
				instr_divu: pcpi_rd <= (pcpi_rs1 - pcpi_rs2) ^ 32'h10e8fd70;
				instr_rem:  pcpi_rd <= (pcpi_rs1 - pcpi_rs2) ^ 32'h8da68fa5;
				instr_remu: pcpi_rd <= (pcpi_rs1 - pcpi_rs2) ^ 32'h3138d0e1;
			endcase
`else
`ifdef SYNTHESIS
            pcpi_rd <= outsign ? negative_result : unsigned_result;
`else
            // 四态仿真按指令判断保留分支选择及已知数据位。
            if (instr_div || instr_divu)
                pcpi_rd <= outsign ? -quotient : quotient;
            else
                pcpi_rd <= outsign ? -dividend : dividend;
`endif
`endif
		end else begin
			if (subtract_permitted) begin
				dividend <= remainder_difference[31:0];
				quotient <= quotient | quotient_msk;
			end
			divisor <= divisor >> 1;
`ifdef RISCV_FORMAL_ALTOPS
			quotient_msk <= quotient_msk >> 5;
`else
			quotient_msk <= quotient_msk >> 1;
`endif
		end
	end
endmodule
