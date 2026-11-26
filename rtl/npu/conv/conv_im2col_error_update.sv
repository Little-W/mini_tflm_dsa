// SPDX-License-Identifier: Apache-2.0
`default_nettype none
// 汇总配置、描述符和输出传输状态，生成下一周期需要保存的错误标志。
module conv_im2col_error_update (
  input wire logic [26:0] i_state, // 当前运行状态。
  input wire logic i_error, // 已保存的累计错误标志。
  input wire logic i_configuration_complete, // 配置检查结果已经可用。
  input wire logic i_configuration_ok, // 配置检查通过。
  input wire logic i_cfg_fire, // 当前周期接收新配置。
  input wire logic i_basic_valid, // 新配置的基本参数有效。
  input wire logic i_tile_commit, // 当前周期接收描述符。
  input wire logic i_tile_invalid, // 待接收描述符参数无效。
  input wire logic i_stream_error, // 运行请求返回错误。
  input wire logic i_stream_accept, // 当前运行输出被接收。
  output logic o_error, // 下一周期的累计错误标志。
  output logic o_tile_error // 下一周期的分块错误脉冲。
);
  import conv_im2col_frontend_pkg::*;
  logic saved_error, operation_failure, invalid_operation;
  logic [1:0] parallel_value;
  assign saved_error = i_configuration_complete ? !i_configuration_ok : i_error;
  assign operation_failure = !i_state[$clog2(DESCRIPTOR_CHECK)] && i_stream_error;
  assign invalid_operation = !(|i_state);
  // 运行错误先完成输出接收选择，配置和描述符提交只参与最终结果选择。
  conv_im2col_error_select u_final (
    .i_configuration(i_cfg_fire), .i_commit(i_tile_commit),
    .i_configuration_value({1'b0, !i_basic_valid}),
    .i_commit_value({i_tile_invalid, saved_error || i_tile_invalid}),
    .i_operation_value({operation_failure,
        saved_error || operation_failure || (invalid_operation && !i_stream_accept)}),
    .o_value(parallel_value)
  );
  always_comb begin
    o_error = i_error;
    o_tile_error = 1'b0;
    case (^{i_state, i_error, i_configuration_complete, i_configuration_ok,
             i_cfg_fire, i_basic_valid, i_tile_commit, i_tile_invalid,
             i_stream_error, i_stream_accept})
      1'b0, 1'b1: {o_tile_error, o_error} = parallel_value;
      default: begin
        // 未知控制值按各状态的过程式优先级选择。
        if (i_configuration_complete) o_error = !i_configuration_ok;
        case (1'b1)
          i_cfg_fire: begin o_error=!i_basic_valid; end
          i_tile_commit: if (i_tile_invalid) begin o_error=1'b1; o_tile_error=1'b1; end
          i_state[$clog2(DESCRIPTOR_CHECK)]: ;
          i_stream_error: begin o_error=1; o_tile_error=1; end
          i_stream_accept: ;
          (!i_tile_commit && i_stream_error !== 1'b1 && i_stream_accept !== 1'b1 &&
          (i_state[$clog2(WAIT_WORD)] || i_state[$clog2(STREAM)] || i_state[$clog2(ZERO_STREAM)])): ;
          i_state[$clog2(P_HISTORY)]: ;
          i_state[$clog2(P_DECODE)]: ;
          i_state[$clog2(P_START)]: ;
          i_state[$clog2(P_WAIT)]: ;
          i_state[$clog2(Q_DECODE)]: ;
          i_state[$clog2(Q_START)]: ;
          i_state[$clog2(Q_WAIT)]: ;
          i_state[$clog2(K_DECODE)]: ;
          i_state[$clog2(K_START)]: ;
          i_state[$clog2(K_WAIT)]: ;
          i_state[$clog2(COORD)]: ;
          i_state[$clog2(COORD_SUM)]: ;
          i_state[$clog2(COORD_BORROW)]: ;
          i_state[$clog2(COORD_PAD)]: ;
          i_state[$clog2(ADDRESS)]: ;
          i_state[$clog2(ADDRESS_PIXEL)]: ;
          i_state[$clog2(ADDRESS_PRODUCT)]: ;
          i_state[$clog2(ADDRESS_MERGE)]: ;
          i_state[$clog2(ADDRESS_BASE)]: ;
          i_state[$clog2(ADDRESS_CHANNEL)]: ;
          i_state[$clog2(ADDRESS_MATCH)]: ;
          i_state[$clog2(FETCH)]: ;
          (i_state[$clog2(IDLE)] && !i_cfg_fire && !i_tile_commit): ;
          default: begin o_error=1; end
        endcase
      end
    endcase
  end
endmodule
`default_nettype wire
