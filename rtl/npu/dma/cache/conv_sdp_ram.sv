// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 缓存使用独立读写宽度；地址均以32位字为单位，数据容量保持不变。
module conv_sdp_ram #(
  parameter int DEPTH = 1024,
  parameter int AW = $clog2(DEPTH),
  parameter int WRITE_WIDTH = 32,
  parameter int READ_WIDTH = 32
) (
  input wire logic clk,
  input wire logic rd_en,
  input wire logic [AW-1:0] rd_addr,
  output logic [READ_WIDTH-1:0] rd_data,
  input wire logic wr_en,
  input wire logic [AW-1:0] wr_addr,
  input wire logic [WRITE_WIDTH-1:0] wr_data,
  input wire logic [WRITE_WIDTH/8-1:0] wr_strb
);
  //! 0. 参数与内部信号
  //! ------------------

  localparam int p_words = (WRITE_WIDTH > READ_WIDTH ? WRITE_WIDTH : READ_WIDTH) / 32;
  localparam int p_read_words = READ_WIDTH / 32;
  localparam int p_write_words = WRITE_WIDTH / 32;
  localparam int p_select_width = (p_words <= 1) ? 1 : $clog2(p_words);
  localparam int p_bank_shift = $clog2(p_words);
  localparam int p_write_shift = $clog2(p_write_words);
  localparam int p_bank_depth = DEPTH / p_words;
  localparam int p_bank_addr_width = (p_bank_depth <= 1) ? 1 : $clog2(p_bank_depth);
  logic [p_select_width-1:0] read_bank;
  logic [p_select_width-1:0] read_bank_nxt;
  logic [p_words-1:0][31:0] read_words;

  //! 1. 读取区域选择
  //! ----------------

  // 一次读取覆盖自然地址分组；低位字地址只选择该组中的起始存储块。
  assign read_bank_nxt = p_select_width'(rd_addr) & p_select_width'(p_words-p_read_words);

  //! 2. 同步存储访问
  //! ----------------

  // 数据与读取区域在同一边沿保存，停顿期间保持已经返回的数据。
  always_ff @(posedge clk) begin
    if (rd_en) begin
      read_bank <= read_bank_nxt;
    end
  end

  for (genvar word = 0; word < p_words; word++) begin : g_bank
    logic storage_i_wr_en, storage_i_rd_en;
    logic [p_bank_addr_width-1:0] storage_i_wr_addr, storage_i_rd_addr;
    logic [31:0] storage_i_wr_data, storage_o_rd_data;
    logic [3:0] storage_i_byte_mask;
    // 读取宽度大于写入宽度时，每次写入只更新所属的一组存储块。
    assign storage_i_wr_en = wr_en && ((p_words == p_write_words) ||
      ((p_select_width'(wr_addr) >> p_write_shift) == p_select_width'(word/p_write_words)));
    assign storage_i_wr_addr = p_bank_addr_width'(wr_addr >> p_bank_shift);
    assign storage_i_wr_data = wr_data[(word%p_write_words)*32 +: 32];
    assign storage_i_byte_mask = wr_strb[(word%p_write_words)*4 +: 4];
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

  //! 3. 读取结果选择
  //! ----------------

  // 每个输出字选择对应存储块，选择过程中保留各块完整的32位数据。
  for (genvar output_word = 0; output_word < p_read_words; output_word++) begin : g_read_word
    assign rd_data[output_word*32 +: 32] = read_words[read_bank+p_select_width'(output_word)];
  end
`ifdef NPU_SIM_ASSERT
  initial begin
    assert (WRITE_WIDTH >= 32 && WRITE_WIDTH % 32 == 0 &&
            READ_WIDTH >= 32 && READ_WIDTH % 32 == 0 &&
            (p_write_words & (p_write_words - 1)) == 0 &&
            (p_read_words & (p_read_words - 1)) == 0 && DEPTH % p_words == 0);
  end
  initial forever @(posedge clk)
    assert (!(rd_en && wr_en && (rd_addr >> p_bank_shift) == (wr_addr >> p_bank_shift)));
`endif
endmodule

`default_nettype wire
