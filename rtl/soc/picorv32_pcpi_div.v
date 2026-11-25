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

// PicoRV32 处理器的独立功能模块。
`timescale 1 ns / 1 ps
/* verilator lint_off WIDTH */
/* verilator lint_off PINMISSING */
/* verilator lint_off CASEOVERLAP */
/* verilator lint_off CASEINCOMPLETE */

module picorv32_pcpi_div (
	input clk, resetn,

	input             pcpi_valid,
	input      [31:0] pcpi_insn,
	input      [31:0] pcpi_rs1,
	input      [31:0] pcpi_rs2,
	output reg        pcpi_wr,
	output reg [31:0] pcpi_rd,
	output reg        pcpi_wait,
	output reg        pcpi_ready
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

// 二进制补码由当前位和低位非零条件形成，四位分组控制归并深度。
(* keep_hierarchy = "yes" *)
module pico_result_negation (
    input wire logic [31:0] i_value,
    output logic [31:0] o_value
);
    (* keep = 1 *) logic [6:0] group_nonzero;
    logic [31:0] negated_value;
    for (genvar group_index = 0; group_index < 7; group_index++) begin : g_group
        assign group_nonzero[group_index] = |i_value[group_index*4+:4];
    end
    assign negated_value[0] = i_value[0];
    for (genvar bit_index = 1; bit_index < 32; bit_index++) begin : g_bit
        localparam int p_groups = bit_index/4;
        localparam int p_local = bit_index%4;
        logic lower_nonzero;
        if (p_groups == 0) begin : g_first
            assign lower_nonzero = |i_value[bit_index-1:0];
        end else if (p_local == 0) begin : g_boundary
            assign lower_nonzero = |group_nonzero[p_groups-1:0];
        end else begin : g_partial
            assign lower_nonzero = (|group_nonzero[p_groups-1:0]) ||
                (|i_value[p_groups*4+:p_local]);
        end
        assign negated_value[bit_index] = i_value[bit_index] ^ lower_nonzero;
    end
    always_comb begin
        case (^i_value)
            1'b0, 1'b1: o_value = negated_value;
            default: o_value = 32'd0 - i_value;
        endcase
    end
endmodule
