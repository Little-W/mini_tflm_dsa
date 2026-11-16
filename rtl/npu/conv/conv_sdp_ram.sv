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
  logic [SELECT_W-1:0] read_bank;
  logic [31:0] read_words[WORDS];
  always_ff @(posedge clk) if (rd_en) read_bank <= SELECT_W'(rd_addr % WORDS);
  assign rd_data = read_words[read_bank];
  for(genvar word=0;word<WORDS;word++)begin:g_bank
    (* ram_style = "block" *) logic [31:0] mem [0:DEPTH/WORDS-1];
    always_ff @(posedge clk) begin
      if (rd_en) read_words[word] <= mem[int'(rd_addr)/WORDS];
      if (wr_en) for(int b=0;b<4;b++)
        if (wr_strb[word*4+b]) mem[int'(wr_addr)/WORDS][b*8+:8] <= wr_data[word*32+b*8+:8];
    end
  end
`ifdef CONV_ASSERT
  always_ff @(posedge clk)
    assert (!(rd_en && wr_en && int'(rd_addr)/WORDS == int'(wr_addr)/WORDS));
`endif
endmodule
