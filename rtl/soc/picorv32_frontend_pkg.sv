// PicoRV32 前端与执行控制器之间的打包字段；所有字段均属于同一时钟域。
`timescale 1 ns / 1 ps
`default_nettype none
package picorv32_frontend_pkg;
    typedef struct packed {
        logic trap; // 处理器异常停止状态。
        logic [31:0] next_pc; // 下一条指令的字节地址。
        logic [31:0] reg_op1; // 访存地址操作数。
        logic [31:0] reg_op2; // 存储写入操作数。
        logic [1:0] mem_wordsize; // 访存宽度编码。
        logic mem_do_prefetch; // 指令预取请求。
        logic mem_do_rinst; // 指令读取请求。
        logic mem_do_rdata; // 数据读取请求。
        logic mem_do_wdata; // 数据写入请求。
        logic clear_prefetched_high_word; // 清除已保存的压缩指令高半字。
        logic decoder_trigger; // 指令详细译码使能。
        logic decoder_trigger_q; // 延迟一周期的译码使能。
        logic decoder_pseudo_trigger; // 复用已译码指令的请求。
        logic decoder_pseudo_trigger_q; // 延迟一周期的复用请求。
        logic launch_next_insn; // 开始执行下一条指令。
    } request_t;

    typedef struct packed {
        logic mem_valid; // 存储请求有效。
        logic mem_instr; // 当前请求为取指访问。
        logic [31:0] mem_addr; // 存储访问字节地址。
        logic [31:0] mem_wdata; // 存储写入数据。
        logic [3:0] mem_wstrb; // 存储写入字节使能。
        logic mem_la_read; // 下一周期读取请求预告。
        logic mem_la_write; // 下一周期写入请求预告。
        logic [31:0] mem_la_addr; // 预告请求的字节地址。
        logic [31:0] mem_la_wdata; // 预告写入数据。
        logic [3:0] mem_la_wstrb; // 预告写入字节使能。
        logic [31:0] mem_rdata_word; // 按访问宽度选取的读取数据。
        logic prefetched_high_word; // 压缩指令高半字已经保存。
        logic mem_done; // 当前取指或访存操作完成。
        logic mem_busy; // 存在待完成的存储操作。
        logic [31:0] pcpi_insn; // 协处理器指令编码。
        logic [5:0] decoded_rd; // 目标寄存器编号，高位补零。
        logic [5:0] decoded_rs1; // 第一源寄存器编号，高位补零。
        logic [4:0] decoded_rs2; // 第二源寄存器编号。
        logic [31:0] decoded_imm; // 已扩展的立即数。
        logic [31:0] decoded_imm_j; // 直接跳转立即数。
        logic compressed_instr; // 当前指令为压缩指令。
        logic [31:0] dbg_insn_opcode; // 执行记录中的指令编码。
        logic [31:0] dbg_insn_addr; // 执行记录中的指令地址。
        logic [4:0] dbg_insn_rs1; // 执行记录中的第一源寄存器编号。
        logic [4:0] dbg_insn_rs2; // 执行记录中的第二源寄存器编号。
        logic dbg_valid_insn; // 执行记录有效。
        logic instr_lui; // 指令 LUI 的译码标志。
        logic instr_auipc; // 指令 AUIPC 的译码标志。
        logic instr_jal; // 指令 JAL 的译码标志。
        logic instr_jalr; // 指令 JALR 的译码标志。
        logic instr_beq; // 指令 BEQ 的译码标志。
        logic instr_bne; // 指令 BNE 的译码标志。
        logic instr_blt; // 指令 BLT 的译码标志。
        logic instr_bge; // 指令 BGE 的译码标志。
        logic instr_bltu; // 指令 BLTU 的译码标志。
        logic instr_bgeu; // 指令 BGEU 的译码标志。
        logic instr_lb; // 指令 LB 的译码标志。
        logic instr_lh; // 指令 LH 的译码标志。
        logic instr_lw; // 指令 LW 的译码标志。
        logic instr_lbu; // 指令 LBU 的译码标志。
        logic instr_lhu; // 指令 LHU 的译码标志。
        logic instr_sb; // 指令 SB 的译码标志。
        logic instr_sh; // 指令 SH 的译码标志。
        logic instr_sw; // 指令 SW 的译码标志。
        logic instr_addi; // 指令 ADDI 的译码标志。
        logic instr_slti; // 指令 SLTI 的译码标志。
        logic instr_sltiu; // 指令 SLTIU 的译码标志。
        logic instr_xori; // 指令 XORI 的译码标志。
        logic instr_ori; // 指令 ORI 的译码标志。
        logic instr_andi; // 指令 ANDI 的译码标志。
        logic instr_slli; // 指令 SLLI 的译码标志。
        logic instr_srli; // 指令 SRLI 的译码标志。
        logic instr_srai; // 指令 SRAI 的译码标志。
        logic instr_add; // 指令 ADD 的译码标志。
        logic instr_sub; // 指令 SUB 的译码标志。
        logic instr_sll; // 指令 SLL 的译码标志。
        logic instr_slt; // 指令 SLT 的译码标志。
        logic instr_sltu; // 指令 SLTU 的译码标志。
        logic instr_xor; // 指令 XOR 的译码标志。
        logic instr_srl; // 指令 SRL 的译码标志。
        logic instr_sra; // 指令 SRA 的译码标志。
        logic instr_or; // 指令 OR 的译码标志。
        logic instr_and; // 指令 AND 的译码标志。
        logic instr_rdcycle; // 指令 RDCYCLE 的译码标志。
        logic instr_rdcycleh; // 指令 RDCYCLEH 的译码标志。
        logic instr_rdinstr; // 指令 RDINSTR 的译码标志。
        logic instr_rdinstrh; // 指令 RDINSTRH 的译码标志。
        logic instr_ecall_ebreak; // 指令 ECALL_EBREAK 的译码标志。
        logic instr_fence; // 指令 FENCE 的译码标志。
        logic instr_getq; // 指令 GETQ 的译码标志。
        logic instr_setq; // 指令 SETQ 的译码标志。
        logic instr_retirq; // 指令 RETIRQ 的译码标志。
        logic instr_maskirq; // 指令 MASKIRQ 的译码标志。
        logic instr_waitirq; // 指令 WAITIRQ 的译码标志。
        logic instr_timer; // 指令 TIMER 的译码标志。
        logic instr_trap; // 指令 TRAP 的译码标志。
        logic is_lui_auipc_jal; // 指令类别 lui_auipc_jal 的选择标志。
        logic is_lb_lh_lw_lbu_lhu; // 指令类别 lb_lh_lw_lbu_lhu 的选择标志。
        logic is_slli_srli_srai; // 指令类别 slli_srli_srai 的选择标志。
        logic is_jalr_addi_slti_sltiu_xori_ori_andi; // 指令类别 jalr_addi_slti_sltiu_xori_ori_andi 的选择标志。
        logic is_sb_sh_sw; // 指令类别 sb_sh_sw 的选择标志。
        logic is_sll_srl_sra; // 指令类别 sll_srl_sra 的选择标志。
        logic is_lui_auipc_jal_jalr_addi_add_sub; // 指令类别 lui_auipc_jal_jalr_addi_add_sub 的选择标志。
        logic is_slti_blt_slt; // 指令类别 slti_blt_slt 的选择标志。
        logic is_sltiu_bltu_sltu; // 指令类别 sltiu_bltu_sltu 的选择标志。
        logic is_beq_bne_blt_bge_bltu_bgeu; // 指令类别 beq_bne_blt_bge_bltu_bgeu 的选择标志。
        logic is_lbu_lhu_lw; // 指令类别 lbu_lhu_lw 的选择标志。
        logic is_alu_reg_imm; // 指令类别 alu_reg_imm 的选择标志。
        logic is_alu_reg_reg; // 指令类别 alu_reg_reg 的选择标志。
        logic is_compare; // 指令类别 compare 的选择标志。
        logic is_rdcycle_rdcycleh_rdinstr_rdinstrh; // 指令类别 rdcycle_rdcycleh_rdinstr_rdinstrh 的选择标志。
    } response_t;

endpackage
`default_nettype wire
