// SPDX-License-Identifier: Apache-2.0
// 检查实际加载器在同一寄存边沿传递装载使能和末行指示。
module bridge_proof(input logic clk,rst_n,i_flush);
 wire store_weight,weight_done;
 logic expected_store,expected_done;
 wire signed [15:0] dma_data[8];
 wire dma_valid[8];
 for(genvar b=0;b<8;b++)begin:g_dma
  assign dma_data[b]='0;
  assign dma_valid[b]=1'b0;
 end
 kernel_loader #(.DATA_WIDTH(16),.SIZE(16),.BUS_WIDTH(64),.REG_WIDTH(32),.COUNT_WIDTH(29)) u_loader (
  .clk(clk),.rst_n(rst_n),.init_cfg(1'b0),.cache_flush(i_flush),
  .load_weight_granted(1'b0),.send_weight_trigger(1'b0),
  .k(32'd48),.n(32'd33),.m(32'd51),.rhs_base(32'h1000),.rhs_row_stride_b(32'd33),
  .rhs_zp(32'd0),.use_16bits(1'b0),.ia_reuse_num(32'd1),.w_reuse_num(32'd1),
  .row_groups(32'd3),.row_tail_tiles(32'd1),.col_groups(32'd4),.col_tail_tiles(32'd1),
  .ext_dma_busy(1'b0),.ext_dma_done(1'b0),.ext_dma_wr_slot(1'b0),.ext_dma_wr_row(4'd0),
  .ext_dma_wr_col_base(4'd0),.ext_dma_wr_data(dma_data),.ext_dma_wr_valid(dma_valid),
  .weight_sending_done(weight_done),.store_weight_req(store_weight)
 );
 always_ff @(posedge clk or negedge rst_n)begin
  if(!rst_n)begin expected_store<=1'b0;expected_done<=1'b0;end
  else if(i_flush)begin expected_store<=1'b0;expected_done<=1'b0;end
  else begin
   expected_store<=u_loader.buf_store_weight_req;
   expected_done<=u_loader.buf_weight_sending_done;
  end
 end
 always_comb begin
  assert(store_weight==expected_store);
  assert(weight_done==expected_done);
 end
endmodule
