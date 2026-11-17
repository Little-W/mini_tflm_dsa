// SPDX-License-Identifier: Apache-2.0
`ifndef SYNTHESIS
/* verilator lint_off DECLFILENAME */
module conv_read_cache_observer #(
  parameter int TB_CACHE_POLICY=0
);

wire [31:0] stat_hits;
wire [31:0] stat_misses;
wire [31:0] stat_read_bytes;
wire [31:0] stat_prefetch_lines;
wire [31:0] stat_prefetch_used;
wire [31:0] stat_prefetch_wasted;
wire [31:0] stat_prefetch_unused;
wire [31:0] stat_prefetch_bytes;
wire [31:0] stat_prefetch_late;
if(TB_CACHE_POLICY==3)begin:g_window_stats
assign stat_hits=conv_read_cache.g_window.u_window.tb_observer.stat_hits;
assign stat_misses=conv_read_cache.g_window.u_window.tb_observer.stat_misses;
assign stat_read_bytes=conv_read_cache.g_window.u_window.tb_observer.stat_read_bytes;
assign stat_prefetch_lines=conv_read_cache.g_window.u_window.tb_observer.stat_prefetch_lines;
assign stat_prefetch_used=conv_read_cache.g_window.u_window.tb_observer.stat_prefetch_used;
assign stat_prefetch_wasted=conv_read_cache.g_window.u_window.tb_observer.stat_prefetch_wasted;
assign stat_prefetch_unused=conv_read_cache.g_window.u_window.tb_observer.stat_prefetch_unused;
assign stat_prefetch_bytes=conv_read_cache.g_window.u_window.tb_observer.stat_prefetch_bytes;
assign stat_prefetch_late=conv_read_cache.g_window.u_window.tb_observer.stat_prefetch_late;
end else begin:g_reference_stats
assign stat_hits=conv_read_cache.g_reference.u_reference.tb_observer.stat_hits;
assign stat_misses=conv_read_cache.g_reference.u_reference.tb_observer.stat_misses;
assign stat_read_bytes=conv_read_cache.g_reference.u_reference.tb_observer.stat_read_bytes;
assign stat_prefetch_lines=32'd0;
assign stat_prefetch_used=32'd0;
assign stat_prefetch_wasted=32'd0;
assign stat_prefetch_unused=32'd0;
assign stat_prefetch_bytes=32'd0;
assign stat_prefetch_late=32'd0;
end

endmodule
bind conv_read_cache conv_read_cache_observer #(
  .TB_CACHE_POLICY(32'(CACHE_POLICY))
) tb_observer();
/* verilator lint_on DECLFILENAME */
`endif
