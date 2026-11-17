// SPDX-License-Identifier: Apache-2.0
`ifndef SYNTHESIS
/* verilator lint_off DECLFILENAME */
module conv_ia_tile_path_observer;

wire [31:0] stat_hits=conv_ia_tile_path.u_front.tb_observer.stat_hits;
wire [31:0] stat_misses=conv_ia_tile_path.u_front.tb_observer.stat_misses;
wire [31:0] stat_read_bytes=conv_ia_tile_path.u_front.tb_observer.stat_read_bytes;
endmodule
bind conv_ia_tile_path conv_ia_tile_path_observer tb_observer();
/* verilator lint_on DECLFILENAME */
`endif
