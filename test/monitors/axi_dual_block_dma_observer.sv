// SPDX-License-Identifier: Apache-2.0
`ifndef SYNTHESIS
/* verilator lint_off DECLFILENAME */
module axi_dual_block_dma_observer #(
  parameter int TB_CONV_SUPPORTED=0
);

wire [31:0] conv_stat_hits;
wire [31:0] conv_stat_misses;
wire [31:0] conv_stat_read_bytes;
wire [31:0] conv_stat_prefetch_lines;
wire [31:0] conv_stat_prefetch_used;
wire [31:0] conv_stat_prefetch_wasted;
wire [31:0] conv_stat_prefetch_unused;
wire [31:0] conv_stat_prefetch_bytes;
wire [31:0] conv_stat_prefetch_late;
if(TB_CONV_SUPPORTED)begin:g_conv_stats
assign conv_stat_hits=axi_dual_block_dma.g_im2col.u_frontend.tb_observer.stat_hits;
assign conv_stat_misses=axi_dual_block_dma.g_im2col.u_frontend.tb_observer.stat_misses;
assign conv_stat_read_bytes=axi_dual_block_dma.g_im2col.u_frontend.tb_observer.stat_read_bytes;
assign conv_stat_prefetch_lines=axi_dual_block_dma.g_im2col.u_frontend.tb_observer.stat_prefetch_lines;
assign conv_stat_prefetch_used=axi_dual_block_dma.g_im2col.u_frontend.tb_observer.stat_prefetch_used;
assign conv_stat_prefetch_wasted=axi_dual_block_dma.g_im2col.u_frontend.tb_observer.stat_prefetch_wasted;
assign conv_stat_prefetch_unused=axi_dual_block_dma.g_im2col.u_frontend.tb_observer.stat_prefetch_unused;
assign conv_stat_prefetch_bytes=axi_dual_block_dma.g_im2col.u_frontend.tb_observer.stat_prefetch_bytes;
assign conv_stat_prefetch_late=axi_dual_block_dma.g_im2col.u_frontend.tb_observer.stat_prefetch_late;
end else begin:g_no_conv_stats
assign conv_stat_hits=0;
assign conv_stat_misses=0;
assign conv_stat_read_bytes=0;
assign conv_stat_prefetch_lines=0;
assign conv_stat_prefetch_used=0;
assign conv_stat_prefetch_wasted=0;
assign conv_stat_prefetch_unused=0;
assign conv_stat_prefetch_bytes=0;
assign conv_stat_prefetch_late=0;
end
wire [31:0] win_stat_requests=axi_dual_block_dma.u_window_queue.tb_observer.stat_requests;
wire [31:0] win_stat_completions=axi_dual_block_dma.u_window_queue.tb_observer.stat_completions;
wire [31:0] win_stat_peak_outstanding=axi_dual_block_dma.u_window_queue.tb_observer.stat_peak_outstanding;
wire [31:0] win_stat_response_beats=axi_dual_block_dma.u_window_queue.tb_observer.stat_response_beats;
wire [31:0] win_stat_consecutive_responses=axi_dual_block_dma.u_window_queue.tb_observer.stat_consecutive_responses;
wire [31:0] win_stat_request_response_overlap=axi_dual_block_dma.u_window_queue.tb_observer.stat_request_response_overlap;
endmodule
bind axi_dual_block_dma axi_dual_block_dma_observer #(
  .TB_CONV_SUPPORTED(32'(CONV_SUPPORTED))
) tb_observer();
/* verilator lint_on DECLFILENAME */
`endif
