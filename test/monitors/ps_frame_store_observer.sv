// SPDX-License-Identifier: Apache-2.0
`ifndef SYNTHESIS
module ps_frame_store_observer #(
  parameter int BANKS=8,
  parameter int BANK_DEPTH=128,
  parameter int EXTERNAL_RAM=0
);
  wire [31:0] bank_free_count[BANKS];
  wire [2:0] encode_commit_opcode=3'd3;
  wire [2:0] encode_commit_words=3'd4;

  reg [31:0] occupancy_free[BANKS];
  for(genvar bank=0;bank<BANKS;bank++)begin:g_bank
    assign bank_free_count[bank]=occupancy_free[bank];
    always @(posedge ps_frame_store.clk or negedge ps_frame_store.rst_n)begin
      if(!ps_frame_store.rst_n)occupancy_free[bank]<=EXTERNAL_RAM==0 ? BANK_DEPTH : 0;
      else if(ps_frame_store.configuration_pending)occupancy_free[bank]<=ps_frame_store.cfg_pool_bank_words;
      else if(ps_frame_store.clear_metadata)occupancy_free[bank]<=0;
      else occupancy_free[bank]<=occupancy_free[bank]+32'(ps_frame_store.payload_ram_read_en[bank])-32'(ps_frame_store.payload_ram_write_en[bank]);
    end
  end

endmodule
bind ps_frame_store ps_frame_store_observer #(.BANKS(BANKS),.BANK_DEPTH(BANK_DEPTH),.EXTERNAL_RAM(EXTERNAL_RAM)) tb_observer();
`endif
