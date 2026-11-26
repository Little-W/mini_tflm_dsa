// SPDX-License-Identifier: Apache-2.0
// 窗口描述符按接收顺序共用图像前端，标签保持所属目标直至末次响应完成。
`default_nettype none
module conv_window_queue #(
  parameter int DEPTH=4,
  parameter int TAG_W=2,
  parameter int COL_W=4,
  parameter int WINDOW_LANES=4,
  parameter int PTR_W=(DEPTH<=1 ? 1 : $clog2(DEPTH)),
  parameter int COUNT_W=$clog2(DEPTH+1),
  parameter int p_max_cols=16,
  parameter int p_frontend_outstanding=1,
  parameter int p_active_width=$clog2(p_frontend_outstanding+1)
) (
  input wire logic clk /* 窗口队列工作时钟。 */,rst_n /* 低有效异步复位。 */,configure /* 清空窗口队列、在途计数和错误状态。 */,enable /* 允许接收窗口请求并向前端发送描述符。 */,
  input wire logic req_valid, // 输入窗口描述符有效。
  output logic req_ready, // 窗口队列可接收输入描述符。
  input wire logic [31:0] req_p0 /* 窗口起始输出位置。 */,req_q0 /* 窗口起始归约位置。 */,req_cols /* 窗口请求的输出列数。 */,
  input wire logic [TAG_W-1:0] req_tag, // 请求所属目标的标签。
  output logic rsp_valid, // 队首窗口的返回数据或错误有效。
  input wire logic rsp_ready, // 下游可接收当前窗口返回。
  output logic [TAG_W-1:0] rsp_tag, // 当前返回所属请求的标签。
  output logic [COL_W-1:0] rsp_col, // 当前返回在窗口内的列索引。
  output logic signed [15:0] rsp_data[WINDOW_LANES], // 当前返回各通道的有符号数据。
  output logic [WINDOW_LANES-1:0] rsp_mask, // 当前返回各通道的数据有效掩码。
  output logic rsp_last /* 当前返回为窗口最后一拍。 */,rsp_error /* 当前窗口返回错误。 */,busy /* 队列中仍有尚未完成返回的窗口。 */,
  output logic frontend_valid /* 已准备的窗口描述符可发送到前端。 */,frontend_active /* 已有窗口在前端执行或等待末拍返回。 */,
  input wire logic frontend_ready, // 前端可接收当前窗口描述符。
  output logic [31:0] frontend_p0 /* 发送到前端的起始输出位置。 */,frontend_q0 /* 发送到前端的起始归约位置。 */,frontend_cols /* 发送到前端的窗口列数。 */,
  output logic frontend_cols_valid, // 已准备窗口的列数处于支持范围。
  input wire logic frontend_rsp_valid, // 前端返回数据有效。
  output logic frontend_rsp_ready, // 当前在途窗口可接收前端返回。
  input wire logic [COL_W-1:0] frontend_rsp_col, // 前端返回数据在窗口内的列索引。
  input wire logic signed [15:0] frontend_rsp_data[WINDOW_LANES], // 前端返回各通道的有符号数据。
  input wire logic [WINDOW_LANES-1:0] frontend_rsp_mask, // 前端返回各通道的数据有效掩码。
  input wire logic frontend_rsp_last /* 前端返回当前窗口的最后一拍。 */,frontend_error /* 前端报告窗口处理错误。 */);
  logic descriptor_i_wr_en;
  logic [PTR_W-1:0] descriptor_i_wr_addr;
  logic [2:0][31:0] descriptor_i_wr_data;
  logic [0:0] descriptor_i_wr_mask;
  logic [1:0] descriptor_i_rd_en;
  logic [1:0][PTR_W-1:0] descriptor_i_rd_addr;
  logic [2:0][1:0][31:0] descriptor_read_data;
  logic cols_valid[DEPTH];
  logic [TAG_W-1:0] tags[DEPTH];
  logic [PTR_W-1:0] head,tail,present;
  logic [COUNT_W-1:0] count,next_count;
  logic count_increment, count_decrement, next_busy;
  logic active,failed,accept,retire,response_fire;
  (* keep = 1 *) logic launch;
  logic [p_active_width-1:0] active_count;
  logic active_retire;
  logic frontend_slot_available, frontend_tail_accept;
  logic descriptor_available, descriptor_multiple;
  logic descriptor_prepared, descriptor_read_available;
  logic descriptor_prepared_nxt;
  logic [PTR_W-1:0] descriptor_read_index;
  logic descriptor_forward;
  logic descriptor_current_cols_valid, descriptor_next_cols_valid;
  logic descriptor_request_cols_valid, descriptor_cols_value, descriptor_cols_selected;
  logic [1:0] descriptor_cols_candidates;
  logic [2:0][31:0] descriptor_prepared_data;
  logic [2:0][31:0] descriptor_prepared_value, descriptor_selected_value;
  logic descriptor_data_enable, descriptor_selected_enable;
  // 未知控制期间保存完整读地址语义；二态电路中该状态恒为零。
  logic descriptor_unknown_seen = 1'b0;
  logic [14:0] descriptor_controls;
  assign descriptor_controls = {rst_n,configure,enable,req_valid,rsp_ready,frontend_ready,
      frontend_rsp_valid,frontend_rsp_last,frontend_error,failed,descriptor_available,
      descriptor_multiple,accept,frontend_valid,launch};
  function automatic logic [PTR_W-1:0] increment(input logic [PTR_W-1:0] value);
    return value==PTR_W'(DEPTH-1) ? '0 : value+1'b1;
  endfunction
  // 占用标志与计数在同一边沿更新，描述符选择直接读取寄存结果。
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      busy <= 1'b0;
    end else if (configure) begin
      busy <= 1'b0;
    end else begin
      busy <= next_busy;
    end
  end
  assign active = |active_count;
  assign active_retire = retire && active;
  assign frontend_active=active;
  assign rsp_valid=count!=0 && (failed || frontend_error || (active && frontend_rsp_valid));
  assign rsp_error=failed || frontend_error;
  assign rsp_tag=tags[head];
  assign rsp_col=rsp_error ? '0 : frontend_rsp_col;
  assign rsp_mask=rsp_error ? '0 : frontend_rsp_mask;
  assign rsp_last=rsp_error || frontend_rsp_last;
  // 每个响应保持前端通道宽度，尾部有效元素由掩码指定。
  for (genvar lane=0;lane<WINDOW_LANES;lane++) begin : g_response_lane
    assign rsp_data[lane]=rsp_error ? 16'sd0 : frontend_rsp_data[lane];
  end
  assign response_fire=rsp_valid && rsp_ready;
  assign retire=response_fire && rsp_last;
  assign req_ready=enable && !configure && !failed && !frontend_error &&
                   (count<COUNT_W'(DEPTH) || retire);
  assign accept=req_valid && req_ready;
  // 已发送窗口可以分别占用前端和输出寄存器，队首保持到外部末拍接收。
  // 待发送位置随启动事件保存，与完成队首和在途计数分别更新。
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) present <= '0;
    else if (configure) present <= '0;
    else if (launch || (retire && !active)) present <= increment(present);
  end
  assign descriptor_available = count > COUNT_W'(active_count);
  assign descriptor_multiple = {1'b0, count} >
    ((COUNT_W+1)'(active_count) + (COUNT_W+1)'(1));
  // 容量与正常末拍接收并行判断，已准备描述符在末级取得发送资格。
  assign frontend_slot_available = active_count < p_active_width'(p_frontend_outstanding);
  assign frontend_tail_accept = (|count) && frontend_rsp_valid && rsp_ready && frontend_rsp_last;
  always_comb begin
    frontend_valid = enable && !configure && !failed && !frontend_error && busy &&
        (frontend_slot_available || frontend_tail_accept) && descriptor_prepared;
    // 未知状态保留响应有效、末拍与在途资格的逐项传播。
    case (^{enable, configure, failed, frontend_error, busy, active_count, count,
             frontend_rsp_valid, rsp_ready, frontend_rsp_last, descriptor_prepared})
      1'b0, 1'b1: begin end
      default: frontend_valid = enable && !configure && !failed && !frontend_error && busy &&
          (frontend_slot_available || active_retire) && descriptor_prepared;
    endcase
  end
  assign frontend_rsp_ready=active && rsp_ready;
  assign launch=frontend_valid && frontend_ready;
  // 发送当前准备项的同时读取下一项，连续单拍窗口可以逐周期接收。
  // 同周期接收的新条目与存储读数在准备寄存器之前选择。
  assign descriptor_read_index=launch ? increment(present) : present;
  // 两个数量比较独立完成，启动事件只决定是否消耗唯一的待发送项。
  assign descriptor_read_available = descriptor_multiple || (!launch && descriptor_available);
  // 没有未发送描述符时，读取位置就是接收位置；新接收数据直接写入准备寄存器。
  assign descriptor_forward = accept && !descriptor_read_available;
  conv_window_prepared_flag u_prepared_flag (
    .i_configure(configure), .i_multiple(descriptor_multiple), .i_available(descriptor_available),
    .i_frontend_valid(frontend_valid), .i_frontend_ready(frontend_ready), .i_accept(accept),
    .o_prepared(descriptor_prepared_nxt)
  );
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      descriptor_prepared<=1'b0;
    end else begin
      descriptor_prepared <= descriptor_prepared_nxt;
    end
  end
  // 未知的发送或复位控制可能暂时改变准备字段与存储项的对应关系。
  // 后续周期持续采用完整读取语义，重新配置或复位时恢复空队列状态。
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) descriptor_unknown_seen <= 1'b0;
    else if (configure) descriptor_unknown_seen <= 1'b0;
    else begin
      case (^descriptor_controls)
        1'b0, 1'b1: begin end
        default: descriptor_unknown_seen <= 1'b1;
      endcase
    end
  end
  // 正常等待时准备字段已经对应当前项，发送后读取下一项；错误阶段读取当前项。
  conv_window_data_enable u_data_enable (
    .i_available(descriptor_available), .i_multiple(descriptor_multiple),
    .i_accept(accept), .i_launch(launch), .i_failed(failed), .o_enable(descriptor_selected_enable)
  );
  for (genvar field_index = 0; field_index < 3; field_index++) begin : g_prepared_value
    conv_window_data_select u_select (
      .i_available(descriptor_available), .i_multiple(descriptor_multiple), .i_launch(launch),
      .i_read(descriptor_read_data[field_index][0]), .i_request(descriptor_i_wr_data[field_index]),
      .o_value(descriptor_selected_value[field_index])
    );
  end
  always_comb begin
    descriptor_prepared_value = descriptor_selected_value;
    descriptor_data_enable = descriptor_selected_enable;
    case ({descriptor_unknown_seen,^descriptor_controls})
      2'b00, 2'b01: begin end
      default: begin
        descriptor_prepared_value = descriptor_prepared_data;
        descriptor_data_enable = 1'b0;
        if (descriptor_forward) begin
          descriptor_prepared_value = descriptor_i_wr_data;
          descriptor_data_enable = 1'b1;
        end else if (descriptor_read_available) begin
          for (int field_index = 0; field_index < 3; field_index++)
            descriptor_prepared_value[field_index] = descriptor_read_data[field_index][1];
          descriptor_data_enable = 1'b1;
        end
      end
    endcase
  end
  always_ff @(posedge clk) begin
    if (descriptor_data_enable) descriptor_prepared_data <= descriptor_prepared_value;
  end
  // 小容量描述符存储异步读取，统一的准备寄存器直接驱动前端字段。
  assign descriptor_i_wr_en = rst_n && accept;
  assign descriptor_i_wr_addr = tail;
  assign descriptor_i_wr_data[0] = req_p0;
  assign descriptor_i_wr_data[1] = req_q0;
  assign descriptor_i_wr_data[2] = req_cols;
  assign descriptor_i_wr_mask = 1'b1;
  assign descriptor_i_rd_en = 2'b11;
  // 第一个端口提前选择正常预取或错误恢复地址，发送事件只作用于末级选择。
  assign descriptor_i_rd_addr[0] = failed ? present : increment(present);
  // 第二个端口保留未知控制的读取语义，二态综合删除该端口。
  assign descriptor_i_rd_addr[1] = descriptor_read_index;
  for (genvar field_index = 0; field_index < 3; field_index++) begin : g_descriptor
    regfile #(
      .p_data_width(32), .p_depth(DEPTH), .p_addr_width(PTR_W),
      .p_write_unit(32), .p_read_ports(2), .p_sync_read(1'b0), .p_ram_style("distributed")
    ) u_value (
      .clk(clk), .i_wr_en(descriptor_i_wr_en), .i_wr_addr(descriptor_i_wr_addr),
      .i_wr_data(descriptor_i_wr_data[field_index]), .i_wr_mask(descriptor_i_wr_mask),
      .i_rd_en(descriptor_i_rd_en), .i_rd_addr(descriptor_i_rd_addr),
      .o_rd_data(descriptor_read_data[field_index])
    );
  end
  assign frontend_p0 = descriptor_prepared_data[0];
  assign frontend_q0 = descriptor_prepared_data[1];
  assign frontend_cols = descriptor_prepared_data[2];
  // 当前项与下一项的列资格并行读取，晚到发送事件只选择一位结果。
  assign descriptor_current_cols_valid = cols_valid[present];
  assign descriptor_next_cols_valid = cols_valid[increment(present)];
  conv_window_cols_range #(.p_max_cols(p_max_cols)) u_cols_range (
    .i_columns(req_cols), .o_valid(descriptor_request_cols_valid)
  );
  conv_window_cols_candidates u_cols_candidates (
    .i_available(descriptor_available), .i_multiple(descriptor_multiple), .i_accept(accept),
    .i_request(descriptor_request_cols_valid), .i_current(descriptor_current_cols_valid),
    .i_next(descriptor_next_cols_valid), .i_saved(frontend_cols_valid), .o_value(descriptor_cols_candidates)
  );
  conv_window_cols_select u_cols_select (
    .i_frontend_valid(frontend_valid), .i_frontend_ready(frontend_ready),
    .i_candidate(descriptor_cols_candidates), .o_value(descriptor_cols_selected)
  );
  // 发送与保持两种结果包含原有写入资格，启动事件仅选择最终保存值。
  always_comb begin
    descriptor_cols_value = descriptor_cols_selected;
`ifndef SYNTHESIS
    if ((^{descriptor_available, descriptor_multiple, frontend_valid, frontend_ready, accept}) === 1'bx) begin
      descriptor_cols_value = frontend_cols_valid;
      if (descriptor_forward) descriptor_cols_value = descriptor_request_cols_valid;
      else if (descriptor_read_available)
        descriptor_cols_value = launch ? descriptor_next_cols_valid : descriptor_current_cols_valid;
    end
`endif
  end
  always_ff @(posedge clk) frontend_cols_valid <= descriptor_cols_value;
  // 加一与减一的传播条件直接取自当前计数，各结果位并行更新。
  assign count_increment = accept && !retire;
  assign count_decrement = retire && !accept;
  assign next_count[0] = count[0] ^ (accept ^ retire);
  for (genvar bit_index = 1; bit_index < COUNT_W; bit_index++) begin : g_count_bit
    assign next_count[bit_index] = count[bit_index] ^
      ((count_increment && (&count[bit_index-1:0])) ||
       (count_decrement && !(|count[bit_index-1:0])));
  end
  // 非空结果使用当前计数的边界标志，与计数数据的翻转并行计算。
  always_comb begin
    next_busy = |count;
    case ({accept,retire})
      2'b10: next_busy = !(&count);
      2'b01: next_busy = count != COUNT_W'(1);
      default: ;
    endcase
  end
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      head<=0;tail<=0;count<=0;active_count<=0;failed<=0;

    end else if (configure) begin
      head<=0;tail<=0;count<=0;active_count<=0;failed<=0;

    end else begin
      count<=next_count;

      if (accept) begin
        tags[tail]<=req_tag;
        // 列范围在请求接收时计算，与对应描述符占用同一个队列位置。
        cols_valid[tail]<=descriptor_request_cols_valid;
        tail<=increment(tail);
      end
      if (retire) head<=increment(head);
      case ({launch, active_retire})
        2'b10: active_count <= active_count + p_active_width'(1);
        2'b01: active_count <= active_count - p_active_width'(1);
        default: ;
      endcase
      if (frontend_error) failed<=1;

    end
  end
`ifdef NPU_SIM_ASSERT
  initial assert(DEPTH>=2 && TAG_W>=1 && p_frontend_outstanding>=1 && p_frontend_outstanding<=DEPTH);
  initial forever @(posedge clk) if(rst_n) begin
    assert(count<=COUNT_W'(DEPTH));
    assert(active_count<=p_active_width'(p_frontend_outstanding));
    assert(COUNT_W'(active_count)<=count);
    if(configure) assert(count==0 && !active);
    if(frontend_rsp_valid && active && !rsp_error) assert(rsp_mask!=0);
    if(retire) assert(count!=0);
    if(launch) assert(count>COUNT_W'(active_count));
  end
`endif
endmodule

`default_nettype wire
