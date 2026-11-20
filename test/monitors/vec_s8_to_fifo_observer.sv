// SPDX-License-Identifier: Apache-2.0
`ifndef SYNTHESIS
/* verilator lint_off DECLFILENAME */
module vec_s8_to_fifo_observer #(
  parameter int TB_BANKS=0,
  parameter int TB_ENABLE_TRANSPOSE=0,
  parameter int TB_VLEN=0
);
wire stream_active,write_sel,read_sel,bank_ready0,bank_ready1;
wire [$clog2(TB_VLEN+1)-1:0] bank_count0,bank_count1;
if(TB_ENABLE_TRANSPOSE==0)begin:g_linear_stats
assign stream_active=vec_s8_to_fifo.g_linear.u_linear.stream_active;
assign write_sel=vec_s8_to_fifo.g_linear.u_linear.write_bank[0];
assign read_sel=vec_s8_to_fifo.g_linear.u_linear.read_bank[0];
assign bank_ready0=vec_s8_to_fifo.g_linear.u_linear.bank_ready[0];
assign bank_ready1=TB_BANKS>1 ? vec_s8_to_fifo.g_linear.u_linear.bank_ready[1] : 1'b0;
assign bank_count0=vec_s8_to_fifo.g_linear.u_linear.bank_count[0];
assign bank_count1=TB_BANKS>1 ? vec_s8_to_fifo.g_linear.u_linear.bank_count[1] : '0;
end else begin:g_full_stats
assign stream_active=vec_s8_to_fifo.g_full.u_full.stream_active;
assign write_sel=vec_s8_to_fifo.g_full.u_full.write_bank[0];
assign read_sel=vec_s8_to_fifo.g_full.u_full.read_bank[0];
assign bank_ready0=vec_s8_to_fifo.g_full.u_full.bank_ready[0];
assign bank_ready1=TB_BANKS>1 ? vec_s8_to_fifo.g_full.u_full.bank_ready[1] : 1'b0;
if (TB_BANKS >= 8 && (TB_BANKS & (TB_BANKS-1)) == 0) begin : g_count_memory
assign bank_count0=bank_ready0 ? vec_s8_to_fifo.g_full.u_full.g_count_memory.u_bank_count.mem[0] : '0;
assign bank_count1=bank_ready1 ? vec_s8_to_fifo.g_full.u_full.g_count_memory.u_bank_count.mem[1] : '0;
end else begin : g_count_registers
assign bank_count0=vec_s8_to_fifo.g_full.u_full.g_count_registers.bank_count[0];
assign bank_count1=TB_BANKS>1 ? vec_s8_to_fifo.g_full.u_full.g_count_registers.bank_count[1] : '0;
end
end

endmodule
bind vec_s8_to_fifo vec_s8_to_fifo_observer #(
  .TB_BANKS(32'(BANKS)),
  .TB_ENABLE_TRANSPOSE(32'(ENABLE_TRANSPOSE)),
  .TB_VLEN(32'(VLEN))
) tb_observer();
/* verilator lint_on DECLFILENAME */
`endif
