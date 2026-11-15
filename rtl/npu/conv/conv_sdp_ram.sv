// SPDX-License-Identifier: Apache-2.0
// Simple dual-port RAM: one synchronous 32-bit read and one byte-enabled write.
// No reset of the data array. Same-address read/write is forbidden by the cache FSM.
module conv_sdp_ram #(
  parameter int DEPTH = 1024,
  parameter int AW = $clog2(DEPTH)
) (
  input logic clk,
  input logic rd_en,
  input logic [AW-1:0] rd_addr,
  output logic [31:0] rd_data,
  input logic wr_en,
  input logic [AW-1:0] wr_addr,
  input logic [31:0] wr_data,
  input logic [3:0] wr_strb
);
  (* ram_style = "block" *) logic [31:0] mem [0:DEPTH-1];
  always_ff @(posedge clk) begin
    if (rd_en) rd_data <= mem[rd_addr];
    if (wr_en) begin
      for (int b=0; b<4; b++)
        if (wr_strb[b]) mem[wr_addr][b*8 +: 8] <= wr_data[b*8 +: 8];
    end
  end
`ifdef CONV_ASSERT
  always_ff @(posedge clk)
    assert (!(rd_en && wr_en && rd_addr == wr_addr));
`endif
endmodule
