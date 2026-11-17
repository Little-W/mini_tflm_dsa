// SPDX-License-Identifier: Apache-2.0
`ifndef SYNTHESIS
/* verilator lint_off DECLFILENAME */
module ia_loader_ctrl_observer #(
  parameter int TB_SLOT_BLOCKS=0
);




wire [TB_SLOT_BLOCKS-1:0] cache_blk_valid;
for(genvar gi=0;gi<TB_SLOT_BLOCKS;gi++)assign cache_blk_valid[gi]=ia_loader_ctrl.blk_valid[gi];

endmodule
bind ia_loader_ctrl ia_loader_ctrl_observer #(
  .TB_SLOT_BLOCKS(32'(SLOT_BLOCKS))
) tb_observer();
/* verilator lint_on DECLFILENAME */
`endif
