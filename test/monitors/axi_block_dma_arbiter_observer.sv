// SPDX-License-Identifier: Apache-2.0
`ifndef SYNTHESIS
/* verilator lint_off DECLFILENAME */
module axi_block_dma_arbiter_observer;
wire [31:0] conv_stat_hits=axi_block_dma_arbiter.u_dma.tb_observer.conv_stat_hits;
wire [31:0] conv_stat_misses=axi_block_dma_arbiter.u_dma.tb_observer.conv_stat_misses;
wire [31:0] conv_stat_read_bytes=axi_block_dma_arbiter.u_dma.tb_observer.conv_stat_read_bytes;
endmodule
bind axi_block_dma_arbiter axi_block_dma_arbiter_observer tb_observer();
/* verilator lint_on DECLFILENAME */
`endif
