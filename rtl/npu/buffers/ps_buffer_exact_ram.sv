// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 精确深度的同步单写单读存储，环形地址由外层控制器按 DEPTH 回绕。
module ps_buffer_exact_ram #(
    parameter int DEPTH=16, DATA_WIDTH=512, ADDR_WIDTH=$clog2(DEPTH)
)(input wire logic clk /* 工作时钟 */, ena /* 写端口总使能 */, enb /* 同步读端口使能 */, wea /* 写端口数据更新使能 */,
  input wire logic [ADDR_WIDTH-1:0] addra /* 写端口的存储字地址 */, addrb /* 读端口的存储字地址 */,
  input wire logic [DATA_WIDTH-1:0] dia /* 写端口输入数据 */,
  output logic [DATA_WIDTH-1:0] dob /* 同步读端口返回的数据 */);
  logic storage_i_wr_en, storage_i_rd_en;
  logic [ADDR_WIDTH-1:0] storage_i_wr_addr, storage_i_rd_addr;
  logic [DATA_WIDTH-1:0] storage_i_wr_data, storage_o_rd_data;
  assign storage_i_wr_en = ena && wea;
  assign storage_i_wr_addr = addra;
  assign storage_i_wr_data = dia;
  assign storage_i_rd_en = enb;
  assign storage_i_rd_addr = addrb;
  assign dob = storage_o_rd_data;
`ifdef ASIC_SRAM
  logic [DATA_WIDTH-1:0] storage_i_wr_mask;
  assign storage_i_wr_mask = '1;
  smic40_sram_1r1w #(.DATA_WIDTH(DATA_WIDTH), .DEPTH(DEPTH), .ADDR_WIDTH(ADDR_WIDTH)) u_sram (
    .clk(clk), .write_enable(storage_i_wr_en), .write_address(storage_i_wr_addr),
    .write_data(storage_i_wr_data), .write_mask(storage_i_wr_mask),
    .read_enable(storage_i_rd_en), .read_address(storage_i_rd_addr), .read_data(storage_o_rd_data)
  );
`else
  logic storage_i_wr_mask;
  assign storage_i_wr_mask = 1'b1;
  regfile #(
    .p_data_width(DATA_WIDTH), .p_depth(DEPTH), .p_addr_width(ADDR_WIDTH),
    .p_write_unit(DATA_WIDTH)
  ) u_storage (
    .clk(clk), .i_wr_en(storage_i_wr_en), .i_wr_addr(storage_i_wr_addr),
    .i_wr_data(storage_i_wr_data), .i_wr_mask(storage_i_wr_mask),
    .i_rd_en(storage_i_rd_en), .i_rd_addr(storage_i_rd_addr), .o_rd_data(storage_o_rd_data)
  );
`endif

endmodule

`default_nettype wire
