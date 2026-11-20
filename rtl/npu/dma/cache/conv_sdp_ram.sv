// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 缓存按32位字读取，以总线宽度和字节掩码写入；存储资源由综合工具选择。
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
  localparam int p_words = WRITE_WIDTH / 32;
  localparam int p_select_width = (p_words <= 1) ? 1 : $clog2(p_words);
  localparam int p_bank_shift = $clog2(p_words);
  localparam int p_bank_depth = DEPTH / p_words;
  localparam int p_bank_addr_width = (p_bank_depth <= 1) ? 1 : $clog2(p_bank_depth);
  logic [p_select_width-1:0] read_bank_q;
  logic [p_words-1:0][31:0] read_words;

  // 数据与所在存储块在同一读取边沿保存，未读取时保留输出。
  always_ff @(posedge clk) begin
    if (rd_en) begin
      read_bank_q <= (p_words == 1) ? '0 : p_select_width'(rd_addr);
    end
  end
  assign rd_data = read_words[read_bank_q];

  for (genvar word = 0; word < p_words; word++) begin : g_bank
    logic storage_i_wr_en, storage_i_rd_en;
    logic [p_bank_addr_width-1:0] storage_i_wr_addr, storage_i_rd_addr;
    logic [31:0] storage_i_wr_data, storage_o_rd_data;
    logic [3:0] storage_i_byte_mask;
    assign storage_i_wr_en = wr_en;
    assign storage_i_wr_addr = p_bank_addr_width'(wr_addr >> p_bank_shift);
    assign storage_i_wr_data = wr_data[word*32 +: 32];
    assign storage_i_byte_mask = wr_strb[word*4 +: 4];
    assign storage_i_rd_en = rd_en;
    assign storage_i_rd_addr = p_bank_addr_width'(rd_addr >> p_bank_shift);
    assign read_words[word] = storage_o_rd_data;
`ifdef ASIC_SRAM
    logic [31:0] storage_i_wr_mask;
    for (genvar byte_lane = 0; byte_lane < 4; byte_lane++) begin : g_byte_mask
      assign storage_i_wr_mask[byte_lane*8 +: 8] = {8{storage_i_byte_mask[byte_lane]}};
    end
    smic40_sram_1r1w #(.DATA_WIDTH(32), .DEPTH(p_bank_depth), .ADDR_WIDTH(p_bank_addr_width)) u_storage (
      .clk(clk), .write_enable(storage_i_wr_en), .write_address(storage_i_wr_addr),
      .write_data(storage_i_wr_data), .write_mask(storage_i_wr_mask),
      .read_enable(storage_i_rd_en), .read_address(storage_i_rd_addr), .read_data(storage_o_rd_data)
    );
`else
    regfile #(
      .p_data_width(32), .p_depth(p_bank_depth), .p_addr_width(p_bank_addr_width),
      .p_write_unit(8), .p_read_ports(1), .p_sync_read(1'b1)
    ) u_storage (
      .clk(clk), .i_wr_en(storage_i_wr_en), .i_wr_addr(storage_i_wr_addr),
      .i_wr_data(storage_i_wr_data), .i_wr_mask(storage_i_byte_mask),
      .i_rd_en(storage_i_rd_en), .i_rd_addr(storage_i_rd_addr), .o_rd_data(storage_o_rd_data)
    );
`endif
  end
`ifdef NPU_SIM_ASSERT
  initial begin
    assert (WRITE_WIDTH >= 32 && WRITE_WIDTH % 32 == 0 &&
            (p_words & (p_words - 1)) == 0 && DEPTH % p_words == 0);
  end
  initial forever @(posedge clk)
    assert (!(rd_en && wr_en && (rd_addr >> p_bank_shift) == (wr_addr >> p_bank_shift)));
`endif
endmodule

`default_nettype wire
