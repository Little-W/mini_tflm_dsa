// SPDX-License-Identifier: Apache-2.0
// One synchronous 32-bit demand read and one native-width byte-enabled fill.
// No reset of the data array. Same-address read/write is forbidden by the cache FSM.
module conv_sdp_ram #(
  parameter int DEPTH = 1024,
  parameter int AW = $clog2(DEPTH),
  parameter int WRITE_WIDTH = 32
) (
  input logic clk,
  input logic rd_en,
  input logic [AW-1:0] rd_addr,
  output logic [31:0] rd_data,
  input logic wr_en,
  input logic [AW-1:0] wr_addr,
  input logic [WRITE_WIDTH-1:0] wr_data,
  input logic [WRITE_WIDTH/8-1:0] wr_strb
);
  localparam int WORDS = WRITE_WIDTH / 32;
  localparam int SELECT_W = WORDS<=1 ? 1 : $clog2(WORDS);
  localparam int BANK_SHIFT = $clog2(WORDS);
  logic [SELECT_W-1:0] read_bank;
  logic [31:0] read_words[WORDS];
  always_ff @(posedge clk) if (rd_en) read_bank <= (WORDS == 1) ? '0 : SELECT_W'(rd_addr);
  assign rd_data = read_words[read_bank];
  for(genvar word=0;word<WORDS;word++)begin:g_bank
`ifdef ASIC_SRAM
    localparam int BANK_DEPTH=DEPTH/WORDS;
    localparam int BANK_AW=$clog2(BANK_DEPTH)>0 ? $clog2(BANK_DEPTH) : 1;
    wire [31:0] bit_mask;
    for(genvar byte_lane=0;byte_lane<4;byte_lane++) begin:g_byte_mask
      assign bit_mask[byte_lane*8+:8]={8{wr_strb[word*4+byte_lane]}};
    end
    smic40_sram_1r1w #(.DATA_WIDTH(32),.DEPTH(BANK_DEPTH),.ADDR_WIDTH(BANK_AW)) u_sram (
      .clk(clk),.write_enable(wr_en),.write_address(BANK_AW'(wr_addr>>BANK_SHIFT)),
      .write_data(wr_data[word*32+:32]),.write_mask(bit_mask),
      .read_enable(rd_en),.read_address(BANK_AW'(rd_addr>>BANK_SHIFT)),.read_data(read_words[word]));
`else
    (* ram_style = "block" *) logic [31:0] mem [0:DEPTH/WORDS-1];
    always_ff @(posedge clk) begin
      if (rd_en) read_words[word] <= mem[rd_addr >> BANK_SHIFT];
      if (wr_en) for(int b=0;b<4;b++)
        if (wr_strb[word*4+b]) mem[wr_addr >> BANK_SHIFT][b*8+:8] <= wr_data[word*32+b*8+:8];
    end
`endif
  end
`ifdef NPU_SIM_ASSERT
  initial begin
    assert (WRITE_WIDTH >= 32 && WRITE_WIDTH % 32 == 0 &&
            (WORDS & (WORDS - 1)) == 0 && DEPTH % WORDS == 0);
  end
  always_ff @(posedge clk)
    assert (!(rd_en && wr_en && (rd_addr >> BANK_SHIFT) == (wr_addr >> BANK_SHIFT)));
`endif
endmodule
