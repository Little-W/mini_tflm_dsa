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

// 上游版本：PicoRV32 ef203c2b0a3fb793280f5114941416c425c5b461。
// 处理器执行控制器：管理寄存器、算术运算、异常和协处理器，取指与译码由独立前端处理。
// 地址由行为级算术生成，前端响应和执行请求分别保存，公开接口保持逐周期行为。

/* verilator lint_off WIDTH */
/* verilator lint_off PINMISSING */
/* verilator lint_off CASEOVERLAP */
/* verilator lint_off CASEINCOMPLETE */

`timescale 1 ns / 1 ps
`default_nettype none
// `define DEBUGNETS
// `define DEBUGREGS
// `define DEBUGASM
// `define DEBUG

`ifdef DEBUG
  `define debug(debug_command) debug_command
`else
  `define debug(debug_command)
`endif

`ifdef FORMAL
  `define FORMAL_KEEP (* keep *)
  `define assert(assert_expr) assert(assert_expr)
`else
  `ifdef DEBUGNETS
    `define FORMAL_KEEP (* keep *)
  `else
    `define FORMAL_KEEP
  `endif
  `define assert(assert_expr) empty_statement
`endif

// uncomment this for register file in extra module
// `define PICORV32_REGS picorv32_regs

// this macro can be used to check if the verilog files in your
// design are read in the correct order.
`define PICORV32_V

/***************************************************************
 * picorv32
 ***************************************************************/

module picorv32 #(
    parameter [ 0:0] ENABLE_COUNTERS = 1,
    parameter [ 0:0] ENABLE_COUNTERS64 = 1,
    parameter [ 0:0] ENABLE_REGS_16_31 = 1,
    parameter [ 0:0] ENABLE_REGS_DUALPORT = 1,
    parameter [ 0:0] LATCHED_MEM_RDATA = 0,
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
    output reg trap /* 处理器异常停止指示。 */,

    output logic        mem_valid /* 处理器存储访问请求有效。 */,
    output logic        mem_instr /* 当前存储请求为取指访问。 */,
    input             mem_ready /* 处理器当前存储请求完成。 */,

    output logic [31:0] mem_addr /* 处理器存储访问字节地址。 */,
    output logic [31:0] mem_wdata /* 处理器写入数据。 */,
    output logic [ 3:0] mem_wstrb /* 处理器写入字节使能，全零表示读取。 */,
    input      [31:0] mem_rdata /* 返回处理器的读取数据。 */,

    // Look-Ahead Interface
    output            mem_la_read /* 下一周期的读取请求预告。 */,
    output            mem_la_write /* 下一周期的写入请求预告。 */,
    output     [31:0] mem_la_addr /* 预告请求的字节地址。 */,
    output logic [31:0] mem_la_wdata /* 预告写入请求的数据。 */,
    output logic [ 3:0] mem_la_wstrb /* 预告写入请求的字节使能。 */,

    // Pico Co-Processor Interface (PCPI)
    output reg        pcpi_valid /* 协处理器指令请求有效。 */,
    output logic [31:0] pcpi_insn /* 待执行的协处理器指令编码。 */,
    output     [31:0] pcpi_rs1 /* 协处理器第一源操作数。 */,
    output     [31:0] pcpi_rs2 /* 协处理器第二源操作数。 */,
    input             pcpi_wr /* 协处理器结果需写回目标寄存器。 */,
    input      [31:0] pcpi_rd /* 协处理器返回的目标寄存器数据。 */,
    input             pcpi_wait /* 协处理器正在处理请求。 */,
    input             pcpi_ready /* 协处理器指令已完成。 */,

    // IRQ Interface
    input      [31:0] irq /* 处理器中断请求向量。 */,
    output reg [31:0] eoi /* 已响应的中断请求位。 */,

`ifdef RISCV_FORMAL
    output reg        rvfi_valid /* RVFI 当前指令提交记录有效。 */,
    output reg [63:0] rvfi_order /* RVFI 已提交指令的顺序编号。 */,
    output reg [31:0] rvfi_insn /* RVFI 已提交指令编码。 */,
    output reg        rvfi_trap /* RVFI 当前指令触发异常。 */,
    output reg        rvfi_halt /* RVFI 当前指令使处理器停止执行。 */,
    output reg        rvfi_intr /* RVFI 当前指令进入中断或异常处理。 */,
    output reg [ 1:0] rvfi_mode /* RVFI 当前指令的特权模式。 */,
    output reg [ 1:0] rvfi_ixl /* RVFI 当前指令使用的整数寄存器宽度编码。 */,
    output reg [ 4:0] rvfi_rs1_addr /* RVFI 第一源寄存器编号。 */,
    output reg [ 4:0] rvfi_rs2_addr /* RVFI 第二源寄存器编号。 */,
    output reg [31:0] rvfi_rs1_rdata /* RVFI 第一源寄存器读取值。 */,
    output reg [31:0] rvfi_rs2_rdata /* RVFI 第二源寄存器读取值。 */,
    output reg [ 4:0] rvfi_rd_addr /* RVFI 目标寄存器编号。 */,
    output reg [31:0] rvfi_rd_wdata /* RVFI 目标寄存器写入值。 */,
    output reg [31:0] rvfi_pc_rdata /* RVFI 执行指令前的程序计数器。 */,
    output reg [31:0] rvfi_pc_wdata /* RVFI 执行指令后的程序计数器。 */,
    output reg [31:0] rvfi_mem_addr /* RVFI 指令访问的存储字节地址。 */,
    output reg [ 3:0] rvfi_mem_rmask /* RVFI 存储读取的字节掩码。 */,
    output reg [ 3:0] rvfi_mem_wmask /* RVFI 存储写入的字节掩码。 */,
    output reg [31:0] rvfi_mem_rdata /* RVFI 存储读取值。 */,
    output reg [31:0] rvfi_mem_wdata /* RVFI 存储写入值。 */,

    output reg [63:0] rvfi_csr_mcycle_rmask /* RVFI 周期计数器读取掩码。 */,
    output reg [63:0] rvfi_csr_mcycle_wmask /* RVFI 周期计数器写入掩码。 */,
    output reg [63:0] rvfi_csr_mcycle_rdata /* RVFI 周期计数器读取值。 */,
    output reg [63:0] rvfi_csr_mcycle_wdata /* RVFI 周期计数器写入值。 */,

    output reg [63:0] rvfi_csr_minstret_rmask /* RVFI 已提交指令计数器读取掩码。 */,
    output reg [63:0] rvfi_csr_minstret_wmask /* RVFI 已提交指令计数器写入掩码。 */,
    output reg [63:0] rvfi_csr_minstret_rdata /* RVFI 已提交指令计数器读取值。 */,
    output reg [63:0] rvfi_csr_minstret_wdata /* RVFI 已提交指令计数器写入值。 */,
`endif

    // Trace Interface
    output reg        trace_valid /* 指令执行记录有效。 */,
    output reg [35:0] trace_data /* 指令执行记录的类型和数据。 */
);
    localparam integer irq_timer = 0;
    localparam integer irq_ebreak = 1;
    localparam integer irq_buserror = 2;

    localparam integer irqregs_offset = ENABLE_REGS_16_31 ? 32 : 16;
    localparam integer regfile_size = (ENABLE_REGS_16_31 ? 32 : 16) + 4*ENABLE_IRQ*ENABLE_IRQ_QREGS;
    localparam integer regindex_bits = (ENABLE_REGS_16_31 ? 5 : 4) + ENABLE_IRQ*ENABLE_IRQ_QREGS;

    localparam WITH_PCPI = ENABLE_PCPI || ENABLE_MUL || ENABLE_FAST_MUL || ENABLE_DIV;

    localparam [35:0] TRACE_BRANCH = {4'b 0001, 32'b 0};
    localparam [35:0] TRACE_ADDR   = {4'b 0010, 32'b 0};
    localparam [35:0] TRACE_IRQ    = {4'b 1000, 32'b 0};

    reg [63:0] count_cycle, count_instr;
    reg [31:0] reg_pc, reg_next_pc, reg_op1, reg_op2, reg_out;
    reg [4:0] reg_sh;

    wire dbg_mem_valid = mem_valid;
    wire dbg_mem_instr = mem_instr;
    wire dbg_mem_ready = mem_ready;
    wire [31:0] dbg_mem_addr  = mem_addr;
    wire [31:0] dbg_mem_wdata = mem_wdata;
    wire [ 3:0] dbg_mem_wstrb = mem_wstrb;
    wire [31:0] dbg_mem_rdata = mem_rdata;

    assign pcpi_rs1 = reg_op1;
    assign pcpi_rs2 = reg_op2;

    wire [31:0] next_pc;

    reg irq_delay;
    reg irq_active;
    reg [31:0] irq_mask;
    reg [31:0] irq_pending;
    reg [31:0] timer;

`ifndef PICORV32_REGS
    reg [31:0] cpuregs [0:regfile_size-1];

    integer i;
    initial begin
        if (REGS_INIT_ZERO) begin
            for (i = 0; i < regfile_size; i = i+1)
                cpuregs[i] = 0;
        end
    end
