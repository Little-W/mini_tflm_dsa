// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 请求字段与完整匹配结果在同一查询边沿保存，后级直接使用保存的资格。
module conv_cache_snapshot_fields #(
  parameter int p_set_width = 4,
  parameter int p_request_width = 131+p_set_width,
  parameter bit p_capture_range = 1'b0
) (
  input wire logic clk, // 工作时钟
  input wire logic [p_request_width-1:0] i_request, // 待保存的完整请求字段
  input wire logic [1:0] i_fg_state, // 前台请求处理状态
  input wire logic i_request_count /* 单项请求队列占用状态 */, i_req_fire /* 当前请求消费事件 */, i_lookup_input_valid /* 输入请求可供查询 */, i_preview_source_select /* 查询输入选择预读来源 */ , // 单项请求队列占用状态；当前请求消费事件；输入请求可供查询；查询输入选择预读来源
  input wire logic [31:2] i_work_word /* 工作请求字地址 */, i_demand_word /* 缺失请求字地址 */ , // 工作请求字地址；缺失请求字地址
  input wire logic [p_set_width-1:0] i_expected_set, // 缺失请求的目标组号
  input wire logic [31:0] i_base /* 有效地址范围起点 */, i_end /* 有效地址范围终点 */ , // 有效地址范围起点；有效地址范围终点
  input wire logic i_request_range /* 正式输入位于有效范围 */, i_head_range /* 队首请求位于有效范围 */ , // 正式输入位于有效范围；队首请求位于有效范围
`ifndef SYNTHESIS
  input wire logic [4:0] i_reference, // 完整字段计算的四态参考结果
`endif
  output logic [p_request_width-1:0] o_request, // 已保存的完整请求字段
  output logic o_work_word_matches /* 工作请求字地址匹配 */, o_work_snapshot_matches /* 工作请求字地址与组号匹配 */, o_demand_word_matches /* 缺失请求字地址匹配 */ , // 工作请求字地址匹配；工作请求字地址与组号匹配；缺失请求字地址匹配
  output logic o_response_snapshot_ready // 响应快照匹配且地址有效
);
  localparam logic [1:0] p_miss_state = 2'd1;
  logic [p_request_width-2:0] request_fields_q;
  logic was_miss_q, request_fire_q;
  logic [31:0] saved_address;
  logic [31:0] request_address;
  logic [p_set_width-1:0] request_set;
  logic current_demand_equal, current_work_equal, previous_word_equal, set_equal;
  logic work_word_match, work_snapshot_match, demand_word_match, work_range;
  logic [4:0] results;

  always_ff @(posedge clk) begin
    request_fields_q <= i_request[p_request_width-1:1];
    was_miss_q <= i_fg_state == p_miss_state;
    request_fire_q <= i_req_fire;
  end
  assign saved_address = request_fields_q[p_request_width-2-:32];
  assign request_address = i_request[p_request_width-1-:32];
  assign request_set = i_request[3+:p_set_width];
  // 各组三位比较与完整请求字段在同一边沿保存，采样后归并完整相等关系。
  conv_cache_registered_equal #(.p_width(30)) u_current_demand (
    .clk(clk),
    .i_a(request_address[31:2]), .i_b(i_demand_word), .o_equal(current_demand_equal)
  );
  conv_cache_registered_equal #(.p_width(30)) u_current_work (
    .clk(clk),
    .i_a(request_address[31:2]), .i_b(i_work_word), .o_equal(current_work_equal)
  );
  conv_cache_registered_equal #(.p_width(30)) u_previous_words (
    .clk(clk),
    .i_a(i_demand_word), .i_b(i_work_word), .o_equal(previous_word_equal)
  );
  conv_cache_registered_equal #(.p_width(p_set_width)) u_set (
    .clk(clk),
    .i_a(request_set), .i_b(i_expected_set), .o_equal(set_equal)
  );
  // 完整请求已包含同一来源的范围结果，可随其余字段直接保存。
  if (p_capture_range) begin : g_request_range
    logic request_range;
    always_ff @(posedge clk) request_range <= i_request[0];
    assign work_range = request_range;
  end else begin : g_saved_range
    logic [31:0] range_base_q, range_end_q;
    logic preview_range_q, stored_range_q, read_input, below_base, below_end;
    assign read_input = !i_request_count ||
        (i_fg_state != p_miss_state && i_req_fire && i_lookup_input_valid);
    always_ff @(posedge clk) begin
      range_base_q <= i_base;
      range_end_q <= i_end;
      preview_range_q <= read_input && i_preview_source_select;
      stored_range_q <= read_input ? i_request_range : i_head_range;
    end
    conv_cache_snapshot_range u_base (
      .i_address(saved_address), .i_bound(range_base_q), .o_below(below_base)
    );
    conv_cache_snapshot_range u_end (
      .i_address(saved_address), .i_bound(range_end_q), .o_below(below_end)
    );
    assign work_range = preview_range_q ? (!below_base && below_end) : stored_range_q;
  end
  assign work_word_match = !was_miss_q || current_demand_equal;
  assign work_snapshot_match = !was_miss_q || (current_demand_equal && set_equal);
  assign demand_word_match = was_miss_q ? (!request_fire_q || previous_word_equal) :
      (request_fire_q ? current_work_equal : current_demand_equal);
`ifndef SYNTHESIS
  logic unknown_control_q;
  logic [4:0] reference_q;
  always_ff @(posedge clk) begin
    unknown_control_q <= (^{i_fg_state, i_request_count, i_req_fire,
                            i_lookup_input_valid, i_preview_source_select}) === 1'bx;
    reference_q <= i_reference;
  end
`endif
  always_comb begin
    results = {work_snapshot_match && work_range, work_snapshot_match,
               work_word_match, demand_word_match, work_range};
`ifndef SYNTHESIS
    // 未知来源控制继续使用完整描述选择的采样结果。
    if (unknown_control_q) results = reference_q;
`endif
  end
  assign o_request = {request_fields_q, results[0]};
  assign {o_response_snapshot_ready, o_work_snapshot_matches,
          o_work_word_matches, o_demand_word_matches} = results[4:1];
endmodule

`default_nettype wire
