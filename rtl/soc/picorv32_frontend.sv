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

// 处理器前端：接受主控制器的取指、预取和访存请求，管理存储握手、压缩指令拼接与译码状态。
// 存储响应在原有接收边沿保存，详细译码与执行记录沿用主控制器给出的周期使能。
`timescale 1 ns / 1 ps
`default_nettype none
`ifdef FORMAL
`define PICORV32_FRONT_ASSERT(condition) assert(condition)
`define PICORV32_FRONT_KEEP (* keep *)
`else
`define PICORV32_FRONT_ASSERT(condition) empty_statement
`ifdef DEBUGNETS
`define PICORV32_FRONT_KEEP (* keep *)
`else
`define PICORV32_FRONT_KEEP
`endif
`endif

module picorv32_frontend #(
    parameter logic LATCHED_MEM_RDATA = 1'b0,
    parameter logic COMPRESSED_ISA = 1'b0,
    parameter logic CATCH_ILLINSN = 1'b1,
    parameter logic ENABLE_COUNTERS = 1'b1,
    parameter logic ENABLE_COUNTERS64 = 1'b1,
    parameter logic ENABLE_REGS_16_31 = 1'b1,
    parameter logic ENABLE_IRQ = 1'b0,
    parameter logic ENABLE_IRQ_QREGS = 1'b1,
    parameter logic ENABLE_IRQ_TIMER = 1'b1,
    parameter logic WITH_PCPI = 1'b0
) (
    input  logic clk, // 模块工作时钟。
    input  logic rst_n, // 低电平有效的同步复位。
    input  picorv32_frontend_pkg::request_t i_request, // 主控制器的访存与译码请求。
    input  logic i_mem_ready, // 当前外部存储请求完成。
    input  logic [31:0] i_mem_rdata, // 当前外部存储读取数据。
    output picorv32_frontend_pkg::response_t o_response // 存储接口、译码结果和执行记录。
);
    //! 0. 参数与局部数据
    //! ---------------------

    localparam integer irqregs_offset = ENABLE_REGS_16_31 ? 32 : 16;
    localparam integer regindex_bits = (ENABLE_REGS_16_31 ? 5 : 4) + ENABLE_IRQ*ENABLE_IRQ_QREGS;
    logic mem_valid;
    logic mem_instr;
    logic [31:0] mem_addr;
    logic [31:0] mem_wdata;
    logic [3:0] mem_wstrb;
    logic mem_la_read;
    logic mem_la_write;
    logic [31:0] mem_la_addr;
    logic [31:0] mem_la_wdata;
    logic [3:0] mem_la_wstrb;
    logic [31:0] pcpi_insn;
    logic [31:0] next_insn_opcode;
    logic [31:0] dbg_insn_opcode;
    logic [31:0] dbg_insn_addr;
    logic [1:0] mem_state;
    logic [31:0] mem_rdata_word;
    logic [31:0] mem_rdata_q;
    logic mem_xfer;
    logic mem_la_secondword, mem_la_firstword_reg, last_mem_valid;
    logic mem_la_firstword;
    logic mem_la_firstword_xfer;
    logic prefetched_high_word;
    logic [15:0] mem_16bit_buffer;
    logic [31:0] mem_rdata_latched_noshuffle;
    logic [31:0] mem_rdata_latched;
    logic mem_la_use_prefetched_high_word;
    logic mem_busy;
    logic mem_done;
    logic instr_lui, instr_auipc, instr_jal, instr_jalr;
    logic instr_beq, instr_bne, instr_blt, instr_bge, instr_bltu, instr_bgeu;
    logic instr_lb, instr_lh, instr_lw, instr_lbu, instr_lhu, instr_sb, instr_sh, instr_sw;
    logic instr_addi, instr_slti, instr_sltiu, instr_xori, instr_ori, instr_andi, instr_slli, instr_srli, instr_srai;
    logic instr_add, instr_sub, instr_sll, instr_slt, instr_sltu, instr_xor, instr_srl, instr_sra, instr_or, instr_and;
    logic instr_rdcycle, instr_rdcycleh, instr_rdinstr, instr_rdinstrh, instr_ecall_ebreak, instr_fence;
    logic instr_getq, instr_setq, instr_retirq, instr_maskirq, instr_waitirq, instr_timer;
    logic instr_trap;
    logic [regindex_bits-1:0] decoded_rd, decoded_rs1;
    logic [4:0] decoded_rs2;
    logic [31:0] decoded_imm, decoded_imm_j;
    logic compressed_instr;
    logic is_lui_auipc_jal;
    logic is_lb_lh_lw_lbu_lhu;
    logic is_slli_srli_srai;
    logic is_jalr_addi_slti_sltiu_xori_ori_andi;
    logic is_sb_sh_sw;
    logic is_sll_srl_sra;
    logic is_lui_auipc_jal_jalr_addi_add_sub;
    logic is_slti_blt_slt;
    logic is_sltiu_bltu_sltu;
    logic is_beq_bne_blt_bge_bltu_bgeu;
    logic is_lbu_lhu_lw;
    logic is_alu_reg_imm;
    logic is_alu_reg_reg;
    logic is_compare;
    logic is_rdcycle_rdcycleh_rdinstr_rdinstrh;
    logic [63:0] new_ascii_instr;
    `PICORV32_FRONT_KEEP logic [63:0] dbg_ascii_instr;
    `PICORV32_FRONT_KEEP logic [31:0] dbg_insn_imm;
    `PICORV32_FRONT_KEEP logic [4:0] dbg_insn_rs1;
    `PICORV32_FRONT_KEEP logic [4:0] dbg_insn_rs2;
    `PICORV32_FRONT_KEEP logic [4:0] dbg_insn_rd;
    logic [63:0] q_ascii_instr;
    logic [31:0] q_insn_imm;
    logic [31:0] q_insn_opcode;
    logic [4:0] q_insn_rs1;
    logic [4:0] q_insn_rs2;
    logic [4:0] q_insn_rd;
    logic dbg_next;
    logic dbg_valid_insn;
    logic [63:0] cached_ascii_instr;
    logic [31:0] cached_insn_imm;
    logic [31:0] cached_insn_opcode;
    logic [4:0] cached_insn_rs1;
    logic [4:0] cached_insn_rs2;
    logic [4:0] cached_insn_rd;

    task empty_statement;
        begin end
    endtask
    //! 1. 存储请求与指令字处理
    //! ---------------------------

    assign mem_la_firstword = COMPRESSED_ISA && (i_request.mem_do_prefetch || i_request.mem_do_rinst) && i_request.next_pc[1] && !mem_la_secondword;
    assign mem_la_firstword_xfer = COMPRESSED_ISA && mem_xfer && (!last_mem_valid ? mem_la_firstword : mem_la_firstword_reg);

    assign mem_la_use_prefetched_high_word = COMPRESSED_ISA && mem_la_firstword && prefetched_high_word && !i_request.clear_prefetched_high_word;
    assign mem_xfer = (mem_valid && i_mem_ready) || (mem_la_use_prefetched_high_word && i_request.mem_do_rinst);

    assign mem_busy = |{i_request.mem_do_prefetch, i_request.mem_do_rinst, i_request.mem_do_rdata, i_request.mem_do_wdata};
    assign mem_done = rst_n && ((mem_xfer && |mem_state && (i_request.mem_do_rinst || i_request.mem_do_rdata || i_request.mem_do_wdata)) || (&mem_state && i_request.mem_do_rinst)) &&
            (!mem_la_firstword || (~&mem_rdata_latched[1:0] && mem_xfer));

    assign mem_la_write = rst_n && !(|mem_state) && i_request.mem_do_wdata;
    assign mem_la_read = rst_n && ((!mem_la_use_prefetched_high_word && !(|mem_state) && (i_request.mem_do_rinst || i_request.mem_do_prefetch || i_request.mem_do_rdata)) ||
            (COMPRESSED_ISA && mem_xfer && (!last_mem_valid ? mem_la_firstword : mem_la_firstword_reg) && !mem_la_secondword && &mem_rdata_latched[1:0]));
    assign mem_la_addr = (i_request.mem_do_prefetch || i_request.mem_do_rinst) ? {i_request.next_pc[31:2] + mem_la_firstword_xfer, 2'b00} : {i_request.reg_op1[31:2], 2'b00};

    assign mem_rdata_latched_noshuffle = (mem_xfer || LATCHED_MEM_RDATA) ? i_mem_rdata : mem_rdata_q;

    assign mem_rdata_latched = COMPRESSED_ISA && mem_la_use_prefetched_high_word ? {16'bx, mem_16bit_buffer} :
            COMPRESSED_ISA && mem_la_secondword ? {mem_rdata_latched_noshuffle[15:0], mem_16bit_buffer} :
            COMPRESSED_ISA && mem_la_firstword ? {16'bx, mem_rdata_latched_noshuffle[31:16]} : mem_rdata_latched_noshuffle;

    // 在外部存储等待期间保存半字位置，直到当前请求完成。
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            mem_la_firstword_reg <= 0;
            last_mem_valid <= 0;
        end else begin
            if (!last_mem_valid)
                mem_la_firstword_reg <= mem_la_firstword;
            last_mem_valid <= mem_valid && !i_mem_ready;
        end
    end

    // 依据字节地址和访问宽度生成字节使能，并选择返回数据。
    always_comb begin
        mem_la_wdata = 'x;
        mem_la_wstrb = 'x;
        mem_rdata_word = 'x;
        case (i_request.mem_wordsize)
            0: begin
                mem_la_wdata = i_request.reg_op2;
                mem_la_wstrb = 4'b1111;
                mem_rdata_word = i_mem_rdata;
            end
            1: begin
                mem_la_wdata = {2{i_request.reg_op2[15:0]}};
                mem_la_wstrb = i_request.reg_op1[1] ? 4'b1100 : 4'b0011;
                case (i_request.reg_op1[1])
                    1'b0: mem_rdata_word = {16'b0, i_mem_rdata[15: 0]};
                    1'b1: mem_rdata_word = {16'b0, i_mem_rdata[31:16]};
                endcase
            end
            2: begin
                mem_la_wdata = {4{i_request.reg_op2[7:0]}};
                mem_la_wstrb = 4'b0001 << i_request.reg_op1[1:0];
                case (i_request.reg_op1[1:0])
                    2'b00: mem_rdata_word = {24'b0, i_mem_rdata[ 7: 0]};
                    2'b01: mem_rdata_word = {24'b0, i_mem_rdata[15: 8]};
                    2'b10: mem_rdata_word = {24'b0, i_mem_rdata[23:16]};
                    2'b11: mem_rdata_word = {24'b0, i_mem_rdata[31:24]};
                endcase
            end
        endcase
    end

    // 接收存储数据后保存指令字，压缩指令在同一边沿补齐译码所需字段。
    always_ff @(posedge clk) begin
        if (mem_xfer) begin
            mem_rdata_q <= COMPRESSED_ISA ? mem_rdata_latched : i_mem_rdata;
            next_insn_opcode <= COMPRESSED_ISA ? mem_rdata_latched : i_mem_rdata;
        end

        if (COMPRESSED_ISA && mem_done && (i_request.mem_do_prefetch || i_request.mem_do_rinst)) begin
            case (mem_rdata_latched[1:0])
                2'b00: begin // Quadrant 0
                    case (mem_rdata_latched[15:13])
                        3'b000: begin // C.ADDI4SPN
                            mem_rdata_q[14:12] <= 3'b000;
                            mem_rdata_q[31:20] <= {2'b0, mem_rdata_latched[10:7], mem_rdata_latched[12:11], mem_rdata_latched[5], mem_rdata_latched[6], 2'b00};
                        end
                        3'b010: begin // C.LW
                            mem_rdata_q[31:20] <= {5'b0, mem_rdata_latched[5], mem_rdata_latched[12:10], mem_rdata_latched[6], 2'b00};
                            mem_rdata_q[14:12] <= 3'b 010;
                        end
                        3'b 110: begin // C.SW
                            {mem_rdata_q[31:25], mem_rdata_q[11:7]} <= {5'b0, mem_rdata_latched[5], mem_rdata_latched[12:10], mem_rdata_latched[6], 2'b00};
                            mem_rdata_q[14:12] <= 3'b 010;
                        end
                    endcase
                end
                2'b01: begin // Quadrant 1
                    case (mem_rdata_latched[15:13])
                        3'b 000: begin // C.ADDI
                            mem_rdata_q[14:12] <= 3'b000;
                            mem_rdata_q[31:20] <= 12'($signed({mem_rdata_latched[12], mem_rdata_latched[6:2]}));
                        end
                        3'b 010: begin // C.LI
                            mem_rdata_q[14:12] <= 3'b000;
                            mem_rdata_q[31:20] <= 12'($signed({mem_rdata_latched[12], mem_rdata_latched[6:2]}));
                        end
                        3'b 011: begin
                            if (mem_rdata_latched[11:7] == 2) begin // C.ADDI16SP
                                mem_rdata_q[14:12] <= 3'b000;
                                mem_rdata_q[31:20] <= 12'($signed({mem_rdata_latched[12], mem_rdata_latched[4:3],
                                        mem_rdata_latched[5], mem_rdata_latched[2], mem_rdata_latched[6], 4'b 0000}));
                            end else begin // C.LUI
                                mem_rdata_q[31:12] <= 20'($signed({mem_rdata_latched[12], mem_rdata_latched[6:2]}));
                            end
                        end
                        3'b100: begin
                            if (mem_rdata_latched[11:10] == 2'b00) begin // C.SRLI
                                mem_rdata_q[31:25] <= 7'b0000000;
                                mem_rdata_q[14:12] <= 3'b 101;
                            end
                            if (mem_rdata_latched[11:10] == 2'b01) begin // C.SRAI
                                mem_rdata_q[31:25] <= 7'b0100000;
                                mem_rdata_q[14:12] <= 3'b 101;
                            end
                            if (mem_rdata_latched[11:10] == 2'b10) begin // C.ANDI
                                mem_rdata_q[14:12] <= 3'b111;
                                mem_rdata_q[31:20] <= 12'($signed({mem_rdata_latched[12], mem_rdata_latched[6:2]}));
                            end
                            if (mem_rdata_latched[12:10] == 3'b011) begin // C.SUB, C.XOR, C.OR, C.AND
                                if (mem_rdata_latched[6:5] == 2'b00) mem_rdata_q[14:12] <= 3'b000;
                                if (mem_rdata_latched[6:5] == 2'b01) mem_rdata_q[14:12] <= 3'b100;
                                if (mem_rdata_latched[6:5] == 2'b10) mem_rdata_q[14:12] <= 3'b110;
                                if (mem_rdata_latched[6:5] == 2'b11) mem_rdata_q[14:12] <= 3'b111;
                                mem_rdata_q[31:25] <= mem_rdata_latched[6:5] == 2'b00 ? 7'b0100000 : 7'b0000000;
                            end
                        end
                        3'b 110: begin // C.BEQZ
                            mem_rdata_q[14:12] <= 3'b000;
                            { mem_rdata_q[31], mem_rdata_q[7], mem_rdata_q[30:25], mem_rdata_q[11:8] } <= 12'($signed({mem_rdata_latched[12], mem_rdata_latched[6:5], mem_rdata_latched[2],
                                            mem_rdata_latched[11:10], mem_rdata_latched[4:3]}));
                        end
                        3'b 111: begin // C.BNEZ
                            mem_rdata_q[14:12] <= 3'b001;
                            { mem_rdata_q[31], mem_rdata_q[7], mem_rdata_q[30:25], mem_rdata_q[11:8] } <= 12'($signed({mem_rdata_latched[12], mem_rdata_latched[6:5], mem_rdata_latched[2],
                                            mem_rdata_latched[11:10], mem_rdata_latched[4:3]}));
                        end
                    endcase
                end
                2'b10: begin // Quadrant 2
                    case (mem_rdata_latched[15:13])
                        3'b000: begin // C.SLLI
                            mem_rdata_q[31:25] <= 7'b0000000;
                            mem_rdata_q[14:12] <= 3'b 001;
                        end
                        3'b010: begin // C.LWSP
                            mem_rdata_q[31:20] <= {4'b0, mem_rdata_latched[3:2], mem_rdata_latched[12], mem_rdata_latched[6:4], 2'b00};
                            mem_rdata_q[14:12] <= 3'b 010;
                        end
                        3'b100: begin
                            if (mem_rdata_latched[12] == 0 && mem_rdata_latched[6:2] == 0) begin // C.JR
                                mem_rdata_q[14:12] <= 3'b000;
                                mem_rdata_q[31:20] <= 12'b0;
                            end
                            if (mem_rdata_latched[12] == 0 && mem_rdata_latched[6:2] != 0) begin // C.MV
                                mem_rdata_q[14:12] <= 3'b000;
                                mem_rdata_q[31:25] <= 7'b0000000;
                            end
                            if (mem_rdata_latched[12] != 0 && mem_rdata_latched[11:7] != 0 && mem_rdata_latched[6:2] == 0) begin // C.JALR
                                mem_rdata_q[14:12] <= 3'b000;
                                mem_rdata_q[31:20] <= 12'b0;
                            end
                            if (mem_rdata_latched[12] != 0 && mem_rdata_latched[6:2] != 0) begin // C.ADD
                                mem_rdata_q[14:12] <= 3'b000;
                                mem_rdata_q[31:25] <= 7'b0000000;
                            end
                        end
                        3'b110: begin // C.SWSP
                            {mem_rdata_q[31:25], mem_rdata_q[11:7]} <= {4'b0, mem_rdata_latched[8:7], mem_rdata_latched[12:9], 2'b00};
                            mem_rdata_q[14:12] <= 3'b 010;
                        end
                    endcase
                end
            endcase
        end
    end

    always_ff @(posedge clk) begin
        if (rst_n && !i_request.trap) begin
            if (i_request.mem_do_prefetch || i_request.mem_do_rinst || i_request.mem_do_rdata)
                `PICORV32_FRONT_ASSERT(!i_request.mem_do_wdata);

            if (i_request.mem_do_prefetch || i_request.mem_do_rinst)
                `PICORV32_FRONT_ASSERT(!i_request.mem_do_rdata);

            if (i_request.mem_do_rdata)
                `PICORV32_FRONT_ASSERT(!i_request.mem_do_prefetch && !i_request.mem_do_rinst);

            if (i_request.mem_do_wdata)
                `PICORV32_FRONT_ASSERT(!(i_request.mem_do_prefetch || i_request.mem_do_rinst || i_request.mem_do_rdata));

            if (mem_state == 2 || mem_state == 3)
                `PICORV32_FRONT_ASSERT(mem_valid || i_request.mem_do_prefetch);
        end
    end

    // 复位或异常结束当前请求，正常状态按预取、读取和写入阶段更新。
    always_ff @(posedge clk) begin
        if (!rst_n || i_request.trap) begin
            if (!rst_n)
                mem_state <= 0;
            if (!rst_n || i_mem_ready)
                mem_valid <= 0;
            mem_la_secondword <= 0;
            prefetched_high_word <= 0;
        end else begin
            if (mem_la_read || mem_la_write) begin
                mem_addr <= mem_la_addr;
                mem_wstrb <= mem_la_wstrb & {4{mem_la_write}};
            end
            if (mem_la_write) begin
                mem_wdata <= mem_la_wdata;
            end
            case (mem_state)
                0: begin
                    if (i_request.mem_do_prefetch || i_request.mem_do_rinst || i_request.mem_do_rdata) begin
                        mem_valid <= !mem_la_use_prefetched_high_word;
                        mem_instr <= i_request.mem_do_prefetch || i_request.mem_do_rinst;
                        mem_wstrb <= 0;
                        mem_state <= 1;
                    end
                    if (i_request.mem_do_wdata) begin
                        mem_valid <= 1;
                        mem_instr <= 0;
                        mem_state <= 2;
                    end
                end
                1: begin
                    `PICORV32_FRONT_ASSERT(mem_wstrb == 0);
                    `PICORV32_FRONT_ASSERT(i_request.mem_do_prefetch || i_request.mem_do_rinst || i_request.mem_do_rdata);
                    `PICORV32_FRONT_ASSERT(mem_valid == !mem_la_use_prefetched_high_word);
                    `PICORV32_FRONT_ASSERT(mem_instr == (i_request.mem_do_prefetch || i_request.mem_do_rinst));
                    if (mem_xfer) begin
                        if (COMPRESSED_ISA && mem_la_read) begin
                            mem_valid <= 1;
                            mem_la_secondword <= 1;
                            if (!mem_la_use_prefetched_high_word)
                                mem_16bit_buffer <= i_mem_rdata[31:16];
                        end else begin
                            mem_valid <= 0;
                            mem_la_secondword <= 0;
                            if (COMPRESSED_ISA && !i_request.mem_do_rdata) begin
                                if (~&i_mem_rdata[1:0] || mem_la_secondword) begin
                                    mem_16bit_buffer <= i_mem_rdata[31:16];
                                    prefetched_high_word <= 1;
                                end else begin
                                    prefetched_high_word <= 0;
                                end
                            end
                            mem_state <= i_request.mem_do_rinst || i_request.mem_do_rdata ? 0 : 3;
                        end
                    end
                end
                2: begin
                    `PICORV32_FRONT_ASSERT(mem_wstrb != 0);
                    `PICORV32_FRONT_ASSERT(i_request.mem_do_wdata);
                    if (mem_xfer) begin
                        mem_valid <= 0;
                        mem_state <= 0;
                    end
                end
                3: begin
                    `PICORV32_FRONT_ASSERT(mem_wstrb == 0);
                    `PICORV32_FRONT_ASSERT(i_request.mem_do_prefetch);
                    if (i_request.mem_do_rinst) begin
                        mem_state <= 0;
                    end
                end
            endcase
        end

        if (i_request.clear_prefetched_high_word)
            prefetched_high_word <= 0;
    end

    //! 2. 指令类别与操作数译码
    //! ---------------------------

    assign instr_trap = (CATCH_ILLINSN || WITH_PCPI) && ~|{instr_lui, instr_auipc, instr_jal, instr_jalr,
            instr_beq, instr_bne, instr_blt, instr_bge, instr_bltu, instr_bgeu,
            instr_lb, instr_lh, instr_lw, instr_lbu, instr_lhu, instr_sb, instr_sh, instr_sw,
            instr_addi, instr_slti, instr_sltiu, instr_xori, instr_ori, instr_andi, instr_slli, instr_srli, instr_srai,
            instr_add, instr_sub, instr_sll, instr_slt, instr_sltu, instr_xor, instr_srl, instr_sra, instr_or, instr_and,
            instr_rdcycle, instr_rdcycleh, instr_rdinstr, instr_rdinstrh, instr_fence,
            instr_getq, instr_setq, instr_retirq, instr_maskirq, instr_waitirq, instr_timer};

    assign is_rdcycle_rdcycleh_rdinstr_rdinstrh = |{instr_rdcycle, instr_rdcycleh, instr_rdinstr, instr_rdinstrh};

    always_comb begin
        new_ascii_instr = "";

        if (instr_lui)      new_ascii_instr = "lui";
        if (instr_auipc)    new_ascii_instr = "auipc";
        if (instr_jal)      new_ascii_instr = "jal";
        if (instr_jalr)     new_ascii_instr = "jalr";

        if (instr_beq)      new_ascii_instr = "beq";
        if (instr_bne)      new_ascii_instr = "bne";
        if (instr_blt)      new_ascii_instr = "blt";
        if (instr_bge)      new_ascii_instr = "bge";
        if (instr_bltu)     new_ascii_instr = "bltu";
        if (instr_bgeu)     new_ascii_instr = "bgeu";

        if (instr_lb)       new_ascii_instr = "lb";
        if (instr_lh)       new_ascii_instr = "lh";
        if (instr_lw)       new_ascii_instr = "lw";
        if (instr_lbu)      new_ascii_instr = "lbu";
        if (instr_lhu)      new_ascii_instr = "lhu";
        if (instr_sb)       new_ascii_instr = "sb";
        if (instr_sh)       new_ascii_instr = "sh";
        if (instr_sw)       new_ascii_instr = "sw";

        if (instr_addi)     new_ascii_instr = "addi";
        if (instr_slti)     new_ascii_instr = "slti";
        if (instr_sltiu)    new_ascii_instr = "sltiu";
        if (instr_xori)     new_ascii_instr = "xori";
        if (instr_ori)      new_ascii_instr = "ori";
        if (instr_andi)     new_ascii_instr = "andi";
        if (instr_slli)     new_ascii_instr = "slli";
        if (instr_srli)     new_ascii_instr = "srli";
        if (instr_srai)     new_ascii_instr = "srai";

        if (instr_add)      new_ascii_instr = "add";
        if (instr_sub)      new_ascii_instr = "sub";
        if (instr_sll)      new_ascii_instr = "sll";
        if (instr_slt)      new_ascii_instr = "slt";
        if (instr_sltu)     new_ascii_instr = "sltu";
        if (instr_xor)      new_ascii_instr = "xor";
        if (instr_srl)      new_ascii_instr = "srl";
        if (instr_sra)      new_ascii_instr = "sra";
        if (instr_or)       new_ascii_instr = "or";
        if (instr_and)      new_ascii_instr = "and";

        if (instr_rdcycle)  new_ascii_instr = "rdcycle";
        if (instr_rdcycleh) new_ascii_instr = "rdcycleh";
        if (instr_rdinstr)  new_ascii_instr = "rdinstr";
        if (instr_rdinstrh) new_ascii_instr = "rdinstrh";
        if (instr_fence)    new_ascii_instr = "fence";

        if (instr_getq)     new_ascii_instr = "getq";
        if (instr_setq)     new_ascii_instr = "setq";
        if (instr_retirq)   new_ascii_instr = "retirq";
        if (instr_maskirq)  new_ascii_instr = "maskirq";
        if (instr_waitirq)  new_ascii_instr = "waitirq";
        if (instr_timer)    new_ascii_instr = "timer";
    end

    // 执行记录与指令开始事件同步保存，伪译码请求复用已保存字段。
    always_ff @(posedge clk) begin
        q_ascii_instr <= dbg_ascii_instr;
        q_insn_imm <= dbg_insn_imm;
        q_insn_opcode <= dbg_insn_opcode;
        q_insn_rs1 <= dbg_insn_rs1;
        q_insn_rs2 <= dbg_insn_rs2;
        q_insn_rd <= dbg_insn_rd;
        dbg_next <= i_request.launch_next_insn;

        if (!rst_n || i_request.trap)
            dbg_valid_insn <= 0;
        else if (i_request.launch_next_insn)
            dbg_valid_insn <= 1;

        if (i_request.decoder_trigger_q) begin
            cached_ascii_instr <= new_ascii_instr;
            cached_insn_imm <= decoded_imm;
            if (&next_insn_opcode[1:0])
                cached_insn_opcode <= next_insn_opcode;
            else
                cached_insn_opcode <= {16'b0, next_insn_opcode[15:0]};
            cached_insn_rs1 <= decoded_rs1;
            cached_insn_rs2 <= decoded_rs2;
            cached_insn_rd <= decoded_rd;
        end

        if (i_request.launch_next_insn) begin
            dbg_insn_addr <= i_request.next_pc;
        end
    end

    always_comb begin
        dbg_ascii_instr = q_ascii_instr;
        dbg_insn_imm = q_insn_imm;
        dbg_insn_opcode = q_insn_opcode;
        dbg_insn_rs1 = q_insn_rs1;
        dbg_insn_rs2 = q_insn_rs2;
        dbg_insn_rd = q_insn_rd;

        if (dbg_next) begin
            if (i_request.decoder_pseudo_trigger_q) begin
                dbg_ascii_instr = cached_ascii_instr;
                dbg_insn_imm = cached_insn_imm;
                dbg_insn_opcode = cached_insn_opcode;
                dbg_insn_rs1 = cached_insn_rs1;
                dbg_insn_rs2 = cached_insn_rs2;
                dbg_insn_rd = cached_insn_rd;
            end else begin
                dbg_ascii_instr = new_ascii_instr;
                if (&next_insn_opcode[1:0])
                    dbg_insn_opcode = next_insn_opcode;
                else
                    dbg_insn_opcode = {16'b0, next_insn_opcode[15:0]};
                dbg_insn_imm = decoded_imm;
                dbg_insn_rs1 = decoded_rs1;
                dbg_insn_rs2 = decoded_rs2;
                dbg_insn_rd = decoded_rd;
            end
        end
    end

`ifdef DEBUGASM
    always_ff @(posedge clk) begin
        if (dbg_next) begin
            $display("debugasm %x %x %s", dbg_insn_addr, dbg_insn_opcode, dbg_ascii_instr ? dbg_ascii_instr : "*");
        end
    end
`endif

`ifdef DEBUG
    always_ff @(posedge clk) begin
        if (dbg_next) begin
            if (&dbg_insn_opcode[1:0])
                $display("DECODE: 0x%08x 0x%08x %-0s", dbg_insn_addr, dbg_insn_opcode, dbg_ascii_instr ? dbg_ascii_instr : "UNKNOWN");
            else
                $display("DECODE: 0x%08x     0x%04x %-0s", dbg_insn_addr, dbg_insn_opcode[15:0], dbg_ascii_instr ? dbg_ascii_instr : "UNKNOWN");
        end
    end
`endif

    // 读取完成时保存初级译码，译码使能有效时保存详细指令和立即数。
    always_ff @(posedge clk) begin
        is_lui_auipc_jal <= |{instr_lui, instr_auipc, instr_jal};
        is_lui_auipc_jal_jalr_addi_add_sub <= |{instr_lui, instr_auipc, instr_jal, instr_jalr, instr_addi, instr_add, instr_sub};
        is_slti_blt_slt <= |{instr_slti, instr_blt, instr_slt};
        is_sltiu_bltu_sltu <= |{instr_sltiu, instr_bltu, instr_sltu};
        is_lbu_lhu_lw <= |{instr_lbu, instr_lhu, instr_lw};
        is_compare <= |{is_beq_bne_blt_bge_bltu_bgeu, instr_slti, instr_slt, instr_sltiu, instr_sltu};

        if (i_request.mem_do_rinst && mem_done) begin
            instr_lui     <= mem_rdata_latched[6:0] == 7'b0110111;
            instr_auipc   <= mem_rdata_latched[6:0] == 7'b0010111;
            instr_jal     <= mem_rdata_latched[6:0] == 7'b1101111;
            instr_jalr    <= mem_rdata_latched[6:0] == 7'b1100111 && mem_rdata_latched[14:12] == 3'b000;
            instr_retirq  <= mem_rdata_latched[6:0] == 7'b0001011 && mem_rdata_latched[31:25] == 7'b0000010 && ENABLE_IRQ;
            instr_waitirq <= mem_rdata_latched[6:0] == 7'b0001011 && mem_rdata_latched[31:25] == 7'b0000100 && ENABLE_IRQ;

            is_beq_bne_blt_bge_bltu_bgeu <= mem_rdata_latched[6:0] == 7'b1100011;
            is_lb_lh_lw_lbu_lhu          <= mem_rdata_latched[6:0] == 7'b0000011;
            is_sb_sh_sw                  <= mem_rdata_latched[6:0] == 7'b0100011;
            is_alu_reg_imm               <= mem_rdata_latched[6:0] == 7'b0010011;
            is_alu_reg_reg               <= mem_rdata_latched[6:0] == 7'b0110011;

            { decoded_imm_j[31:20], decoded_imm_j[10:1], decoded_imm_j[11], decoded_imm_j[19:12], decoded_imm_j[0] } <= 32'($signed({mem_rdata_latched[31:12], 1'b0}));

            decoded_rd <= regindex_bits'(mem_rdata_latched[11:7]);
            decoded_rs1 <= regindex_bits'(mem_rdata_latched[19:15]);
            decoded_rs2 <= 5'(mem_rdata_latched[24:20]);

            if (mem_rdata_latched[6:0] == 7'b0001011 && mem_rdata_latched[31:25] == 7'b0000000 && ENABLE_IRQ && ENABLE_IRQ_QREGS)
                decoded_rs1[regindex_bits-1] <= 1; // instr_getq

            if (mem_rdata_latched[6:0] == 7'b0001011 && mem_rdata_latched[31:25] == 7'b0000010 && ENABLE_IRQ)
                decoded_rs1 <= regindex_bits'(ENABLE_IRQ_QREGS ? irqregs_offset : 3); // instr_retirq

            compressed_instr <= 0;
            if (COMPRESSED_ISA && mem_rdata_latched[1:0] != 2'b11) begin
                compressed_instr <= 1;
                decoded_rd <= regindex_bits'(0);
                decoded_rs1 <= regindex_bits'(0);
                decoded_rs2 <= 5'(0);

                { decoded_imm_j[31:11], decoded_imm_j[4], decoded_imm_j[9:8], decoded_imm_j[10], decoded_imm_j[6],
                  decoded_imm_j[7], decoded_imm_j[3:1], decoded_imm_j[5], decoded_imm_j[0] } <= 32'($signed({mem_rdata_latched[12:2], 1'b0}));

                case (mem_rdata_latched[1:0])
                    2'b00: begin // Quadrant 0
                        case (mem_rdata_latched[15:13])
                            3'b000: begin // C.ADDI4SPN
                                is_alu_reg_imm <= |mem_rdata_latched[12:5];
                                decoded_rs1 <= regindex_bits'(2);
                                decoded_rd <= regindex_bits'(5'd8 + 5'(mem_rdata_latched[4:2]));
                            end
                            3'b010: begin // C.LW
                                is_lb_lh_lw_lbu_lhu <= 1;
                                decoded_rs1 <= regindex_bits'(5'd8 + 5'(mem_rdata_latched[9:7]));
                                decoded_rd <= regindex_bits'(5'd8 + 5'(mem_rdata_latched[4:2]));
                            end
                            3'b110: begin // C.SW
                                is_sb_sh_sw <= 1;
                                decoded_rs1 <= regindex_bits'(5'd8 + 5'(mem_rdata_latched[9:7]));
                                decoded_rs2 <= 5'(5'd8 + 5'(mem_rdata_latched[4:2]));
                            end
                        endcase
                    end
                    2'b01: begin // Quadrant 1
                        case (mem_rdata_latched[15:13])
                            3'b000: begin // C.NOP / C.ADDI
                                is_alu_reg_imm <= 1;
                                decoded_rd <= regindex_bits'(mem_rdata_latched[11:7]);
                                decoded_rs1 <= regindex_bits'(mem_rdata_latched[11:7]);
                            end
                            3'b001: begin // C.JAL
                                instr_jal <= 1;
                                decoded_rd <= regindex_bits'(1);
                            end
                            3'b 010: begin // C.LI
                                is_alu_reg_imm <= 1;
                                decoded_rd <= regindex_bits'(mem_rdata_latched[11:7]);
                                decoded_rs1 <= regindex_bits'(0);
                            end
                            3'b 011: begin
                                if (mem_rdata_latched[12] || (|mem_rdata_latched[6:2])) begin
                                    if (mem_rdata_latched[11:7] == 2) begin // C.ADDI16SP
                                        is_alu_reg_imm <= 1;
                                        decoded_rd <= regindex_bits'(mem_rdata_latched[11:7]);
                                        decoded_rs1 <= regindex_bits'(mem_rdata_latched[11:7]);
                                    end else begin // C.LUI
                                        instr_lui <= 1;
                                        decoded_rd <= regindex_bits'(mem_rdata_latched[11:7]);
                                        decoded_rs1 <= regindex_bits'(0);
                                    end
                                end
                            end
                            3'b100: begin
                                if (!mem_rdata_latched[11] && !mem_rdata_latched[12]) begin // C.SRLI, C.SRAI
                                    is_alu_reg_imm <= 1;
                                    decoded_rd <= regindex_bits'(5'd8 + 5'(mem_rdata_latched[9:7]));
                                    decoded_rs1 <= regindex_bits'(5'd8 + 5'(mem_rdata_latched[9:7]));
                                    decoded_rs2 <= 5'({mem_rdata_latched[12], mem_rdata_latched[6:2]});
                                end
                                if (mem_rdata_latched[11:10] == 2'b10) begin // C.ANDI
                                    is_alu_reg_imm <= 1;
                                    decoded_rd <= regindex_bits'(5'd8 + 5'(mem_rdata_latched[9:7]));
                                    decoded_rs1 <= regindex_bits'(5'd8 + 5'(mem_rdata_latched[9:7]));
                                end
                                if (mem_rdata_latched[12:10] == 3'b011) begin // C.SUB, C.XOR, C.OR, C.AND
                                    is_alu_reg_reg <= 1;
                                    decoded_rd <= regindex_bits'(5'd8 + 5'(mem_rdata_latched[9:7]));
                                    decoded_rs1 <= regindex_bits'(5'd8 + 5'(mem_rdata_latched[9:7]));
                                    decoded_rs2 <= 5'(5'd8 + 5'(mem_rdata_latched[4:2]));
                                end
                            end
                            3'b101: begin // C.J
                                instr_jal <= 1;
                            end
                            3'b110: begin // C.BEQZ
                                is_beq_bne_blt_bge_bltu_bgeu <= 1;
                                decoded_rs1 <= regindex_bits'(5'd8 + 5'(mem_rdata_latched[9:7]));
                                decoded_rs2 <= 5'(0);
                            end
                            3'b111: begin // C.BNEZ
                                is_beq_bne_blt_bge_bltu_bgeu <= 1;
                                decoded_rs1 <= regindex_bits'(5'd8 + 5'(mem_rdata_latched[9:7]));
                                decoded_rs2 <= 5'(0);
                            end
                        endcase
                    end
                    2'b10: begin // Quadrant 2
                        case (mem_rdata_latched[15:13])
                            3'b000: begin // C.SLLI
                                if (!mem_rdata_latched[12]) begin
                                    is_alu_reg_imm <= 1;
                                    decoded_rd <= regindex_bits'(mem_rdata_latched[11:7]);
                                    decoded_rs1 <= regindex_bits'(mem_rdata_latched[11:7]);
                                    decoded_rs2 <= 5'({mem_rdata_latched[12], mem_rdata_latched[6:2]});
                                end
                            end
                            3'b010: begin // C.LWSP
                                if (|mem_rdata_latched[11:7]) begin
                                    is_lb_lh_lw_lbu_lhu <= 1;
                                    decoded_rd <= regindex_bits'(mem_rdata_latched[11:7]);
                                    decoded_rs1 <= regindex_bits'(2);
                                end
                            end
                            3'b100: begin
                                if (mem_rdata_latched[12] == 0 && mem_rdata_latched[11:7] != 0 && mem_rdata_latched[6:2] == 0) begin // C.JR
                                    instr_jalr <= 1;
                                    decoded_rd <= regindex_bits'(0);
                                    decoded_rs1 <= regindex_bits'(mem_rdata_latched[11:7]);
                                end
                                if (mem_rdata_latched[12] == 0 && mem_rdata_latched[6:2] != 0) begin // C.MV
                                    is_alu_reg_reg <= 1;
                                    decoded_rd <= regindex_bits'(mem_rdata_latched[11:7]);
                                    decoded_rs1 <= regindex_bits'(0);
                                    decoded_rs2 <= 5'(mem_rdata_latched[6:2]);
                                end
                                if (mem_rdata_latched[12] != 0 && mem_rdata_latched[11:7] != 0 && mem_rdata_latched[6:2] == 0) begin // C.JALR
                                    instr_jalr <= 1;
                                    decoded_rd <= regindex_bits'(1);
                                    decoded_rs1 <= regindex_bits'(mem_rdata_latched[11:7]);
                                end
                                if (mem_rdata_latched[12] != 0 && mem_rdata_latched[6:2] != 0) begin // C.ADD
                                    is_alu_reg_reg <= 1;
                                    decoded_rd <= regindex_bits'(mem_rdata_latched[11:7]);
                                    decoded_rs1 <= regindex_bits'(mem_rdata_latched[11:7]);
                                    decoded_rs2 <= 5'(mem_rdata_latched[6:2]);
                                end
                            end
                            3'b110: begin // C.SWSP
                                is_sb_sh_sw <= 1;
                                decoded_rs1 <= regindex_bits'(2);
                                decoded_rs2 <= 5'(mem_rdata_latched[6:2]);
                            end
                        endcase
                    end
                endcase
            end
        end

        if (i_request.decoder_trigger && !i_request.decoder_pseudo_trigger) begin
            pcpi_insn <= WITH_PCPI ? mem_rdata_q : 'bx;

            instr_beq   <= is_beq_bne_blt_bge_bltu_bgeu && mem_rdata_q[14:12] == 3'b000;
            instr_bne   <= is_beq_bne_blt_bge_bltu_bgeu && mem_rdata_q[14:12] == 3'b001;
            instr_blt   <= is_beq_bne_blt_bge_bltu_bgeu && mem_rdata_q[14:12] == 3'b100;
            instr_bge   <= is_beq_bne_blt_bge_bltu_bgeu && mem_rdata_q[14:12] == 3'b101;
            instr_bltu  <= is_beq_bne_blt_bge_bltu_bgeu && mem_rdata_q[14:12] == 3'b110;
            instr_bgeu  <= is_beq_bne_blt_bge_bltu_bgeu && mem_rdata_q[14:12] == 3'b111;

            instr_lb    <= is_lb_lh_lw_lbu_lhu && mem_rdata_q[14:12] == 3'b000;
            instr_lh    <= is_lb_lh_lw_lbu_lhu && mem_rdata_q[14:12] == 3'b001;
            instr_lw    <= is_lb_lh_lw_lbu_lhu && mem_rdata_q[14:12] == 3'b010;
            instr_lbu   <= is_lb_lh_lw_lbu_lhu && mem_rdata_q[14:12] == 3'b100;
            instr_lhu   <= is_lb_lh_lw_lbu_lhu && mem_rdata_q[14:12] == 3'b101;

            instr_sb    <= is_sb_sh_sw && mem_rdata_q[14:12] == 3'b000;
            instr_sh    <= is_sb_sh_sw && mem_rdata_q[14:12] == 3'b001;
            instr_sw    <= is_sb_sh_sw && mem_rdata_q[14:12] == 3'b010;

            instr_addi  <= is_alu_reg_imm && mem_rdata_q[14:12] == 3'b000;
            instr_slti  <= is_alu_reg_imm && mem_rdata_q[14:12] == 3'b010;
            instr_sltiu <= is_alu_reg_imm && mem_rdata_q[14:12] == 3'b011;
            instr_xori  <= is_alu_reg_imm && mem_rdata_q[14:12] == 3'b100;
            instr_ori   <= is_alu_reg_imm && mem_rdata_q[14:12] == 3'b110;
            instr_andi  <= is_alu_reg_imm && mem_rdata_q[14:12] == 3'b111;

            instr_slli  <= is_alu_reg_imm && mem_rdata_q[14:12] == 3'b001 && mem_rdata_q[31:25] == 7'b0000000;
            instr_srli  <= is_alu_reg_imm && mem_rdata_q[14:12] == 3'b101 && mem_rdata_q[31:25] == 7'b0000000;
            instr_srai  <= is_alu_reg_imm && mem_rdata_q[14:12] == 3'b101 && mem_rdata_q[31:25] == 7'b0100000;

            instr_add   <= is_alu_reg_reg && mem_rdata_q[14:12] == 3'b000 && mem_rdata_q[31:25] == 7'b0000000;
            instr_sub   <= is_alu_reg_reg && mem_rdata_q[14:12] == 3'b000 && mem_rdata_q[31:25] == 7'b0100000;
            instr_sll   <= is_alu_reg_reg && mem_rdata_q[14:12] == 3'b001 && mem_rdata_q[31:25] == 7'b0000000;
            instr_slt   <= is_alu_reg_reg && mem_rdata_q[14:12] == 3'b010 && mem_rdata_q[31:25] == 7'b0000000;
            instr_sltu  <= is_alu_reg_reg && mem_rdata_q[14:12] == 3'b011 && mem_rdata_q[31:25] == 7'b0000000;
            instr_xor   <= is_alu_reg_reg && mem_rdata_q[14:12] == 3'b100 && mem_rdata_q[31:25] == 7'b0000000;
            instr_srl   <= is_alu_reg_reg && mem_rdata_q[14:12] == 3'b101 && mem_rdata_q[31:25] == 7'b0000000;
            instr_sra   <= is_alu_reg_reg && mem_rdata_q[14:12] == 3'b101 && mem_rdata_q[31:25] == 7'b0100000;
            instr_or    <= is_alu_reg_reg && mem_rdata_q[14:12] == 3'b110 && mem_rdata_q[31:25] == 7'b0000000;
            instr_and   <= is_alu_reg_reg && mem_rdata_q[14:12] == 3'b111 && mem_rdata_q[31:25] == 7'b0000000;

            instr_rdcycle  <= ((mem_rdata_q[6:0] == 7'b1110011 && mem_rdata_q[31:12] == 'b11000000000000000010) ||
                               (mem_rdata_q[6:0] == 7'b1110011 && mem_rdata_q[31:12] == 'b11000000000100000010)) && ENABLE_COUNTERS;
            instr_rdcycleh <= ((mem_rdata_q[6:0] == 7'b1110011 && mem_rdata_q[31:12] == 'b11001000000000000010) ||
                               (mem_rdata_q[6:0] == 7'b1110011 && mem_rdata_q[31:12] == 'b11001000000100000010)) && ENABLE_COUNTERS && ENABLE_COUNTERS64;
            instr_rdinstr  <=  (mem_rdata_q[6:0] == 7'b1110011 && mem_rdata_q[31:12] == 'b11000000001000000010) && ENABLE_COUNTERS;
            instr_rdinstrh <=  (mem_rdata_q[6:0] == 7'b1110011 && mem_rdata_q[31:12] == 'b11001000001000000010) && ENABLE_COUNTERS && ENABLE_COUNTERS64;

            instr_ecall_ebreak <= ((mem_rdata_q[6:0] == 7'b1110011 && !(|mem_rdata_q[31:21]) && !(|mem_rdata_q[19:7])) ||
                    (COMPRESSED_ISA && mem_rdata_q[15:0] == 16'h9002));
            instr_fence <= (mem_rdata_q[6:0] == 7'b0001111 && !(|mem_rdata_q[14:12]));

            instr_getq    <= mem_rdata_q[6:0] == 7'b0001011 && mem_rdata_q[31:25] == 7'b0000000 && ENABLE_IRQ && ENABLE_IRQ_QREGS;
            instr_setq    <= mem_rdata_q[6:0] == 7'b0001011 && mem_rdata_q[31:25] == 7'b0000001 && ENABLE_IRQ && ENABLE_IRQ_QREGS;
            instr_maskirq <= mem_rdata_q[6:0] == 7'b0001011 && mem_rdata_q[31:25] == 7'b0000011 && ENABLE_IRQ;
            instr_timer   <= mem_rdata_q[6:0] == 7'b0001011 && mem_rdata_q[31:25] == 7'b0000101 && ENABLE_IRQ && ENABLE_IRQ_TIMER;

            is_slli_srli_srai <= is_alu_reg_imm && |{
                mem_rdata_q[14:12] == 3'b001 && mem_rdata_q[31:25] == 7'b0000000,
                mem_rdata_q[14:12] == 3'b101 && mem_rdata_q[31:25] == 7'b0000000,
                mem_rdata_q[14:12] == 3'b101 && mem_rdata_q[31:25] == 7'b0100000
            };

            is_jalr_addi_slti_sltiu_xori_ori_andi <= instr_jalr || is_alu_reg_imm && |{
                mem_rdata_q[14:12] == 3'b000,
                mem_rdata_q[14:12] == 3'b010,
                mem_rdata_q[14:12] == 3'b011,
                mem_rdata_q[14:12] == 3'b100,
                mem_rdata_q[14:12] == 3'b110,
                mem_rdata_q[14:12] == 3'b111
            };

            is_sll_srl_sra <= is_alu_reg_reg && |{
                mem_rdata_q[14:12] == 3'b001 && mem_rdata_q[31:25] == 7'b0000000,
                mem_rdata_q[14:12] == 3'b101 && mem_rdata_q[31:25] == 7'b0000000,
                mem_rdata_q[14:12] == 3'b101 && mem_rdata_q[31:25] == 7'b0100000
            };

            is_lui_auipc_jal_jalr_addi_add_sub <= 0;
            is_compare <= 0;

            case (1'b1)
                instr_jal:
                    decoded_imm <= decoded_imm_j;
                |{instr_lui, instr_auipc}:
                    decoded_imm <= mem_rdata_q[31:12] << 12;
                |{instr_jalr, is_lb_lh_lw_lbu_lhu, is_alu_reg_imm}:
                    decoded_imm <= 32'($signed(mem_rdata_q[31:20]));
                is_beq_bne_blt_bge_bltu_bgeu:
                    decoded_imm <= 32'($signed({mem_rdata_q[31], mem_rdata_q[7], mem_rdata_q[30:25], mem_rdata_q[11:8], 1'b0}));
                is_sb_sh_sw:
                    decoded_imm <= 32'($signed({mem_rdata_q[31:25], mem_rdata_q[11:7]}));
                default:
                    decoded_imm <= 32'bx;
            endcase
        end

        if (!rst_n) begin
            is_beq_bne_blt_bge_bltu_bgeu <= 0;
            is_compare <= 0;

            instr_beq   <= 0;
            instr_bne   <= 0;
            instr_blt   <= 0;
            instr_bge   <= 0;
            instr_bltu  <= 0;
            instr_bgeu  <= 0;

            instr_addi  <= 0;
            instr_slti  <= 0;
            instr_sltiu <= 0;
            instr_xori  <= 0;
            instr_ori   <= 0;
            instr_andi  <= 0;

            instr_add   <= 0;
            instr_sub   <= 0;
            instr_sll   <= 0;
            instr_slt   <= 0;
            instr_sltu  <= 0;
            instr_xor   <= 0;
            instr_srl   <= 0;
            instr_sra   <= 0;
            instr_or    <= 0;
            instr_and   <= 0;

            instr_fence <= 0;
        end
    end

    //! 3. 输出字段组合
    //! ---------------------

    assign o_response.mem_valid = mem_valid;
    assign o_response.mem_instr = mem_instr;
    assign o_response.mem_addr = mem_addr;
    assign o_response.mem_wdata = mem_wdata;
    assign o_response.mem_wstrb = mem_wstrb;
    assign o_response.mem_la_read = mem_la_read;
    assign o_response.mem_la_write = mem_la_write;
    assign o_response.mem_la_addr = mem_la_addr;
    assign o_response.mem_la_wdata = mem_la_wdata;
    assign o_response.mem_la_wstrb = mem_la_wstrb;
    assign o_response.mem_rdata_word = mem_rdata_word;
    assign o_response.prefetched_high_word = prefetched_high_word;
    assign o_response.mem_done = mem_done;
    assign o_response.mem_busy = mem_busy;
    assign o_response.pcpi_insn = pcpi_insn;
    assign o_response.decoded_rd = 6'(decoded_rd);
    assign o_response.decoded_rs1 = 6'(decoded_rs1);
    assign o_response.decoded_rs2 = decoded_rs2;
    assign o_response.decoded_imm = decoded_imm;
    assign o_response.decoded_imm_j = decoded_imm_j;
    assign o_response.compressed_instr = compressed_instr;
    assign o_response.dbg_insn_opcode = dbg_insn_opcode;
    assign o_response.dbg_insn_addr = dbg_insn_addr;
    assign o_response.dbg_insn_rs1 = dbg_insn_rs1;
    assign o_response.dbg_insn_rs2 = dbg_insn_rs2;
    assign o_response.dbg_valid_insn = dbg_valid_insn;
    assign o_response.instr_lui = instr_lui;
    assign o_response.instr_auipc = instr_auipc;
    assign o_response.instr_jal = instr_jal;
    assign o_response.instr_jalr = instr_jalr;
    assign o_response.instr_beq = instr_beq;
    assign o_response.instr_bne = instr_bne;
    assign o_response.instr_blt = instr_blt;
    assign o_response.instr_bge = instr_bge;
    assign o_response.instr_bltu = instr_bltu;
    assign o_response.instr_bgeu = instr_bgeu;
    assign o_response.instr_lb = instr_lb;
    assign o_response.instr_lh = instr_lh;
    assign o_response.instr_lw = instr_lw;
    assign o_response.instr_lbu = instr_lbu;
    assign o_response.instr_lhu = instr_lhu;
    assign o_response.instr_sb = instr_sb;
    assign o_response.instr_sh = instr_sh;
    assign o_response.instr_sw = instr_sw;
    assign o_response.instr_addi = instr_addi;
    assign o_response.instr_slti = instr_slti;
    assign o_response.instr_sltiu = instr_sltiu;
    assign o_response.instr_xori = instr_xori;
    assign o_response.instr_ori = instr_ori;
    assign o_response.instr_andi = instr_andi;
    assign o_response.instr_slli = instr_slli;
    assign o_response.instr_srli = instr_srli;
    assign o_response.instr_srai = instr_srai;
    assign o_response.instr_add = instr_add;
    assign o_response.instr_sub = instr_sub;
    assign o_response.instr_sll = instr_sll;
    assign o_response.instr_slt = instr_slt;
    assign o_response.instr_sltu = instr_sltu;
    assign o_response.instr_xor = instr_xor;
    assign o_response.instr_srl = instr_srl;
    assign o_response.instr_sra = instr_sra;
    assign o_response.instr_or = instr_or;
    assign o_response.instr_and = instr_and;
    assign o_response.instr_rdcycle = instr_rdcycle;
    assign o_response.instr_rdcycleh = instr_rdcycleh;
    assign o_response.instr_rdinstr = instr_rdinstr;
    assign o_response.instr_rdinstrh = instr_rdinstrh;
    assign o_response.instr_ecall_ebreak = instr_ecall_ebreak;
    assign o_response.instr_fence = instr_fence;
    assign o_response.instr_getq = instr_getq;
    assign o_response.instr_setq = instr_setq;
    assign o_response.instr_retirq = instr_retirq;
    assign o_response.instr_maskirq = instr_maskirq;
    assign o_response.instr_waitirq = instr_waitirq;
    assign o_response.instr_timer = instr_timer;
    assign o_response.instr_trap = instr_trap;
    assign o_response.is_lui_auipc_jal = is_lui_auipc_jal;
    assign o_response.is_lb_lh_lw_lbu_lhu = is_lb_lh_lw_lbu_lhu;
    assign o_response.is_slli_srli_srai = is_slli_srli_srai;
    assign o_response.is_jalr_addi_slti_sltiu_xori_ori_andi = is_jalr_addi_slti_sltiu_xori_ori_andi;
    assign o_response.is_sb_sh_sw = is_sb_sh_sw;
    assign o_response.is_sll_srl_sra = is_sll_srl_sra;
    assign o_response.is_lui_auipc_jal_jalr_addi_add_sub = is_lui_auipc_jal_jalr_addi_add_sub;
    assign o_response.is_slti_blt_slt = is_slti_blt_slt;
    assign o_response.is_sltiu_bltu_sltu = is_sltiu_bltu_sltu;
    assign o_response.is_beq_bne_blt_bge_bltu_bgeu = is_beq_bne_blt_bge_bltu_bgeu;
    assign o_response.is_lbu_lhu_lw = is_lbu_lhu_lw;
    assign o_response.is_alu_reg_imm = is_alu_reg_imm;
    assign o_response.is_alu_reg_reg = is_alu_reg_reg;
    assign o_response.is_compare = is_compare;
    assign o_response.is_rdcycle_rdcycleh_rdinstr_rdinstrh = is_rdcycle_rdcycleh_rdinstr_rdinstrh;
endmodule

`undef PICORV32_FRONT_ASSERT
`undef PICORV32_FRONT_KEEP
`default_nettype wire
