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

// 连接 PicoRV32 处理器与 AXI 存储接口，并提供协处理器、中断和执行记录接口。
`timescale 1 ns / 1 ps
/* verilator lint_off WIDTH */
/* verilator lint_off PINMISSING */
/* verilator lint_off CASEOVERLAP */
/* verilator lint_off CASEINCOMPLETE */

module picorv32_axi #(
	parameter [ 0:0] ENABLE_COUNTERS = 1,
	parameter [ 0:0] ENABLE_COUNTERS64 = 1,
	parameter [ 0:0] ENABLE_REGS_16_31 = 1,
	parameter [ 0:0] ENABLE_REGS_DUALPORT = 1,
	parameter [ 0:0] TWO_STAGE_SHIFT = 1,
	parameter [ 0:0] BARREL_SHIFTER = 0,
	parameter [ 0:0] TWO_CYCLE_COMPARE = 0,
	parameter [ 0:0] TWO_CYCLE_ALU = 0,
	parameter [ 0:0] COMPRESSED_ISA = 0,
	parameter [ 0:0] CATCH_MISALIGN = 1,
	parameter [ 0:0] CATCH_ILLINSN = 1,
	parameter [ 0:0] ENABLE_PCPI = 0,
	parameter [ 0:0] ENABLE_MUL = 0,
	parameter [ 0:0] ENABLE_FAST_MUL = 0,
	parameter [ 0:0] ENABLE_DIV = 0,
	parameter [ 0:0] ENABLE_IRQ = 0,
	parameter [ 0:0] ENABLE_IRQ_QREGS = 1,
	parameter [ 0:0] ENABLE_IRQ_TIMER = 1,
	parameter [ 0:0] ENABLE_TRACE = 0,
	parameter [ 0:0] REGS_INIT_ZERO = 0,
	parameter [31:0] MASKED_IRQ = 32'h 0000_0000,
	parameter [31:0] LATCHED_IRQ = 32'h ffff_ffff,
	parameter [31:0] PROGADDR_RESET = 32'h 0000_0000,
	parameter [31:0] PROGADDR_IRQ = 32'h 0000_0010,
	parameter [31:0] STACKADDR = 32'h ffff_ffff
) (
	input clk /* 模块工作时钟。 */, resetn /* 低电平有效复位。 */,
	output trap /* 处理器异常停止指示。 */,

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

	// Pico Co-Processor Interface (PCPI)
	output        pcpi_valid /* 协处理器指令请求有效。 */,
	output [31:0] pcpi_insn /* 待执行的协处理器指令编码。 */,
	output [31:0] pcpi_rs1 /* 协处理器第一源操作数。 */,
	output [31:0] pcpi_rs2 /* 协处理器第二源操作数。 */,
	input         pcpi_wr /* 协处理器结果需写回目标寄存器。 */,
	input  [31:0] pcpi_rd /* 协处理器返回的目标寄存器数据。 */,
	input         pcpi_wait /* 协处理器正在处理请求。 */,
	input         pcpi_ready /* 协处理器指令已完成。 */,

	// IRQ interface
	input  [31:0] irq /* 处理器中断请求向量。 */,
	output [31:0] eoi /* 已响应的中断请求位。 */,

`ifdef RISCV_FORMAL
	output        rvfi_valid /* RVFI 当前指令提交记录有效。 */,
	output [63:0] rvfi_order /* RVFI 已提交指令的顺序编号。 */,
	output [31:0] rvfi_insn /* RVFI 已提交指令编码。 */,
	output        rvfi_trap /* RVFI 当前指令触发异常。 */,
	output        rvfi_halt /* RVFI 当前指令使处理器停止执行。 */,
	output        rvfi_intr /* RVFI 当前指令进入中断或异常处理。 */,
	output [ 4:0] rvfi_rs1_addr /* RVFI 第一源寄存器编号。 */,
	output [ 4:0] rvfi_rs2_addr /* RVFI 第二源寄存器编号。 */,
	output [31:0] rvfi_rs1_rdata /* RVFI 第一源寄存器读取值。 */,
	output [31:0] rvfi_rs2_rdata /* RVFI 第二源寄存器读取值。 */,
	output [ 4:0] rvfi_rd_addr /* RVFI 目标寄存器编号。 */,
	output [31:0] rvfi_rd_wdata /* RVFI 目标寄存器写入值。 */,
	output [31:0] rvfi_pc_rdata /* RVFI 执行指令前的程序计数器。 */,
	output [31:0] rvfi_pc_wdata /* RVFI 执行指令后的程序计数器。 */,
	output [31:0] rvfi_mem_addr /* RVFI 指令访问的存储字节地址。 */,
	output [ 3:0] rvfi_mem_rmask /* RVFI 存储读取的字节掩码。 */,
	output [ 3:0] rvfi_mem_wmask /* RVFI 存储写入的字节掩码。 */,
	output [31:0] rvfi_mem_rdata /* RVFI 存储读取值。 */,
	output [31:0] rvfi_mem_wdata /* RVFI 存储写入值。 */,
