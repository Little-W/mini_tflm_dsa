// SPDX-License-Identifier: Apache-2.0
// Structural adapter to ia_loader's tl_wr_* interface (2 corrected s16 lanes).
// This is NOT a patched ia_loader. Select this path only while Conv owns the slot.
module conv_ia_write_adapter #(
  parameter int SIZE=16,
  parameter int CACHE_BLOCKS=4,
  parameter int SW=(CACHE_BLOCKS<=1 ? 1 : $clog2(CACHE_BLOCKS)),
  parameter int CW=$clog2(SIZE)
) (
  input logic selected,
  input logic in_valid,
  output logic in_ready,
  input logic [SW-1:0] in_slot,
  input logic [CW-1:0] in_row, in_col,
  input logic signed [15:0] in_data [2],
  input logic [1:0] in_mask,
  output logic [SW-1:0] tl_wr_slot,
  output logic [CW-1:0] tl_wr_row, tl_wr_col_base,
  output logic signed [15:0] tl_wr_data [4],
  output logic tl_wr_valid [4],
  output logic tl_wr_use_16bits
);
  assign in_ready=selected;
  assign tl_wr_slot=in_slot;
  assign tl_wr_row=in_row;
  assign tl_wr_col_base=in_col;
  assign tl_wr_use_16bits=1'b1;
  always_comb begin
    for (int i=0;i<4;i++) begin tl_wr_data[i]=0; tl_wr_valid[i]=0; end
    for (int i=0;i<2;i++) begin
      tl_wr_data[i]=in_data[i];
      tl_wr_valid[i]=selected && in_valid && in_mask[i];
    end
  end
endmodule
