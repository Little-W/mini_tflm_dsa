// SPDX-License-Identifier: Apache-2.0
module producer_proof #(parameter int p_size=16)(
 input logic clk, rst_n, i_start, i_send_allowed, i_data_allowed, i_flush,
 input logic i_load_start, i_row_valid, i_row_slot, i_load_done, i_done_slot, i_discard,
 input logic [$clog2(p_size)-1:0] i_row_idx,
 input logic i_weight_resident, i_ia_done, i_ia_valid, i_ps_ready, i_ps_done,
 input logic i_advance, i_quant_ready, i_fifo_full, i_oa_done, i_done_ready
);
 // 发送允许和参数可用条件保持任意，驻留模式在初始化边沿保存。
 localparam int p_count_width=$clog2(p_size+1);
 wire sa_ready, init_weight, send_weight, weight_commit;
 wire buf_valid, buf_done, buf_store, buf_discard_ready, buf_load_ready;
 wire signed [0:0] row_data[p_size], weight_data[p_size];
 wire cache_flush=i_flush && sa_ready;
 wire send_start=i_send_allowed && send_weight && buf_valid;
 logic weight_done, weight_store;
 logic resident;
 logic [p_count_width-1:0] loaded_rows;
 for(genvar c=0;c<p_size;c++)begin:g_row_data
  assign row_data[c]='0;
 end
 kernel_loader_buffer #(.DATA_WIDTH(1),.SIZE(p_size)) u_buffer (
  .clk(clk),.rst_n(rst_n),.cache_flush(cache_flush),.discard_head(i_discard),
  .load_start(i_load_start),.load_slot_id(),.row_valid(i_row_valid),.row_slot(i_row_slot),
  .row_idx(i_row_idx),.row_data(row_data),.load_done(i_load_done),.done_slot(i_done_slot),
  .send_start(send_start),.load_ready(buf_load_ready),.load_commit(),.load_commit_slot(),
  .discard_ready(buf_discard_ready),.weight_data_valid(buf_valid),
  .weight_sending_done(buf_done),.store_weight_req(buf_store),.weight_out(weight_data)
 );
 always_ff @(posedge clk)begin
  if(!rst_n)resident<=1'b0;
  else if(u_control.current_state==4'b0001)resident<=i_weight_resident;
  // 连续帧开始时前一发送已完成；普通任务可以在接收时清空缓冲控制。
  if(rst_n && i_start && sa_ready && !cache_flush)
   assume(!u_buffer.send_active && !u_buffer.send_pending && !u_buffer.send_prefetch && !buf_store && !weight_store && !u_control.shadow_inflight);
 end
 always_ff @(posedge clk or negedge rst_n) begin
  if(!rst_n)begin weight_done<=1'b0;weight_store<=1'b0;end
  else if(cache_flush)begin weight_done<=1'b0;weight_store<=1'b0;end
  else begin weight_done<=buf_done;weight_store<=buf_store;end
 end
 npu_controller #(.SIZE(p_size),.BUS_WIDTH(64),.REG_WIDTH(32)) u_control (
  .clk(clk),.rst_n(rst_n),.calc_start(i_start),.cfg_16bits_ia(1'b0),
  .cfg_tiling_error(1'b0),.cfg_dataflow_mode(1'b0),.sa_ready(sa_ready),
  .lhs_base(32'h1000),.rhs_base(32'h2000),.dst_base(32'h3000),.bias_base(32'd0),
  .q_mult_pt(32'd0),.q_shift_pt(32'd0),.use_per_channel(1'b0),
  .k(32'd48),.n(32'd33),.m(32'd51),
  .lhs_row_stride_b(32'd33),.dst_row_stride_b(32'd51),.rhs_col_stride_b(32'd33),
  .init_cfg_ia(),.init_cfg_weight(init_weight),.init_cfg_bias(),.init_cfg_requant(),.init_cfg_oa(),.use_16bits(),
  .partial_sum_calc_over(i_ps_done),.partial_sum_advance_ready(i_advance),.tile_calc_over(1'b0),
  .send_ia_trigger(),.ia_sending_done(i_ia_done),.ia_data_valid(i_ia_valid),.ps_frame_ready(i_ps_ready),
  .weight_commit(weight_commit),.send_weight_trigger(send_weight),
  .weight_sending_done(weight_done),.weight_data_valid(buf_valid && i_data_allowed),.weight_resident(resident),
  .bias_valid(1'b1),.bias_sleep(1'b1),.quant_params_valid(i_quant_ready),.fifo_full_flag(i_fifo_full),
  .oa_calc_over(i_oa_done),.done_valid(),.done_ready(i_done_ready),.err_code()
 );
 always_ff @(posedge clk)begin
  if(!rst_n || cache_flush) loaded_rows<='0;
  else begin
   if(weight_commit) loaded_rows<=weight_store ? p_count_width'(1) : '0;
   else if(weight_store && loaded_rows<p_count_width'(p_size)) loaded_rows<=loaded_rows+1'b1;
  end
 end
 always_comb if(rst_n && !cache_flush)begin
  assert(loaded_rows<=p_count_width'(p_size));
  if(u_buffer.send_active || u_buffer.send_pending || u_buffer.send_prefetch || buf_store || weight_store)
   assert(u_control.shadow_inflight);
  if(u_buffer.send_active) assert(loaded_rows>=((u_buffer.emit_col_idx<(p_size-3)) ? p_count_width'(p_size-3-u_buffer.emit_col_idx) : p_count_width'(0)));
  if(buf_done) assert(buf_store && weight_store && loaded_rows>=p_count_width'(p_size-2));
  if(u_control.shadow_ready && u_control.current_state!=0 && u_control.current_state!=1) assert(loaded_rows==p_count_width'(p_size));
  if(weight_done) assert(weight_store && loaded_rows>=p_count_width'(p_size-1));
  if(weight_commit)assert(loaded_rows==p_count_width'(p_size));
 end
endmodule