`endif

    task empty_statement;
        // This task is used by the `assert directive in non-formal mode to
        // avoid empty statement (which are unsupported by plain Verilog syntax).
        begin end
    endtask

`ifdef DEBUGREGS
    wire [31:0] dbg_reg_x0  = 0;
    wire [31:0] dbg_reg_x1  = cpuregs[1];
    wire [31:0] dbg_reg_x2  = cpuregs[2];
    wire [31:0] dbg_reg_x3  = cpuregs[3];
    wire [31:0] dbg_reg_x4  = cpuregs[4];
    wire [31:0] dbg_reg_x5  = cpuregs[5];
    wire [31:0] dbg_reg_x6  = cpuregs[6];
    wire [31:0] dbg_reg_x7  = cpuregs[7];
    wire [31:0] dbg_reg_x8  = cpuregs[8];
    wire [31:0] dbg_reg_x9  = cpuregs[9];
    wire [31:0] dbg_reg_x10 = cpuregs[10];
    wire [31:0] dbg_reg_x11 = cpuregs[11];
    wire [31:0] dbg_reg_x12 = cpuregs[12];
    wire [31:0] dbg_reg_x13 = cpuregs[13];
    wire [31:0] dbg_reg_x14 = cpuregs[14];
    wire [31:0] dbg_reg_x15 = cpuregs[15];
    wire [31:0] dbg_reg_x16 = cpuregs[16];
    wire [31:0] dbg_reg_x17 = cpuregs[17];
    wire [31:0] dbg_reg_x18 = cpuregs[18];
    wire [31:0] dbg_reg_x19 = cpuregs[19];
    wire [31:0] dbg_reg_x20 = cpuregs[20];
    wire [31:0] dbg_reg_x21 = cpuregs[21];
    wire [31:0] dbg_reg_x22 = cpuregs[22];
    wire [31:0] dbg_reg_x23 = cpuregs[23];
    wire [31:0] dbg_reg_x24 = cpuregs[24];
    wire [31:0] dbg_reg_x25 = cpuregs[25];
    wire [31:0] dbg_reg_x26 = cpuregs[26];
    wire [31:0] dbg_reg_x27 = cpuregs[27];
    wire [31:0] dbg_reg_x28 = cpuregs[28];
    wire [31:0] dbg_reg_x29 = cpuregs[29];
    wire [31:0] dbg_reg_x30 = cpuregs[30];
    wire [31:0] dbg_reg_x31 = cpuregs[31];
`endif

    // Internal PCPI Cores

    wire        pcpi_mul_wr;
    wire [31:0] pcpi_mul_rd;
    wire        pcpi_mul_wait;
    wire        pcpi_mul_ready;

    wire        pcpi_div_wr;
    wire [31:0] pcpi_div_rd;
    wire        pcpi_div_wait;
    wire        pcpi_div_ready;

    reg        pcpi_int_wr;
    reg [31:0] pcpi_int_rd;
    reg        pcpi_int_wait;
    reg        pcpi_int_ready;

    generate if (ENABLE_FAST_MUL) begin
        picorv32_pcpi_fast_mul pcpi_mul (
            .clk       (clk            ),
            .resetn    (resetn         ),
            .pcpi_valid(pcpi_valid     ),
            .pcpi_insn (pcpi_insn      ),
            .pcpi_rs1  (pcpi_rs1       ),
            .pcpi_rs2  (pcpi_rs2       ),
            .pcpi_wr   (pcpi_mul_wr    ),
            .pcpi_rd   (pcpi_mul_rd    ),
            .pcpi_wait (pcpi_mul_wait  ),
            .pcpi_ready(pcpi_mul_ready )
        );
    end else if (ENABLE_MUL) begin
        picorv32_pcpi_mul pcpi_mul (
            .clk       (clk            ),
            .resetn    (resetn         ),
            .pcpi_valid(pcpi_valid     ),
            .pcpi_insn (pcpi_insn      ),
            .pcpi_rs1  (pcpi_rs1       ),
            .pcpi_rs2  (pcpi_rs2       ),
            .pcpi_wr   (pcpi_mul_wr    ),
            .pcpi_rd   (pcpi_mul_rd    ),
            .pcpi_wait (pcpi_mul_wait  ),
            .pcpi_ready(pcpi_mul_ready )
        );
    end else begin
        assign pcpi_mul_wr = 0;
        assign pcpi_mul_rd = 32'bx;
        assign pcpi_mul_wait = 0;
        assign pcpi_mul_ready = 0;
    end endgenerate

    generate if (ENABLE_DIV) begin
        picorv32_pcpi_div pcpi_div (
            .clk       (clk            ),
            .resetn    (resetn         ),
            .pcpi_valid(pcpi_valid     ),
            .pcpi_insn (pcpi_insn      ),
            .pcpi_rs1  (pcpi_rs1       ),
            .pcpi_rs2  (pcpi_rs2       ),
            .pcpi_wr   (pcpi_div_wr    ),
            .pcpi_rd   (pcpi_div_rd    ),
            .pcpi_wait (pcpi_div_wait  ),
            .pcpi_ready(pcpi_div_ready )
        );
    end else begin
        assign pcpi_div_wr = 0;
        assign pcpi_div_rd = 32'bx;
        assign pcpi_div_wait = 0;
        assign pcpi_div_ready = 0;
    end endgenerate

    always @* begin
        pcpi_int_wr = 0;
        pcpi_int_rd = 32'bx;
        pcpi_int_wait  = |{ENABLE_PCPI && pcpi_wait,  (ENABLE_MUL || ENABLE_FAST_MUL) && pcpi_mul_wait,  ENABLE_DIV && pcpi_div_wait};
        pcpi_int_ready = |{ENABLE_PCPI && pcpi_ready, (ENABLE_MUL || ENABLE_FAST_MUL) && pcpi_mul_ready, ENABLE_DIV && pcpi_div_ready};

        (* parallel_case *)
        case (1'b1)
            ENABLE_PCPI && pcpi_ready: begin
                pcpi_int_wr = ENABLE_PCPI ? pcpi_wr : 0;
                pcpi_int_rd = ENABLE_PCPI ? pcpi_rd : 0;
            end
            (ENABLE_MUL || ENABLE_FAST_MUL) && pcpi_mul_ready: begin
                pcpi_int_wr = pcpi_mul_wr;
                pcpi_int_rd = pcpi_mul_rd;
            end
            ENABLE_DIV && pcpi_div_ready: begin
                pcpi_int_wr = pcpi_div_wr;
                pcpi_int_rd = pcpi_div_rd;
            end
        endcase
    end

    // 前端独立管理取指与存储接口，主控制器保留执行状态及请求更新优先次序。
    logic [1:0] mem_wordsize;
    logic mem_do_prefetch, mem_do_rinst, mem_do_rdata, mem_do_wdata;
    logic clear_prefetched_high_word;
    logic decoder_trigger, decoder_trigger_q;
    logic decoder_pseudo_trigger, decoder_pseudo_trigger_q;
    logic launch_next_insn;
    logic [31:0] dbg_rs1val, dbg_rs2val;
    logic dbg_rs1val_valid, dbg_rs2val_valid;
    picorv32_frontend_pkg::request_t frontend_i_request;
    picorv32_frontend_pkg::response_t frontend_o_response;
    logic frontend_i_mem_ready;
    logic [31:0] frontend_i_mem_rdata;
    assign frontend_i_request.trap = trap;
    assign frontend_i_request.next_pc = next_pc;
    assign frontend_i_request.reg_op1 = reg_op1;
    assign frontend_i_request.reg_op2 = reg_op2;
    assign frontend_i_request.mem_wordsize = mem_wordsize;
    assign frontend_i_request.mem_do_prefetch = mem_do_prefetch;
    assign frontend_i_request.mem_do_rinst = mem_do_rinst;
    assign frontend_i_request.mem_do_rdata = mem_do_rdata;
    assign frontend_i_request.mem_do_wdata = mem_do_wdata;
    assign frontend_i_request.clear_prefetched_high_word = clear_prefetched_high_word;
    assign frontend_i_request.decoder_trigger = decoder_trigger;
    assign frontend_i_request.decoder_trigger_q = decoder_trigger_q;
    assign frontend_i_request.decoder_pseudo_trigger = decoder_pseudo_trigger;
    assign frontend_i_request.decoder_pseudo_trigger_q = decoder_pseudo_trigger_q;
    assign frontend_i_request.launch_next_insn = launch_next_insn;
    assign frontend_i_mem_ready = mem_ready;
    assign frontend_i_mem_rdata = mem_rdata;
    picorv32_frontend #(
        .LATCHED_MEM_RDATA(LATCHED_MEM_RDATA),
        .COMPRESSED_ISA(COMPRESSED_ISA),
        .CATCH_ILLINSN(CATCH_ILLINSN),
        .ENABLE_COUNTERS(ENABLE_COUNTERS),
        .ENABLE_COUNTERS64(ENABLE_COUNTERS64),
        .ENABLE_REGS_16_31(ENABLE_REGS_16_31),
        .ENABLE_IRQ(ENABLE_IRQ),
        .ENABLE_IRQ_QREGS(ENABLE_IRQ_QREGS),
        .ENABLE_IRQ_TIMER(ENABLE_IRQ_TIMER),
        .WITH_PCPI(WITH_PCPI)
    ) u_frontend (
        .clk(clk), .rst_n(resetn),
        .i_request(frontend_i_request),
        .i_mem_ready(frontend_i_mem_ready), .i_mem_rdata(frontend_i_mem_rdata),
        .o_response(frontend_o_response)
    );

    // Main State Machine

    localparam cpu_state_trap   = 8'b10000000;
    localparam cpu_state_fetch  = 8'b01000000;
    localparam cpu_state_ld_rs1 = 8'b00100000;
    localparam cpu_state_ld_rs2 = 8'b00010000;
    localparam cpu_state_exec   = 8'b00001000;
    localparam cpu_state_shift  = 8'b00000100;
    localparam cpu_state_stmem  = 8'b00000010;
    localparam cpu_state_ldmem  = 8'b00000001;

    reg [7:0] cpu_state;
    reg [1:0] irq_state;

    `FORMAL_KEEP reg [127:0] dbg_ascii_state;

    always @* begin
        dbg_ascii_state = "";
        if (cpu_state == cpu_state_trap)   dbg_ascii_state = "trap";
        if (cpu_state == cpu_state_fetch)  dbg_ascii_state = "fetch";
        if (cpu_state == cpu_state_ld_rs1) dbg_ascii_state = "ld_rs1";
        if (cpu_state == cpu_state_ld_rs2) dbg_ascii_state = "ld_rs2";
        if (cpu_state == cpu_state_exec)   dbg_ascii_state = "exec";
        if (cpu_state == cpu_state_shift)  dbg_ascii_state = "shift";
        if (cpu_state == cpu_state_stmem)  dbg_ascii_state = "stmem";
        if (cpu_state == cpu_state_ldmem)  dbg_ascii_state = "ldmem";
    end

    reg set_mem_do_rinst;
    reg set_mem_do_rdata;
    reg set_mem_do_wdata;

    reg latched_store;
    reg latched_stalu;
    reg latched_branch;
    reg latched_compr;
    reg latched_trace;
    reg latched_is_lu;
    reg latched_is_lh;
    reg latched_is_lb;
    reg [regindex_bits-1:0] latched_rd;

    reg [31:0] current_pc;
    assign next_pc = latched_store && latched_branch ? reg_out & ~1 : reg_next_pc;

    reg [3:0] pcpi_timeout_counter;
    reg pcpi_timeout;

    reg [31:0] next_irq_pending;
    reg do_waitirq;

    reg [31:0] alu_out, alu_out_q;
    reg alu_out_0, alu_out_0_q;
    reg alu_wait, alu_wait_2;

    // 加减法和关系比较分别准备，控制只选择已经完成的结果。
    wire [31:0] operand_addition = reg_op1 + reg_op2;
    wire [32:0] operand_difference = {1'b0, reg_op1} - {1'b0, reg_op2};
    wire [31:0] return_address_sum = reg_pc + (latched_compr ? 32'd2 : 32'd4);
    wire [63:0] next_cycle_count = count_cycle + 64'd1;
    wire [63:0] next_instruction_count = count_instr + 64'd1;
    reg [31:0] alu_add_sub;
    reg [31:0] alu_shl, alu_shr;
    reg alu_eq, alu_ltu, alu_lts;
    logic operand_unsigned_less, operand_signed_less;

    // 比较按三位分组并行计算，有符号次序只在符号不同时选择符号位。
    pico_operand_comparison u_operand_comparison (
        .i_a(reg_op1), .i_b(reg_op2),
        .o_unsigned_less(operand_unsigned_less), .o_signed_less(operand_signed_less)
    );

    // 取指地址选择只依赖已保存状态，地址加法在寄存器接收边沿前完成。
    reg [31:0] selected_fetch_pc;
    always @* begin
        selected_fetch_pc = reg_next_pc;
        (* parallel_case *)
        case (1'b1)
            latched_branch:
                selected_fetch_pc = latched_store ? (latched_stalu ? alu_out_q : reg_out) & ~32'd1 : reg_next_pc;
            latched_store && !latched_branch:
                selected_fetch_pc = reg_next_pc;
            ENABLE_IRQ && irq_state[0]:
                selected_fetch_pc = PROGADDR_IRQ;
            ENABLE_IRQ && irq_state[1]:
                selected_fetch_pc = reg_next_pc;
        endcase
    end
    // 顺序、直接跳转与相对分支地址保留完整 32 位模加结果。
    logic [31:0] sequential_address_sum;
    pico_sequential_address u_sequential_address (
        .i_address(selected_fetch_pc), .i_compressed(frontend_o_response.compressed_instr),
        .o_address(sequential_address_sum)
    );
    logic [31:0] jump_address_sum;
    logic unused_jump_carry;
`ifdef SYNTHESIS
    // 两个半字同时相加，末级按低半字进位修正高半字。
    parallel_prefix_add #(.p_width(32), .p_group_width(4), .p_preserve_groups(1'b1),
        .p_dsp_split_width(16), .p_parallel_high_prefix(1'b1), .p_keep_carry(1'b0)) u_jump_address (
        .i_a(selected_fetch_pc), .i_b(frontend_o_response.decoded_imm_j), .i_carry(1'b0),
        .o_sum(jump_address_sum), .o_carry(unused_jump_carry)
    );
`else
    assign {unused_jump_carry, jump_address_sum} = {1'b0, selected_fetch_pc} + {1'b0, frontend_o_response.decoded_imm_j};
`endif
    wire [31:0] branch_address_sum = reg_pc + frontend_o_response.decoded_imm;
    // 访存指令共用保存操作数与立即数的完整地址加法。
    wire [31:0] memory_address_sum = reg_op1 + frontend_o_response.decoded_imm;

    generate if (TWO_CYCLE_ALU) begin
        always @(posedge clk) begin
            alu_add_sub <= frontend_o_response.instr_sub ? operand_difference[31:0] : operand_addition;
            alu_eq <= reg_op1 == reg_op2;
            alu_lts <= operand_signed_less;
            alu_ltu <= operand_unsigned_less;
            alu_shl <= reg_op1 << reg_op2[4:0];
            alu_shr <= $signed({frontend_o_response.instr_sra || frontend_o_response.instr_srai ? reg_op1[31] : 1'b0, reg_op1}) >>> reg_op2[4:0];
        end
    end else begin
        always @* begin
            alu_add_sub = frontend_o_response.instr_sub ? operand_difference[31:0] : operand_addition;
            alu_eq = reg_op1 == reg_op2;
            alu_lts = operand_signed_less;
            alu_ltu = operand_unsigned_less;
            alu_shl = reg_op1 << reg_op2[4:0];
            alu_shr = $signed({frontend_o_response.instr_sra || frontend_o_response.instr_srai ? reg_op1[31] : 1'b0, reg_op1}) >>> reg_op2[4:0];
        end
    end endgenerate

    always @* begin
        alu_out_0 = 'bx;
        (* parallel_case, full_case *)
        case (1'b1)
            frontend_o_response.instr_beq:
                alu_out_0 = alu_eq;
            frontend_o_response.instr_bne:
                alu_out_0 = !alu_eq;
            frontend_o_response.instr_bge:
                alu_out_0 = !alu_lts;
            frontend_o_response.instr_bgeu:
                alu_out_0 = !alu_ltu;
            frontend_o_response.is_slti_blt_slt && (!TWO_CYCLE_COMPARE || !{frontend_o_response.instr_beq,frontend_o_response.instr_bne,frontend_o_response.instr_bge,frontend_o_response.instr_bgeu}):
                alu_out_0 = alu_lts;
            frontend_o_response.is_sltiu_bltu_sltu && (!TWO_CYCLE_COMPARE || !{frontend_o_response.instr_beq,frontend_o_response.instr_bne,frontend_o_response.instr_bge,frontend_o_response.instr_bgeu}):
                alu_out_0 = alu_ltu;
        endcase

        alu_out = 'bx;
        (* parallel_case, full_case *)
        case (1'b1)
            frontend_o_response.is_lui_auipc_jal_jalr_addi_add_sub:
                alu_out = alu_add_sub;
            frontend_o_response.is_compare:
                alu_out = alu_out_0;
            frontend_o_response.instr_xori || frontend_o_response.instr_xor:
                alu_out = reg_op1 ^ reg_op2;
            frontend_o_response.instr_ori || frontend_o_response.instr_or:
                alu_out = reg_op1 | reg_op2;
            frontend_o_response.instr_andi || frontend_o_response.instr_and:
                alu_out = reg_op1 & reg_op2;
            BARREL_SHIFTER && (frontend_o_response.instr_sll || frontend_o_response.instr_slli):
                alu_out = alu_shl;
            BARREL_SHIFTER && (frontend_o_response.instr_srl || frontend_o_response.instr_srli || frontend_o_response.instr_sra || frontend_o_response.instr_srai):
                alu_out = alu_shr;
        endcase

`ifdef RISCV_FORMAL_BLACKBOX_ALU
        alu_out_0 = $anyseq;
        alu_out = $anyseq;
`endif
    end

    reg clear_prefetched_high_word_q;
    always @(posedge clk) clear_prefetched_high_word_q <= clear_prefetched_high_word;

    always @* begin
        clear_prefetched_high_word = clear_prefetched_high_word_q;
        if (!frontend_o_response.prefetched_high_word)
            clear_prefetched_high_word = 0;
        if (latched_branch || irq_state || !resetn)
            clear_prefetched_high_word = COMPRESSED_ISA;
    end

    reg cpuregs_write;
    reg [31:0] cpuregs_wrdata;
    reg [31:0] cpuregs_rs1;
    reg [31:0] cpuregs_rs2;
    reg [regindex_bits-1:0] decoded_rs;

    always @* begin
        cpuregs_write = 0;
        cpuregs_wrdata = 'bx;

        if (cpu_state == cpu_state_fetch) begin
            (* parallel_case *)
            case (1'b1)
                latched_branch: begin
                    cpuregs_wrdata = return_address_sum;
                    cpuregs_write = 1;
                end
                latched_store && !latched_branch: begin
                    cpuregs_wrdata = latched_stalu ? alu_out_q : reg_out;
                    cpuregs_write = 1;
                end
                ENABLE_IRQ && irq_state[0]: begin
                    cpuregs_wrdata = reg_next_pc | latched_compr;
                    cpuregs_write = 1;
                end
                ENABLE_IRQ && irq_state[1]: begin
                    cpuregs_wrdata = irq_pending & ~irq_mask;
                    cpuregs_write = 1;
                end
            endcase
        end
    end

`ifndef PICORV32_REGS
    always @(posedge clk) begin
        if (resetn && cpuregs_write && latched_rd)
`ifdef PICORV32_TESTBUG_001
            cpuregs[latched_rd ^ 1] <= cpuregs_wrdata;
`elsif PICORV32_TESTBUG_002
            cpuregs[latched_rd] <= cpuregs_wrdata ^ 1;
`else
            cpuregs[latched_rd] <= cpuregs_wrdata;
`endif
    end

    always @* begin
        decoded_rs = 'bx;
        if (ENABLE_REGS_DUALPORT) begin
`ifndef RISCV_FORMAL_BLACKBOX_REGS
            cpuregs_rs1 = frontend_o_response.decoded_rs1 ? cpuregs[frontend_o_response.decoded_rs1] : 0;
            cpuregs_rs2 = frontend_o_response.decoded_rs2 ? cpuregs[frontend_o_response.decoded_rs2] : 0;
`else
            cpuregs_rs1 = frontend_o_response.decoded_rs1 ? $anyseq : 0;
            cpuregs_rs2 = frontend_o_response.decoded_rs2 ? $anyseq : 0;
`endif
        end else begin
            decoded_rs = (cpu_state == cpu_state_ld_rs2) ? frontend_o_response.decoded_rs2 : frontend_o_response.decoded_rs1;
`ifndef RISCV_FORMAL_BLACKBOX_REGS
            cpuregs_rs1 = decoded_rs ? cpuregs[decoded_rs] : 0;
`else
            cpuregs_rs1 = decoded_rs ? $anyseq : 0;
`endif
            cpuregs_rs2 = cpuregs_rs1;
        end
    end
`else
    wire[31:0] cpuregs_rdata1;
    wire[31:0] cpuregs_rdata2;

    wire [5:0] cpuregs_waddr = latched_rd;
    wire [5:0] cpuregs_raddr1 = ENABLE_REGS_DUALPORT ? frontend_o_response.decoded_rs1 : decoded_rs;
    wire [5:0] cpuregs_raddr2 = ENABLE_REGS_DUALPORT ? frontend_o_response.decoded_rs2 : 0;

    `PICORV32_REGS cpuregs (
        .clk(clk),
        .wen(resetn && cpuregs_write && latched_rd),
        .waddr(cpuregs_waddr),
        .raddr1(cpuregs_raddr1),
        .raddr2(cpuregs_raddr2),
        .wdata(cpuregs_wrdata),
        .rdata1(cpuregs_rdata1),
        .rdata2(cpuregs_rdata2)
    );

    always @* begin
        decoded_rs = 'bx;
        if (ENABLE_REGS_DUALPORT) begin
            cpuregs_rs1 = frontend_o_response.decoded_rs1 ? cpuregs_rdata1 : 0;
            cpuregs_rs2 = frontend_o_response.decoded_rs2 ? cpuregs_rdata2 : 0;
        end else begin
            decoded_rs = (cpu_state == cpu_state_ld_rs2) ? frontend_o_response.decoded_rs2 : frontend_o_response.decoded_rs1;
            cpuregs_rs1 = decoded_rs ? cpuregs_rdata1 : 0;
            cpuregs_rs2 = cpuregs_rs1;
        end
    end
`endif

    assign launch_next_insn = cpu_state == cpu_state_fetch && decoder_trigger && (!ENABLE_IRQ || irq_delay || irq_active || !(irq_pending & ~irq_mask));

    always @(posedge clk) begin
        trap <= 0;
        reg_sh <= 'bx;
        reg_out <= 'bx;
        set_mem_do_rinst = 0;
        set_mem_do_rdata = 0;
        set_mem_do_wdata = 0;

        alu_out_0_q <= alu_out_0;
        alu_out_q <= alu_out;

        alu_wait <= 0;
        alu_wait_2 <= 0;

        if (launch_next_insn) begin
            dbg_rs1val <= 'bx;
            dbg_rs2val <= 'bx;
            dbg_rs1val_valid <= 0;
            dbg_rs2val_valid <= 0;
        end

        if (WITH_PCPI && CATCH_ILLINSN) begin
            if (resetn && pcpi_valid && !pcpi_int_wait) begin
                if (pcpi_timeout_counter)
                    pcpi_timeout_counter <= pcpi_timeout_counter - 1;
            end else
                pcpi_timeout_counter <= ~0;
            pcpi_timeout <= !pcpi_timeout_counter;
        end

        if (ENABLE_COUNTERS) begin
            count_cycle <= resetn ? next_cycle_count : 0;
            if (!ENABLE_COUNTERS64) count_cycle[63:32] <= 0;
        end else begin
            count_cycle <= 'bx;
            count_instr <= 'bx;
        end

        next_irq_pending = ENABLE_IRQ ? irq_pending & LATCHED_IRQ : 'bx;

        if (ENABLE_IRQ && ENABLE_IRQ_TIMER && timer) begin
            timer <= timer - 1;
        end

        decoder_trigger <= mem_do_rinst && frontend_o_response.mem_done;
        decoder_trigger_q <= decoder_trigger;
        decoder_pseudo_trigger <= 0;
        decoder_pseudo_trigger_q <= decoder_pseudo_trigger;
        do_waitirq <= 0;

        trace_valid <= 0;

        if (!ENABLE_TRACE)
            trace_data <= 'bx;

        if (!resetn) begin
            reg_pc <= PROGADDR_RESET;
            reg_next_pc <= PROGADDR_RESET;
            if (ENABLE_COUNTERS)
                count_instr <= 0;
            latched_store <= 0;
            latched_stalu <= 0;
            latched_branch <= 0;
            latched_trace <= 0;
            latched_is_lu <= 0;
            latched_is_lh <= 0;
            latched_is_lb <= 0;
            pcpi_valid <= 0;
            pcpi_timeout <= 0;
            irq_active <= 0;
            irq_delay <= 0;
            irq_mask <= ~0;
            next_irq_pending = 0;
            irq_state <= 0;
            eoi <= 0;
            timer <= 0;
            if (~STACKADDR) begin
                latched_store <= 1;
                latched_rd <= 2;
                reg_out <= STACKADDR;
            end
            cpu_state <= cpu_state_fetch;
        end else
        (* parallel_case, full_case *)
        case (cpu_state)
            cpu_state_trap: begin
                trap <= 1;
            end

            cpu_state_fetch: begin
                mem_do_rinst <= !decoder_trigger && !do_waitirq;
                mem_wordsize <= 0;

                current_pc = reg_next_pc;

                (* parallel_case *)
                case (1'b1)
                    latched_branch: begin
                        current_pc = latched_store ? (latched_stalu ? alu_out_q : reg_out) & ~1 : reg_next_pc;
                        `debug($display("ST_RD:  %2d 0x%08x, BRANCH 0x%08x", latched_rd, reg_pc + (latched_compr ? 2 : 4), current_pc);)
                    end
                    latched_store && !latched_branch: begin
                        `debug($display("ST_RD:  %2d 0x%08x", latched_rd, latched_stalu ? alu_out_q : reg_out);)
                    end
                    ENABLE_IRQ && irq_state[0]: begin
                        current_pc = PROGADDR_IRQ;
                        irq_active <= 1;
                        mem_do_rinst <= 1;
                    end
                    ENABLE_IRQ && irq_state[1]: begin
                        eoi <= irq_pending & ~irq_mask;
                        next_irq_pending = next_irq_pending & irq_mask;
                    end
                endcase

                if (ENABLE_TRACE && latched_trace) begin
                    latched_trace <= 0;
                    trace_valid <= 1;
                    if (latched_branch)
                        trace_data <= (irq_active ? TRACE_IRQ : 0) | TRACE_BRANCH | (current_pc & 32'hfffffffe);
                    else
                        trace_data <= (irq_active ? TRACE_IRQ : 0) | (latched_stalu ? alu_out_q : reg_out);
                end

                reg_pc <= current_pc;
                reg_next_pc <= current_pc;

                latched_store <= 0;
                latched_stalu <= 0;
                latched_branch <= 0;
                latched_is_lu <= 0;
                latched_is_lh <= 0;
                latched_is_lb <= 0;
                latched_rd <= frontend_o_response.decoded_rd;
                latched_compr <= frontend_o_response.compressed_instr;

                if (ENABLE_IRQ && ((decoder_trigger && !irq_active && !irq_delay && |(irq_pending & ~irq_mask)) || irq_state)) begin
                    irq_state <=
                        irq_state == 2'b00 ? 2'b01 :
                        irq_state == 2'b01 ? 2'b10 : 2'b00;
                    latched_compr <= latched_compr;
                    if (ENABLE_IRQ_QREGS)
                        latched_rd <= irqregs_offset | irq_state[0];
                    else
                        latched_rd <= irq_state[0] ? 4 : 3;
                end else
                if (ENABLE_IRQ && (decoder_trigger || do_waitirq) && frontend_o_response.instr_waitirq) begin
                    if (irq_pending) begin
                        latched_store <= 1;
                        reg_out <= irq_pending;
                        reg_next_pc <= sequential_address_sum;
                        mem_do_rinst <= 1;
                    end else
                        do_waitirq <= 1;
                end else
                if (decoder_trigger) begin
                    `debug($display("-- %-0t", $time);)
                    irq_delay <= irq_active;
                    reg_next_pc <= sequential_address_sum;
                    if (ENABLE_TRACE)
                        latched_trace <= 1;
                    if (ENABLE_COUNTERS) begin
                        count_instr <= next_instruction_count;
                        if (!ENABLE_COUNTERS64) count_instr[63:32] <= 0;
                    end
                    if (frontend_o_response.instr_jal) begin
                        mem_do_rinst <= 1;
                        reg_next_pc <= jump_address_sum;
                        latched_branch <= 1;
                    end else begin
                        mem_do_rinst <= 0;
                        mem_do_prefetch <= !frontend_o_response.instr_jalr && !frontend_o_response.instr_retirq;
                        cpu_state <= cpu_state_ld_rs1;
                    end
                end
            end

            cpu_state_ld_rs1: begin
                reg_op1 <= 'bx;
                reg_op2 <= 'bx;

                (* parallel_case *)
                case (1'b1)
                    (CATCH_ILLINSN || WITH_PCPI) && frontend_o_response.instr_trap: begin
                        if (WITH_PCPI) begin
                            `debug($display("LD_RS1: %2d 0x%08x", frontend_o_response.decoded_rs1, cpuregs_rs1);)
                            reg_op1 <= cpuregs_rs1;
                            dbg_rs1val <= cpuregs_rs1;
                            dbg_rs1val_valid <= 1;
                            if (ENABLE_REGS_DUALPORT) begin
                                pcpi_valid <= 1;
                                `debug($display("LD_RS2: %2d 0x%08x", frontend_o_response.decoded_rs2, cpuregs_rs2);)
                                reg_sh <= cpuregs_rs2;
                                reg_op2 <= cpuregs_rs2;
                                dbg_rs2val <= cpuregs_rs2;
                                dbg_rs2val_valid <= 1;
                                if (pcpi_int_ready) begin
                                    mem_do_rinst <= 1;
                                    pcpi_valid <= 0;
                                    reg_out <= pcpi_int_rd;
                                    latched_store <= pcpi_int_wr;
                                    cpu_state <= cpu_state_fetch;
                                end else
                                if (CATCH_ILLINSN && (pcpi_timeout || frontend_o_response.instr_ecall_ebreak)) begin
                                    pcpi_valid <= 0;
                                    `debug($display("EBREAK OR UNSUPPORTED INSN AT 0x%08x", reg_pc);)
                                    if (ENABLE_IRQ && !irq_mask[irq_ebreak] && !irq_active) begin
                                        next_irq_pending[irq_ebreak] = 1;
                                        cpu_state <= cpu_state_fetch;
                                    end else
                                        cpu_state <= cpu_state_trap;
                                end
                            end else begin
                                cpu_state <= cpu_state_ld_rs2;
                            end
                        end else begin
                            `debug($display("EBREAK OR UNSUPPORTED INSN AT 0x%08x", reg_pc);)
                            if (ENABLE_IRQ && !irq_mask[irq_ebreak] && !irq_active) begin
                                next_irq_pending[irq_ebreak] = 1;
                                cpu_state <= cpu_state_fetch;
                            end else
                                cpu_state <= cpu_state_trap;
                        end
                    end
                    ENABLE_COUNTERS && frontend_o_response.is_rdcycle_rdcycleh_rdinstr_rdinstrh: begin
                        (* parallel_case, full_case *)
                        case (1'b1)
                            frontend_o_response.instr_rdcycle:
                                reg_out <= count_cycle[31:0];
                            frontend_o_response.instr_rdcycleh && ENABLE_COUNTERS64:
                                reg_out <= count_cycle[63:32];
                            frontend_o_response.instr_rdinstr:
                                reg_out <= count_instr[31:0];
                            frontend_o_response.instr_rdinstrh && ENABLE_COUNTERS64:
                                reg_out <= count_instr[63:32];
                        endcase
                        latched_store <= 1;
                        cpu_state <= cpu_state_fetch;
                    end
                    frontend_o_response.is_lui_auipc_jal: begin
                        reg_op1 <= frontend_o_response.instr_lui ? 0 : reg_pc;
                        reg_op2 <= frontend_o_response.decoded_imm;
                        if (TWO_CYCLE_ALU)
                            alu_wait <= 1;
                        else
                            mem_do_rinst <= mem_do_prefetch;
                        cpu_state <= cpu_state_exec;
                    end
                    ENABLE_IRQ && ENABLE_IRQ_QREGS && frontend_o_response.instr_getq: begin
                        `debug($display("LD_RS1: %2d 0x%08x", frontend_o_response.decoded_rs1, cpuregs_rs1);)
                        reg_out <= cpuregs_rs1;
                        dbg_rs1val <= cpuregs_rs1;
                        dbg_rs1val_valid <= 1;
                        latched_store <= 1;
                        cpu_state <= cpu_state_fetch;
                    end
                    ENABLE_IRQ && ENABLE_IRQ_QREGS && frontend_o_response.instr_setq: begin
                        `debug($display("LD_RS1: %2d 0x%08x", frontend_o_response.decoded_rs1, cpuregs_rs1);)
                        reg_out <= cpuregs_rs1;
                        dbg_rs1val <= cpuregs_rs1;
                        dbg_rs1val_valid <= 1;
                        latched_rd <= latched_rd | irqregs_offset;
                        latched_store <= 1;
                        cpu_state <= cpu_state_fetch;
                    end
                    ENABLE_IRQ && frontend_o_response.instr_retirq: begin
                        eoi <= 0;
                        irq_active <= 0;
                        latched_branch <= 1;
                        latched_store <= 1;
                        `debug($display("LD_RS1: %2d 0x%08x", frontend_o_response.decoded_rs1, cpuregs_rs1);)
                        reg_out <= CATCH_MISALIGN ? (cpuregs_rs1 & 32'h fffffffe) : cpuregs_rs1;
                        dbg_rs1val <= cpuregs_rs1;
                        dbg_rs1val_valid <= 1;
                        cpu_state <= cpu_state_fetch;
                    end
                    ENABLE_IRQ && frontend_o_response.instr_maskirq: begin
                        latched_store <= 1;
                        reg_out <= irq_mask;
                        `debug($display("LD_RS1: %2d 0x%08x", frontend_o_response.decoded_rs1, cpuregs_rs1);)
                        irq_mask <= cpuregs_rs1 | MASKED_IRQ;
                        dbg_rs1val <= cpuregs_rs1;
                        dbg_rs1val_valid <= 1;
                        cpu_state <= cpu_state_fetch;
                    end
                    ENABLE_IRQ && ENABLE_IRQ_TIMER && frontend_o_response.instr_timer: begin
                        latched_store <= 1;
                        reg_out <= timer;
                        `debug($display("LD_RS1: %2d 0x%08x", frontend_o_response.decoded_rs1, cpuregs_rs1);)
                        timer <= cpuregs_rs1;
                        dbg_rs1val <= cpuregs_rs1;
                        dbg_rs1val_valid <= 1;
                        cpu_state <= cpu_state_fetch;
                    end
                    frontend_o_response.is_lb_lh_lw_lbu_lhu && !frontend_o_response.instr_trap: begin
                        `debug($display("LD_RS1: %2d 0x%08x", frontend_o_response.decoded_rs1, cpuregs_rs1);)
                        reg_op1 <= cpuregs_rs1;
                        dbg_rs1val <= cpuregs_rs1;
                        dbg_rs1val_valid <= 1;
                        cpu_state <= cpu_state_ldmem;
                        mem_do_rinst <= 1;
                    end
                    frontend_o_response.is_slli_srli_srai && !BARREL_SHIFTER: begin
                        `debug($display("LD_RS1: %2d 0x%08x", frontend_o_response.decoded_rs1, cpuregs_rs1);)
                        reg_op1 <= cpuregs_rs1;
                        dbg_rs1val <= cpuregs_rs1;
                        dbg_rs1val_valid <= 1;
                        reg_sh <= frontend_o_response.decoded_rs2;
                        cpu_state <= cpu_state_shift;
                    end
                    frontend_o_response.is_jalr_addi_slti_sltiu_xori_ori_andi, frontend_o_response.is_slli_srli_srai && BARREL_SHIFTER: begin
                        `debug($display("LD_RS1: %2d 0x%08x", frontend_o_response.decoded_rs1, cpuregs_rs1);)
                        reg_op1 <= cpuregs_rs1;
                        dbg_rs1val <= cpuregs_rs1;
                        dbg_rs1val_valid <= 1;
                        reg_op2 <= frontend_o_response.is_slli_srli_srai && BARREL_SHIFTER ? frontend_o_response.decoded_rs2 : frontend_o_response.decoded_imm;
                        if (TWO_CYCLE_ALU)
                            alu_wait <= 1;
                        else
                            mem_do_rinst <= mem_do_prefetch;
                        cpu_state <= cpu_state_exec;
                    end
                    default: begin
                        `debug($display("LD_RS1: %2d 0x%08x", frontend_o_response.decoded_rs1, cpuregs_rs1);)
                        reg_op1 <= cpuregs_rs1;
                        dbg_rs1val <= cpuregs_rs1;
                        dbg_rs1val_valid <= 1;
                        if (ENABLE_REGS_DUALPORT) begin
                            `debug($display("LD_RS2: %2d 0x%08x", frontend_o_response.decoded_rs2, cpuregs_rs2);)
                            reg_sh <= cpuregs_rs2;
                            reg_op2 <= cpuregs_rs2;
                            dbg_rs2val <= cpuregs_rs2;
                            dbg_rs2val_valid <= 1;
                            (* parallel_case *)
                            case (1'b1)
                                frontend_o_response.is_sb_sh_sw: begin
                                    cpu_state <= cpu_state_stmem;
                                    mem_do_rinst <= 1;
                                end
                                frontend_o_response.is_sll_srl_sra && !BARREL_SHIFTER: begin
                                    cpu_state <= cpu_state_shift;
                                end
                                default: begin
                                    if (TWO_CYCLE_ALU || (TWO_CYCLE_COMPARE && frontend_o_response.is_beq_bne_blt_bge_bltu_bgeu)) begin
                                        alu_wait_2 <= TWO_CYCLE_ALU && (TWO_CYCLE_COMPARE && frontend_o_response.is_beq_bne_blt_bge_bltu_bgeu);
                                        alu_wait <= 1;
                                    end else
                                        mem_do_rinst <= mem_do_prefetch;
                                    cpu_state <= cpu_state_exec;
                                end
                            endcase
                        end else
                            cpu_state <= cpu_state_ld_rs2;
                    end
                endcase
            end

            cpu_state_ld_rs2: begin
                `debug($display("LD_RS2: %2d 0x%08x", frontend_o_response.decoded_rs2, cpuregs_rs2);)
                reg_sh <= cpuregs_rs2;
                reg_op2 <= cpuregs_rs2;
                dbg_rs2val <= cpuregs_rs2;
                dbg_rs2val_valid <= 1;

                (* parallel_case *)
                case (1'b1)
                    WITH_PCPI && frontend_o_response.instr_trap: begin
                        pcpi_valid <= 1;
                        if (pcpi_int_ready) begin
                            mem_do_rinst <= 1;
                            pcpi_valid <= 0;
                            reg_out <= pcpi_int_rd;
                            latched_store <= pcpi_int_wr;
                            cpu_state <= cpu_state_fetch;
                        end else
                        if (CATCH_ILLINSN && (pcpi_timeout || frontend_o_response.instr_ecall_ebreak)) begin
                            pcpi_valid <= 0;
                            `debug($display("EBREAK OR UNSUPPORTED INSN AT 0x%08x", reg_pc);)
                            if (ENABLE_IRQ && !irq_mask[irq_ebreak] && !irq_active) begin
                                next_irq_pending[irq_ebreak] = 1;
                                cpu_state <= cpu_state_fetch;
                            end else
                                cpu_state <= cpu_state_trap;
                        end
                    end
                    frontend_o_response.is_sb_sh_sw: begin
                        cpu_state <= cpu_state_stmem;
                        mem_do_rinst <= 1;
                    end
                    frontend_o_response.is_sll_srl_sra && !BARREL_SHIFTER: begin
                        cpu_state <= cpu_state_shift;
                    end
                    default: begin
                        if (TWO_CYCLE_ALU || (TWO_CYCLE_COMPARE && frontend_o_response.is_beq_bne_blt_bge_bltu_bgeu)) begin
                            alu_wait_2 <= TWO_CYCLE_ALU && (TWO_CYCLE_COMPARE && frontend_o_response.is_beq_bne_blt_bge_bltu_bgeu);
                            alu_wait <= 1;
                        end else
                            mem_do_rinst <= mem_do_prefetch;
                        cpu_state <= cpu_state_exec;
                    end
                endcase
            end

            cpu_state_exec: begin
                reg_out <= branch_address_sum;
                if ((TWO_CYCLE_ALU || TWO_CYCLE_COMPARE) && (alu_wait || alu_wait_2)) begin
                    mem_do_rinst <= mem_do_prefetch && !alu_wait_2;
                    alu_wait <= alu_wait_2;
                end else
                if (frontend_o_response.is_beq_bne_blt_bge_bltu_bgeu) begin
                    latched_rd <= 0;
                    latched_store <= TWO_CYCLE_COMPARE ? alu_out_0_q : alu_out_0;
                    latched_branch <= TWO_CYCLE_COMPARE ? alu_out_0_q : alu_out_0;
                    if (frontend_o_response.mem_done)
                        cpu_state <= cpu_state_fetch;
                    if (TWO_CYCLE_COMPARE ? alu_out_0_q : alu_out_0) begin
                        decoder_trigger <= 0;
                        set_mem_do_rinst = 1;
                    end
                end else begin
                    latched_branch <= frontend_o_response.instr_jalr;
                    latched_store <= 1;
                    latched_stalu <= 1;
                    cpu_state <= cpu_state_fetch;
                end
            end

            cpu_state_shift: begin
                latched_store <= 1;
                if (reg_sh == 0) begin
                    reg_out <= reg_op1;
                    mem_do_rinst <= mem_do_prefetch;
                    cpu_state <= cpu_state_fetch;
                end else if (TWO_STAGE_SHIFT && reg_sh >= 4) begin
                    (* parallel_case, full_case *)
                    case (1'b1)
                        frontend_o_response.instr_slli || frontend_o_response.instr_sll: reg_op1 <= reg_op1 << 4;
                        frontend_o_response.instr_srli || frontend_o_response.instr_srl: reg_op1 <= reg_op1 >> 4;
                        frontend_o_response.instr_srai || frontend_o_response.instr_sra: reg_op1 <= $signed(reg_op1) >>> 4;
                    endcase
                    reg_sh <= reg_sh - 4;
                end else begin
                    (* parallel_case, full_case *)
                    case (1'b1)
                        frontend_o_response.instr_slli || frontend_o_response.instr_sll: reg_op1 <= reg_op1 << 1;
                        frontend_o_response.instr_srli || frontend_o_response.instr_srl: reg_op1 <= reg_op1 >> 1;
                        frontend_o_response.instr_srai || frontend_o_response.instr_sra: reg_op1 <= $signed(reg_op1) >>> 1;
                    endcase
                    reg_sh <= reg_sh - 1;
                end
            end

            cpu_state_stmem: begin
                if (ENABLE_TRACE)
                    reg_out <= reg_op2;
                if (!mem_do_prefetch || frontend_o_response.mem_done) begin
                    if (!mem_do_wdata) begin
                        (* parallel_case, full_case *)
                        case (1'b1)
                            frontend_o_response.instr_sb: mem_wordsize <= 2;
                            frontend_o_response.instr_sh: mem_wordsize <= 1;
                            frontend_o_response.instr_sw: mem_wordsize <= 0;
                        endcase
                        if (ENABLE_TRACE) begin
                            trace_valid <= 1;
                            trace_data <= (irq_active ? TRACE_IRQ : 0) | TRACE_ADDR | ((reg_op1 + frontend_o_response.decoded_imm) & 32'hffffffff);
                        end
                        reg_op1 <= memory_address_sum;
                        set_mem_do_wdata = 1;
                    end
                    if (!mem_do_prefetch && frontend_o_response.mem_done) begin
                        cpu_state <= cpu_state_fetch;
                        decoder_trigger <= 1;
                        decoder_pseudo_trigger <= 1;
                    end
                end
            end

            cpu_state_ldmem: begin
                latched_store <= 1;
                if (!mem_do_prefetch || frontend_o_response.mem_done) begin
                    if (!mem_do_rdata) begin
                        (* parallel_case, full_case *)
                        case (1'b1)
                            frontend_o_response.instr_lb || frontend_o_response.instr_lbu: mem_wordsize <= 2;
                            frontend_o_response.instr_lh || frontend_o_response.instr_lhu: mem_wordsize <= 1;
                            frontend_o_response.instr_lw: mem_wordsize <= 0;
                        endcase
                        latched_is_lu <= frontend_o_response.is_lbu_lhu_lw;
                        latched_is_lh <= frontend_o_response.instr_lh;
                        latched_is_lb <= frontend_o_response.instr_lb;
                        if (ENABLE_TRACE) begin
                            trace_valid <= 1;
                            trace_data <= (irq_active ? TRACE_IRQ : 0) | TRACE_ADDR | ((reg_op1 + frontend_o_response.decoded_imm) & 32'hffffffff);
                        end
                        reg_op1 <= memory_address_sum;
                        set_mem_do_rdata = 1;
                    end
                    if (!mem_do_prefetch && frontend_o_response.mem_done) begin
                        (* parallel_case, full_case *)
                        case (1'b1)
                            latched_is_lu: reg_out <= frontend_o_response.mem_rdata_word;
                            latched_is_lh: reg_out <= $signed(frontend_o_response.mem_rdata_word[15:0]);
                            latched_is_lb: reg_out <= $signed(frontend_o_response.mem_rdata_word[7:0]);
                        endcase
                        decoder_trigger <= 1;
                        decoder_pseudo_trigger <= 1;
                        cpu_state <= cpu_state_fetch;
                    end
                end
            end
        endcase

        if (ENABLE_IRQ) begin
            next_irq_pending = next_irq_pending | irq;
            if(ENABLE_IRQ_TIMER && timer)
                if (timer - 1 == 0)
                    next_irq_pending[irq_timer] = 1;
        end

        if (CATCH_MISALIGN && resetn && (mem_do_rdata || mem_do_wdata)) begin
            if (mem_wordsize == 0 && reg_op1[1:0] != 0) begin
                `debug($display("MISALIGNED WORD: 0x%08x", reg_op1);)
                if (ENABLE_IRQ && !irq_mask[irq_buserror] && !irq_active) begin
                    next_irq_pending[irq_buserror] = 1;
                end else
                    cpu_state <= cpu_state_trap;
            end
            if (mem_wordsize == 1 && reg_op1[0] != 0) begin
                `debug($display("MISALIGNED HALFWORD: 0x%08x", reg_op1);)
                if (ENABLE_IRQ && !irq_mask[irq_buserror] && !irq_active) begin
                    next_irq_pending[irq_buserror] = 1;
                end else
                    cpu_state <= cpu_state_trap;
            end
        end
        if (CATCH_MISALIGN && resetn && mem_do_rinst && (COMPRESSED_ISA ? reg_pc[0] : |reg_pc[1:0])) begin
            `debug($display("MISALIGNED INSTRUCTION: 0x%08x", reg_pc);)
            if (ENABLE_IRQ && !irq_mask[irq_buserror] && !irq_active) begin
                next_irq_pending[irq_buserror] = 1;
            end else
                cpu_state <= cpu_state_trap;
        end
        if (!CATCH_ILLINSN && decoder_trigger_q && !decoder_pseudo_trigger_q && frontend_o_response.instr_ecall_ebreak) begin
            cpu_state <= cpu_state_trap;
        end

        if (!resetn || frontend_o_response.mem_done) begin
            mem_do_prefetch <= 0;
            mem_do_rinst <= 0;
            mem_do_rdata <= 0;
            mem_do_wdata <= 0;
        end

        if (set_mem_do_rinst)
            mem_do_rinst <= 1;
        if (set_mem_do_rdata)
            mem_do_rdata <= 1;
        if (set_mem_do_wdata)
            mem_do_wdata <= 1;

        irq_pending <= next_irq_pending & ~MASKED_IRQ;

        if (!CATCH_MISALIGN) begin
            if (COMPRESSED_ISA) begin
                reg_pc[0] <= 0;
                reg_next_pc[0] <= 0;
            end else begin
                reg_pc[1:0] <= 0;
                reg_next_pc[1:0] <= 0;
            end
        end
        current_pc = 'bx;
    end

`ifdef RISCV_FORMAL
    reg dbg_irq_call;
    reg dbg_irq_enter;
    reg [31:0] dbg_irq_ret;
    always @(posedge clk) begin
        rvfi_valid <= resetn && (launch_next_insn || trap) && frontend_o_response.dbg_valid_insn;
        rvfi_order <= resetn ? rvfi_order + rvfi_valid : 0;

        rvfi_insn <= frontend_o_response.dbg_insn_opcode;
        rvfi_rs1_addr <= dbg_rs1val_valid ? frontend_o_response.dbg_insn_rs1 : 0;
        rvfi_rs2_addr <= dbg_rs2val_valid ? frontend_o_response.dbg_insn_rs2 : 0;
        rvfi_pc_rdata <= frontend_o_response.dbg_insn_addr;
        rvfi_rs1_rdata <= dbg_rs1val_valid ? dbg_rs1val : 0;
        rvfi_rs2_rdata <= dbg_rs2val_valid ? dbg_rs2val : 0;
        rvfi_trap <= trap;
        rvfi_halt <= trap;
        rvfi_intr <= dbg_irq_enter;
        rvfi_mode <= 3;
        rvfi_ixl <= 1;

        if (!resetn) begin
            dbg_irq_call <= 0;
            dbg_irq_enter <= 0;
        end else
        if (rvfi_valid) begin
            dbg_irq_call <= 0;
            dbg_irq_enter <= dbg_irq_call;
        end else
        if (irq_state == 1) begin
            dbg_irq_call <= 1;
            dbg_irq_ret <= next_pc;
        end

        if (!resetn) begin
            rvfi_rd_addr <= 0;
            rvfi_rd_wdata <= 0;
        end else
        if (cpuregs_write && !irq_state) begin
`ifdef PICORV32_TESTBUG_003
            rvfi_rd_addr <= latched_rd ^ 1;
`else
            rvfi_rd_addr <= latched_rd;
`endif
`ifdef PICORV32_TESTBUG_004
            rvfi_rd_wdata <= latched_rd ? cpuregs_wrdata ^ 1 : 0;
`else
            rvfi_rd_wdata <= latched_rd ? cpuregs_wrdata : 0;
`endif
        end else
        if (rvfi_valid) begin
            rvfi_rd_addr <= 0;
            rvfi_rd_wdata <= 0;
        end

        casez (frontend_o_response.dbg_insn_opcode)
            32'b 0000000_?????_000??_???_?????_0001011: begin // getq
                rvfi_rs1_addr <= 0;
                rvfi_rs1_rdata <= 0;
            end
            32'b 0000001_?????_?????_???_000??_0001011: begin // setq
                rvfi_rd_addr <= 0;
                rvfi_rd_wdata <= 0;
            end
            32'b 0000010_?????_00000_???_00000_0001011: begin // retirq
                rvfi_rs1_addr <= 0;
                rvfi_rs1_rdata <= 0;
            end
        endcase

        if (!dbg_irq_call) begin
            if (dbg_mem_instr) begin
                rvfi_mem_addr <= 0;
                rvfi_mem_rmask <= 0;
                rvfi_mem_wmask <= 0;
                rvfi_mem_rdata <= 0;
                rvfi_mem_wdata <= 0;
            end else
            if (dbg_mem_valid && dbg_mem_ready) begin
                rvfi_mem_addr <= dbg_mem_addr;
                rvfi_mem_rmask <= dbg_mem_wstrb ? 0 : ~0;
                rvfi_mem_wmask <= dbg_mem_wstrb;
                rvfi_mem_rdata <= dbg_mem_rdata;
                rvfi_mem_wdata <= dbg_mem_wdata;
            end
        end
    end

    always @* begin
`ifdef PICORV32_TESTBUG_005
        rvfi_pc_wdata = (dbg_irq_call ? dbg_irq_ret : frontend_o_response.dbg_insn_addr) ^ 4;
`else
        rvfi_pc_wdata = dbg_irq_call ? dbg_irq_ret : frontend_o_response.dbg_insn_addr;
`endif

        rvfi_csr_mcycle_rmask = 0;
        rvfi_csr_mcycle_wmask = 0;
        rvfi_csr_mcycle_rdata = 0;
        rvfi_csr_mcycle_wdata = 0;

        rvfi_csr_minstret_rmask = 0;
        rvfi_csr_minstret_wmask = 0;
        rvfi_csr_minstret_rdata = 0;
        rvfi_csr_minstret_wdata = 0;

        if (rvfi_valid && rvfi_insn[6:0] == 7'b 1110011 && rvfi_insn[13:12] == 3'b010) begin
            if (rvfi_insn[31:20] == 12'h C00) begin
                rvfi_csr_mcycle_rmask = 64'h 0000_0000_FFFF_FFFF;
                rvfi_csr_mcycle_rdata = {32'h 0000_0000, rvfi_rd_wdata};
            end
            if (rvfi_insn[31:20] == 12'h C80) begin
                rvfi_csr_mcycle_rmask = 64'h FFFF_FFFF_0000_0000;
                rvfi_csr_mcycle_rdata = {rvfi_rd_wdata, 32'h 0000_0000};
            end
            if (rvfi_insn[31:20] == 12'h C02) begin
                rvfi_csr_minstret_rmask = 64'h 0000_0000_FFFF_FFFF;
                rvfi_csr_minstret_rdata = {32'h 0000_0000, rvfi_rd_wdata};
            end
            if (rvfi_insn[31:20] == 12'h C82) begin
                rvfi_csr_minstret_rmask = 64'h FFFF_FFFF_0000_0000;
                rvfi_csr_minstret_rdata = {rvfi_rd_wdata, 32'h 0000_0000};
            end
        end
    end
`endif

    // Formal Verification
`ifdef FORMAL
    reg [3:0] last_mem_nowait;
    always @(posedge clk)
        last_mem_nowait <= {last_mem_nowait, mem_ready || !mem_valid};

    // stall the memory interface for max 4 cycles
    restrict property (|last_mem_nowait || mem_ready || !mem_valid);

    // resetn low in first cycle, after that resetn high
    restrict property (resetn != $initstate);

    // this just makes it much easier to read traces. uncomment as needed.
    // assume property (mem_valid || !mem_ready);

    reg ok;
    always @* begin
        if (resetn) begin
            // instruction fetches are read-only
            if (mem_valid && mem_instr)
                assert (mem_wstrb == 0);

            // cpu_state must be valid
            ok = 0;
            if (cpu_state == cpu_state_trap)   ok = 1;
            if (cpu_state == cpu_state_fetch)  ok = 1;
            if (cpu_state == cpu_state_ld_rs1) ok = 1;
            if (cpu_state == cpu_state_ld_rs2) ok = !ENABLE_REGS_DUALPORT;
            if (cpu_state == cpu_state_exec)   ok = 1;
            if (cpu_state == cpu_state_shift)  ok = 1;
            if (cpu_state == cpu_state_stmem)  ok = 1;
            if (cpu_state == cpu_state_ldmem)  ok = 1;
            assert (ok);
        end
    end

    reg last_mem_la_read = 0;
    reg last_mem_la_write = 0;
    reg [31:0] last_mem_la_addr;
    reg [31:0] last_mem_la_wdata;
    reg [3:0] last_mem_la_wstrb = 0;

    always @(posedge clk) begin
        last_mem_la_read <= mem_la_read;
        last_mem_la_write <= mem_la_write;
        last_mem_la_addr <= mem_la_addr;
        last_mem_la_wdata <= mem_la_wdata;
        last_mem_la_wstrb <= mem_la_wstrb;

        if (last_mem_la_read) begin
            assert(mem_valid);
            assert(mem_addr == last_mem_la_addr);
            assert(mem_wstrb == 0);
        end
        if (last_mem_la_write) begin
            assert(mem_valid);
            assert(mem_addr == last_mem_la_addr);
            assert(mem_wdata == last_mem_la_wdata);
            assert(mem_wstrb == last_mem_la_wstrb);
        end
        if (mem_la_read || mem_la_write) begin
            assert(!mem_valid || mem_ready);
        end
    end
`endif

    assign mem_valid = frontend_o_response.mem_valid;
    assign mem_instr = frontend_o_response.mem_instr;
    assign mem_addr = frontend_o_response.mem_addr;
    assign mem_wdata = frontend_o_response.mem_wdata;
    assign mem_wstrb = frontend_o_response.mem_wstrb;
    assign mem_la_read = frontend_o_response.mem_la_read;
    assign mem_la_write = frontend_o_response.mem_la_write;
    assign mem_la_addr = frontend_o_response.mem_la_addr;
    assign mem_la_wdata = frontend_o_response.mem_la_wdata;
    assign mem_la_wstrb = frontend_o_response.mem_la_wstrb;
    assign pcpi_insn = frontend_o_response.pcpi_insn;
endmodule

`default_nettype wire
