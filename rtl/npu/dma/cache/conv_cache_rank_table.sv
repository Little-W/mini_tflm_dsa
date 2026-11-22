// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 三个存储体的异或值表示替换来源；同地址写入依次保留填充、提示和命中。
module conv_cache_rank_table #(
  parameter int p_depth = 128,
  parameter int p_addr_width = $clog2(p_depth)
) (
  input wire logic clk,
  input wire logic i_clear_en,
  input wire logic [p_addr_width-1:0] i_clear_addr,
  input wire logic i_write_en,
  input wire logic i_fill_valid, i_hint_valid, i_hit_valid,
  input wire logic [p_addr_width-1:0] i_fill_addr, i_hint_addr, i_hit_addr,
  input wire logic i_read_en,
  input wire logic [p_addr_width-1:0] i_read_addr,
  output logic [1:0] o_read_data
);
  logic [2:0] bank_i_wr_en;
  logic [2:0][p_addr_width-1:0] bank_i_wr_addr;
  logic [2:0][1:0] bank_i_wr_data;
  logic [2:0][2:0][1:0] bank_o_rd_data;
  logic [2:0][p_addr_width-1:0] bank_i_rd_addr [3];
  logic bank_i_wr_mask;
  logic [2:0] bank_i_rd_en;

  assign bank_i_wr_mask = 1'b1;
  assign bank_i_rd_en = 3'b111;

  // 共享清空阶段逐行建立确定的异或初值，缓存有效位继续控制行的可用性。
  assign bank_i_wr_en[0] = i_clear_en || (i_write_en && i_fill_valid);
  assign bank_i_wr_en[1] = i_clear_en || (i_write_en && i_hint_valid &&
    !(i_fill_valid && i_fill_addr == i_hint_addr));
  assign bank_i_wr_en[2] = i_clear_en || (i_write_en && i_hit_valid &&
    !(i_fill_valid && i_fill_addr == i_hit_addr) && !(i_hint_valid && i_hint_addr == i_hit_addr));
  assign bank_i_wr_addr[0] = i_clear_en ? i_clear_addr : i_fill_addr;
  assign bank_i_wr_addr[1] = i_clear_en ? i_clear_addr : i_hint_addr;
  assign bank_i_wr_addr[2] = i_clear_en ? i_clear_addr : i_hit_addr;

  // 每个存储体读取候选行和另外两个写端口的地址，写入前消去原有来源值。
  assign bank_i_rd_addr[0][0] = i_read_addr;
  assign bank_i_rd_addr[0][1] = i_hint_addr;
  assign bank_i_rd_addr[0][2] = i_hit_addr;
  assign bank_i_rd_addr[1][0] = i_read_addr;
  assign bank_i_rd_addr[1][1] = i_fill_addr;
  assign bank_i_rd_addr[1][2] = i_hit_addr;
  assign bank_i_rd_addr[2][0] = i_read_addr;
  assign bank_i_rd_addr[2][1] = i_fill_addr;
  assign bank_i_rd_addr[2][2] = i_hint_addr;
  assign bank_i_wr_data[0] = i_clear_en ? 2'd0 : bank_o_rd_data[1][1] ^ bank_o_rd_data[2][1];
  assign bank_i_wr_data[1] = i_clear_en ? 2'd0 : 2'd1 ^ bank_o_rd_data[0][1] ^ bank_o_rd_data[2][2];
  assign bank_i_wr_data[2] = i_clear_en ? 2'd0 : 2'd2 ^ bank_o_rd_data[0][2] ^ bank_o_rd_data[1][2];
  for (genvar bank=0; bank<3; bank++) begin : g_bank
    regfile #(
      .p_data_width(2), .p_depth(p_depth), .p_addr_width(p_addr_width),
      .p_write_unit(2), .p_read_ports(3), .p_sync_read(1'b0)
    ) u_storage (
      .clk(clk), .i_wr_en(bank_i_wr_en[bank]), .i_wr_addr(bank_i_wr_addr[bank]),
      .i_wr_data(bank_i_wr_data[bank]), .i_wr_mask(bank_i_wr_mask),
      .i_rd_en(bank_i_rd_en), .i_rd_addr(bank_i_rd_addr[bank]), .o_rd_data(bank_o_rd_data[bank])
    );
  end

  // 同步输出读取写入前的来源，暂停读取时保持原值。
  always_ff @(posedge clk) begin
    if (i_read_en)
      o_read_data <= bank_o_rd_data[0][0] ^ bank_o_rd_data[1][0] ^ bank_o_rd_data[2][0];
  end
endmodule

`default_nettype wire
