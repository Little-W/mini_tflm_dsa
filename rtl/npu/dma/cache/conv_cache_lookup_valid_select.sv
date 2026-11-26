// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 缓存有效位来源选择：各候选先完成存储读取及写入转发，再选择一位结果。
// 结果沿用调用方现有的查询寄存边沿，单项请求队列不增加处理周期。
module conv_cache_lookup_valid_select (
  input wire logic rst_n,                         // 复位电平，仅用于保持原有四态传播
  input wire logic i_cfg_accept,                  // 当前周期接收新配置
  input wire logic [1:0] i_foreground_state,       // 前台状态，编码一表示缺失处理
  input wire logic i_request_occupied,            // 单项请求队列已占用
  input wire logic i_request_fire,                // 当前工作请求被处理
  input wire logic i_input_valid,                 // 正式输入或预读输入可供读取
  input wire logic i_preview_selected,            // 输入来源选择预读请求
  input wire logic [3:0] i_source_valid,           // 队首、正式输入、缺失请求和预读的有效位
  input wire logic i_address_valid,               // 按完整地址选择得到的四态参考结果
  input wire logic i_saved_valid,                 // 配置或复位含未知值时使用的已保存结果
  output logic o_valid                           // 当前查询边沿需要保存的有效位
);
  //! 0. 辅助定义
  //! -----------

  localparam logic [1:0] p_miss_state = 2'd1;
  logic read_input;
  logic [3:0] source_select;
  logic [1:0] source_index;
  logic selected_valid;

  //! 1. 读取来源选择
  //! ---------------

  // 缺失请求优先使用需求地址；否则队列空闲或当前项消费时读取新输入。
  assign read_input = !i_request_occupied ||
      (i_foreground_state != p_miss_state && i_request_fire && i_input_valid);
  assign source_select[0] = i_foreground_state != p_miss_state && !read_input;
  assign source_select[1] = i_foreground_state != p_miss_state &&
      read_input && !i_preview_selected;
  assign source_select[2] = i_foreground_state == p_miss_state;
  assign source_select[3] = i_foreground_state != p_miss_state &&
      read_input && i_preview_selected;
  assign source_index[0] = i_foreground_state != p_miss_state && read_input;
  assign source_index[1] = i_foreground_state == p_miss_state ||
      (read_input && i_preview_selected);
  // 存储内容含未知位时按来源直接索引，保留被选中位的高阻态。
  always_comb begin
    selected_valid = i_source_valid[source_index];
    case (^i_source_valid)
      1'b0, 1'b1: selected_valid = |(source_select & i_source_valid);
      default: begin end
    endcase
  end

  //! 2. 有效位输出
  //! -------------

  // 已知控制只选择读出后的单比特；未知控制沿用完整地址的传播结果。
  always_comb begin
    o_valid = i_address_valid;
    case (^{i_foreground_state, i_request_occupied, i_request_fire,
             i_input_valid, i_preview_selected})
      1'b0, 1'b1: o_valid = selected_valid;
      default: begin end
    endcase
    case (^{rst_n, i_cfg_accept})
      1'b0, 1'b1: begin end
      default: o_valid = i_saved_valid;
    endcase
  end
endmodule

`default_nettype wire