`endif

	// Trace Interface
	output        trace_valid /* 指令执行记录有效。 */,
	output [35:0] trace_data /* 指令执行记录的类型和数据。 */
);
	wire        mem_valid;
	wire [31:0] mem_addr;
	wire [31:0] mem_wdata;
	wire [ 3:0] mem_wstrb;
	wire        mem_instr;
	wire        mem_ready;
	wire [31:0] mem_rdata;

	picorv32_axi_adapter axi_adapter (
		.clk            (clk            ),
		.resetn         (resetn         ),
		.mem_axi_awvalid(mem_axi_awvalid),
		.mem_axi_awready(mem_axi_awready),
		.mem_axi_awaddr (mem_axi_awaddr ),
		.mem_axi_awprot (mem_axi_awprot ),
		.mem_axi_wvalid (mem_axi_wvalid ),
		.mem_axi_wready (mem_axi_wready ),
		.mem_axi_wdata  (mem_axi_wdata  ),
		.mem_axi_wstrb  (mem_axi_wstrb  ),
		.mem_axi_bvalid (mem_axi_bvalid ),
		.mem_axi_bready (mem_axi_bready ),
		.mem_axi_arvalid(mem_axi_arvalid),
		.mem_axi_arready(mem_axi_arready),
		.mem_axi_araddr (mem_axi_araddr ),
		.mem_axi_arprot (mem_axi_arprot ),
		.mem_axi_rvalid (mem_axi_rvalid ),
		.mem_axi_rready (mem_axi_rready ),
		.mem_axi_rdata  (mem_axi_rdata  ),
		.mem_valid      (mem_valid      ),
		.mem_instr      (mem_instr      ),
		.mem_ready      (mem_ready      ),
		.mem_addr       (mem_addr       ),
		.mem_wdata      (mem_wdata      ),
		.mem_wstrb      (mem_wstrb      ),
		.mem_rdata      (mem_rdata      )
	);

	picorv32 #(
		.ENABLE_COUNTERS     (ENABLE_COUNTERS     ),
		.ENABLE_COUNTERS64   (ENABLE_COUNTERS64   ),
		.ENABLE_REGS_16_31   (ENABLE_REGS_16_31   ),
		.ENABLE_REGS_DUALPORT(ENABLE_REGS_DUALPORT),
		.TWO_STAGE_SHIFT     (TWO_STAGE_SHIFT     ),
		.BARREL_SHIFTER      (BARREL_SHIFTER      ),
		.TWO_CYCLE_COMPARE   (TWO_CYCLE_COMPARE   ),
		.TWO_CYCLE_ALU       (TWO_CYCLE_ALU       ),
		.COMPRESSED_ISA      (COMPRESSED_ISA      ),
		.CATCH_MISALIGN      (CATCH_MISALIGN      ),
		.CATCH_ILLINSN       (CATCH_ILLINSN       ),
		.ENABLE_PCPI         (ENABLE_PCPI         ),
		.ENABLE_MUL          (ENABLE_MUL          ),
		.ENABLE_FAST_MUL     (ENABLE_FAST_MUL     ),
		.ENABLE_DIV          (ENABLE_DIV          ),
		.ENABLE_IRQ          (ENABLE_IRQ          ),
		.ENABLE_IRQ_QREGS    (ENABLE_IRQ_QREGS    ),
		.ENABLE_IRQ_TIMER    (ENABLE_IRQ_TIMER    ),
		.ENABLE_TRACE        (ENABLE_TRACE        ),
		.REGS_INIT_ZERO      (REGS_INIT_ZERO      ),
		.MASKED_IRQ          (MASKED_IRQ          ),
		.LATCHED_IRQ         (LATCHED_IRQ         ),
		.PROGADDR_RESET      (PROGADDR_RESET      ),
		.PROGADDR_IRQ        (PROGADDR_IRQ        ),
		.STACKADDR           (STACKADDR           )
	) picorv32_core (
		.clk      (clk   ),
		.resetn   (resetn),
		.trap     (trap  ),

		.mem_valid(mem_valid),
		.mem_addr (mem_addr ),
		.mem_wdata(mem_wdata),
		.mem_wstrb(mem_wstrb),
		.mem_instr(mem_instr),
		.mem_ready(mem_ready),
		.mem_rdata(mem_rdata),

		.pcpi_valid(pcpi_valid),
		.pcpi_insn (pcpi_insn ),
		.pcpi_rs1  (pcpi_rs1  ),
		.pcpi_rs2  (pcpi_rs2  ),
		.pcpi_wr   (pcpi_wr   ),
		.pcpi_rd   (pcpi_rd   ),
		.pcpi_wait (pcpi_wait ),
		.pcpi_ready(pcpi_ready),

		.irq(irq),
		.eoi(eoi),

`ifdef RISCV_FORMAL
		.rvfi_valid    (rvfi_valid    ),
		.rvfi_order    (rvfi_order    ),
		.rvfi_insn     (rvfi_insn     ),
		.rvfi_trap     (rvfi_trap     ),
		.rvfi_halt     (rvfi_halt     ),
		.rvfi_intr     (rvfi_intr     ),
		.rvfi_rs1_addr (rvfi_rs1_addr ),
		.rvfi_rs2_addr (rvfi_rs2_addr ),
		.rvfi_rs1_rdata(rvfi_rs1_rdata),
		.rvfi_rs2_rdata(rvfi_rs2_rdata),
		.rvfi_rd_addr  (rvfi_rd_addr  ),
		.rvfi_rd_wdata (rvfi_rd_wdata ),
		.rvfi_pc_rdata (rvfi_pc_rdata ),
		.rvfi_pc_wdata (rvfi_pc_wdata ),
		.rvfi_mem_addr (rvfi_mem_addr ),
		.rvfi_mem_rmask(rvfi_mem_rmask),
		.rvfi_mem_wmask(rvfi_mem_wmask),
		.rvfi_mem_rdata(rvfi_mem_rdata),
		.rvfi_mem_wdata(rvfi_mem_wdata),
`endif

		.trace_valid(trace_valid),
		.trace_data (trace_data)
	);
endmodule
