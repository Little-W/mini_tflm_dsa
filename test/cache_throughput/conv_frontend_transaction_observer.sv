// SPDX-License-Identifier: Apache-2.0
// 记录完整前端的描述符、缓存请求及输出握手，供固定输入的逐周期比较使用。
module conv_frontend_transaction_observer;
  bit enabled;
  longint unsigned cycle;
  initial enabled = $test$plusargs("FRONTEND_TRANSACTION_TRACE");
  always @(posedge conv_im2col_frontend.clk) begin
    if (!conv_im2col_frontend.rst_n) cycle = 0;
    else begin
      cycle++;
      if (enabled) begin
        $display("FRONTEND_TRANSACTION cycle=%0d tile=%b%b p=%h q=%h rows=%h cols=%h slot=%h state=%h operation=%h request=%b%b pending=%b cancel=%b addr=%h index=%h index_valid=%b epoch=%h retire=%h progress=%h preview=%b response=%b%b write=%b%b last=%b mask=%h",
          cycle, conv_im2col_frontend.tile_valid, conv_im2col_frontend.tile_ready,
          conv_im2col_frontend.tile_p0, conv_im2col_frontend.tile_q0,
          conv_im2col_frontend.tile_rows, conv_im2col_frontend.tile_cols,
          conv_im2col_frontend.tile_slot, conv_im2col_frontend.state,
          conv_im2col_frontend.operation_state, conv_im2col_frontend.cache_port_valid,
          conv_im2col_frontend.cache_port_ready, conv_im2col_frontend.request_pending,
          conv_im2col_frontend.request_cancel, conv_im2col_frontend.request_addr_q,
          conv_im2col_frontend.request_index_q, conv_im2col_frontend.request_index_valid_q,
          conv_im2col_frontend.request_epoch_q, conv_im2col_frontend.request_retire,
          conv_im2col_frontend.request_progress_q, conv_im2col_frontend.preview_valid_q,
          conv_im2col_frontend.cache_rsp_valid, conv_im2col_frontend.cache_rsp_ready,
          conv_im2col_frontend.wr_valid, conv_im2col_frontend.wr_ready,
          conv_im2col_frontend.wr_last, conv_im2col_frontend.wr_mask);
      end
    end
  end
endmodule

bind conv_im2col_frontend conv_frontend_transaction_observer transaction_observer();
