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

// 将 PicoRV32 本地存储握手转换为 AXI 的独立地址、数据和响应握手。
`timescale 1 ns / 1 ps
/* verilator lint_off WIDTH */
/* verilator lint_off PINMISSING */
/* verilator lint_off CASEOVERLAP */
/* verilator lint_off CASEINCOMPLETE */

module picorv32_axi_adapter (
	input clk /* 模块工作时钟。 */, resetn /* 低电平有效复位。 */,

	// AXI4-lite master memory interface

	output        mem_axi_awvalid /* 处理器 AXI 主接口的写地址有效。 */,
	input         mem_axi_awready /* 处理器 AXI 主接口的可接收写地址。 */,
	output [31:0] mem_axi_awaddr /* 处理器 AXI 主接口的写地址。 */,
	output [ 2:0] mem_axi_awprot /* 处理器 AXI 主接口的写访问保护属性。 */,

	output        mem_axi_wvalid /* 处理器 AXI 主接口的写数据有效。 */,
	input         mem_axi_wready /* 处理器 AXI 主接口的可接收写数据。 */,
	output [31:0] mem_axi_wdata /* 处理器 AXI 主接口的写入数据。 */,
	output [ 3:0] mem_axi_wstrb /* 处理器 AXI 主接口的写入字节使能。 */,

	input         mem_axi_bvalid /* 处理器 AXI 主接口的写响应有效。 */,
	output        mem_axi_bready /* 处理器 AXI 主接口的可接收写响应。 */,

	output        mem_axi_arvalid /* 处理器 AXI 主接口的读地址有效。 */,
	input         mem_axi_arready /* 处理器 AXI 主接口的可接收读地址。 */,
	output [31:0] mem_axi_araddr /* 处理器 AXI 主接口的读地址。 */,
	output [ 2:0] mem_axi_arprot /* 处理器 AXI 主接口的读访问保护属性。 */,

	input         mem_axi_rvalid /* 处理器 AXI 主接口的读响应有效。 */,
	output        mem_axi_rready /* 处理器 AXI 主接口的可接收读响应。 */,
	input  [31:0] mem_axi_rdata /* 处理器 AXI 主接口的读取数据。 */,

	// Native PicoRV32 memory interface

	input         mem_valid /* 处理器存储访问请求有效。 */,
	input         mem_instr /* 当前存储请求为取指访问。 */,
	output        mem_ready /* 处理器当前存储请求完成。 */,
	input  [31:0] mem_addr /* 处理器存储访问字节地址。 */,
	input  [31:0] mem_wdata /* 处理器写入数据。 */,
	input  [ 3:0] mem_wstrb /* 处理器写入字节使能，全零表示读取。 */,
	output [31:0] mem_rdata /* 返回处理器的读取数据。 */
);
	reg ack_awvalid;
	reg ack_arvalid;
	reg ack_wvalid;
	reg xfer_done;

	assign mem_axi_awvalid = mem_valid && |mem_wstrb && !ack_awvalid;
	assign mem_axi_awaddr = mem_addr;
	assign mem_axi_awprot = 0;

	assign mem_axi_arvalid = mem_valid && !mem_wstrb && !ack_arvalid;
	assign mem_axi_araddr = mem_addr;
	assign mem_axi_arprot = mem_instr ? 3'b100 : 3'b000;

	assign mem_axi_wvalid = mem_valid && |mem_wstrb && !ack_wvalid;
	assign mem_axi_wdata = mem_wdata;
	assign mem_axi_wstrb = mem_wstrb;

	assign mem_ready = mem_axi_bvalid || mem_axi_rvalid;
	assign mem_axi_bready = mem_valid && |mem_wstrb;
	assign mem_axi_rready = mem_valid && !mem_wstrb;
	assign mem_rdata = mem_axi_rdata;

	always @(posedge clk) begin
		if (!resetn) begin
			ack_awvalid <= 0;
		end else begin
			xfer_done <= mem_valid && mem_ready;
			if (mem_axi_awready && mem_axi_awvalid)
				ack_awvalid <= 1;
			if (mem_axi_arready && mem_axi_arvalid)
				ack_arvalid <= 1;
			if (mem_axi_wready && mem_axi_wvalid)
				ack_wvalid <= 1;
			if (xfer_done || !mem_valid) begin
				ack_awvalid <= 0;
				ack_arvalid <= 0;
				ack_wvalid <= 0;
			end
		end
	end
endmodule
