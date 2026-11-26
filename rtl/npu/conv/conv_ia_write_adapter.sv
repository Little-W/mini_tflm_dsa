// SPDX-License-Identifier: Apache-2.0
// Structural adapter to ia_loader's tl_wr_* interface (2 corrected s16 lanes).
// This is NOT a patched ia_loader. Select this path only while Conv owns the slot.
module conv_ia_write_adapter #( // 将卷积前端的两路十六位结果转换为输入加载器的逐通道写入接口。
  parameter int SIZE=16,
  parameter int CACHE_BLOCKS=4,
  parameter int SW=(CACHE_BLOCKS<=1 ? 1 : $clog2(CACHE_BLOCKS)),
  parameter int CW=$clog2(SIZE)
) (
  input logic selected, // 当前输入缓存写入接口由卷积路径使用。
  input logic in_valid, // 卷积前端的本拍数据有效。
  output logic in_ready, // 当前允许接收卷积前端数据。
  input logic [SW-1:0] in_slot, // 当前数据对应的输入缓存槽号。
  input logic [CW-1:0] in_row /* 当前数据在展开分块内的行号。 */, in_col /* 当前两路数据的起始分块列号。 */,
  input logic signed [15:0] in_data [2], // 卷积前端返回的两路有符号十六位数据。
  input logic [1:0] in_mask, // 两路卷积返回数据各自的有效标志。
  output logic [SW-1:0] tl_wr_slot, // 返回数据需要写入的输入缓存槽号。
  output logic [CW-1:0] tl_wr_row /* 返回数据需要写入的分块行号。 */, tl_wr_col_base /* 本拍返回数据的起始分块列号。 */,
  output logic signed [15:0] tl_wr_data [4], // 送入输入加载器的逐通道有符号数据。
  output logic tl_wr_valid [4], // 送入输入加载器的逐通道写入有效标志。
  output logic tl_wr_use_16bits // 返回数据采用十六位元素格式。
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
