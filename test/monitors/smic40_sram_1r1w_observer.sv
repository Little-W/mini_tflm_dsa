// SPDX-License-Identifier: Apache-2.0
`ifndef SYNTHESIS
module smic40_sram_1r1w_observer;
  initial forever @(posedge smic40_sram_1r1w.clk) begin
    if(smic40_sram_1r1w.read_enable && smic40_sram_1r1w.write_enable &&
       smic40_sram_1r1w.read_address==smic40_sram_1r1w.write_address &&
       |smic40_sram_1r1w.write_mask)
      $fatal(1,"SRAM read/write collision at address %0d",smic40_sram_1r1w.read_address);
  end
endmodule
bind smic40_sram_1r1w smic40_sram_1r1w_observer tb_observer();
`endif
