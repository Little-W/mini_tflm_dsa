// SPDX-License-Identifier: Apache-2.0
`ifndef SYNTHESIS
/* verilator lint_off DECLFILENAME */
module conv_im2col_frontend_observer;

wire [31:0] stat_hits=conv_im2col_frontend.u_cache.tb_observer.stat_hits;
wire [31:0] stat_misses=conv_im2col_frontend.u_cache.tb_observer.stat_misses;
wire [31:0] stat_read_bytes=conv_im2col_frontend.u_cache.tb_observer.stat_read_bytes;
wire [31:0] stat_prefetch_lines=conv_im2col_frontend.u_cache.tb_observer.stat_prefetch_lines;
wire [31:0] stat_prefetch_used=conv_im2col_frontend.u_cache.tb_observer.stat_prefetch_used;
wire [31:0] stat_prefetch_wasted=conv_im2col_frontend.u_cache.tb_observer.stat_prefetch_wasted;
wire [31:0] stat_prefetch_unused=conv_im2col_frontend.u_cache.tb_observer.stat_prefetch_unused;
wire [31:0] stat_prefetch_bytes=conv_im2col_frontend.u_cache.tb_observer.stat_prefetch_bytes;
wire [31:0] stat_prefetch_late=conv_im2col_frontend.u_cache.tb_observer.stat_prefetch_late;
endmodule
bind conv_im2col_frontend conv_im2col_frontend_observer tb_observer();
/* verilator lint_on DECLFILENAME */
`endif
