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
  parameter int p_max_cols=16
) (
  input wire logic clk,rst_n,configure,enable,
  input wire logic req_valid,
  output logic req_ready,
  input wire logic [31:0] req_p0,req_q0,req_cols,
  input wire logic [TAG_W-1:0] req_tag,
  output logic rsp_valid,
  input wire logic rsp_ready,
  output logic [TAG_W-1:0] rsp_tag,
  output logic [COL_W-1:0] rsp_col,
  output logic signed [15:0] rsp_data[WINDOW_LANES],
  output logic [WINDOW_LANES-1:0] rsp_mask,
  output logic rsp_last,rsp_error,busy,
  output logic frontend_valid,frontend_active,
  input wire logic frontend_ready,
  output logic [31:0] frontend_p0,frontend_q0,frontend_cols,
  output logic frontend_cols_valid,
  input wire logic frontend_rsp_valid,
  output logic frontend_rsp_ready,
  input wire logic [COL_W-1:0] frontend_rsp_col,
  input wire logic signed [15:0] frontend_rsp_data[WINDOW_LANES],
  input wire logic [WINDOW_LANES-1:0] frontend_rsp_mask,
  input wire logic frontend_rsp_last,frontend_error);
  logic descriptor_i_wr_en;
  logic [PTR_W-1:0] descriptor_i_wr_addr;
  logic [2:0][31:0] descriptor_i_wr_data;
  logic [0:0] descriptor_i_wr_mask, descriptor_i_rd_en;
  logic [0:0][PTR_W-1:0] descriptor_i_rd_addr;
  logic [2:0][0:0][31:0] descriptor_o_rd_data;
  logic cols_valid[DEPTH];
  logic [TAG_W-1:0] tags[DEPTH];
  logic [PTR_W-1:0] head,tail,present;
  logic [COUNT_W-1:0] count,next_count;
  logic count_increment, count_decrement, next_busy;
  logic active,failed,accept,retire,launch,response_fire;
  logic descriptor_available,descriptor_prepared,descriptor_read_available;
  logic [PTR_W-1:0] descriptor_read_index;
  logic descriptor_forward,descriptor_forward_valid;
  logic [2:0][31:0] descriptor_forward_data;
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
  assign present=active ? increment(head) : head;
  assign descriptor_available=count>(active ? COUNT_W'(1) : COUNT_W'(0));
  // 准备项始终占用队列位置，显式非空条件使空闲配置与前端发送保持互斥。
  assign frontend_valid=enable && !configure && !failed && !frontend_error && busy &&
    (!active || retire) && descriptor_prepared;
  assign frontend_rsp_ready=active && rsp_ready;
  assign launch=frontend_valid && frontend_ready;
  // 发送当前准备项的同时读取下一项，连续单拍窗口可以逐周期接收。
  // 同周期接收的新条目直接保存到返回寄存器，存储器继续保持先读后写语义。
  assign descriptor_read_index=launch ? increment(present) : present;
  assign descriptor_read_available=launch ?
      count>(active ? COUNT_W'(2) : COUNT_W'(1)) : descriptor_available;
  assign descriptor_forward=accept && !descriptor_read_available && descriptor_read_index==tail;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      descriptor_prepared<=1'b0;
      descriptor_forward_valid<=1'b0;
    end else if (configure) begin
      descriptor_prepared<=1'b0;
      descriptor_forward_valid<=1'b0;
    end else begin
      descriptor_prepared<=descriptor_read_available || descriptor_forward;
      descriptor_forward_valid<=descriptor_forward;
    end
  end
  always_ff @(posedge clk) begin
    if (descriptor_forward) descriptor_forward_data<=descriptor_i_wr_data;
  end
  // 三个描述符字段共用接收和读取事件，同步读端口保存当前准备项。
  assign descriptor_i_wr_en = rst_n && accept;
  assign descriptor_i_wr_addr = tail;
  assign descriptor_i_wr_data[0] = req_p0;
  assign descriptor_i_wr_data[1] = req_q0;
  assign descriptor_i_wr_data[2] = req_cols;
  assign descriptor_i_wr_mask = 1'b1;
  assign descriptor_i_rd_en = descriptor_read_available;
  assign descriptor_i_rd_addr[0] = descriptor_read_index;
  for (genvar field_index = 0; field_index < 3; field_index++) begin : g_descriptor
    regfile #(
      .p_data_width(32), .p_depth(DEPTH), .p_addr_width(PTR_W),
      .p_write_unit(32), .p_read_ports(1), .p_sync_read(1'b1), .p_ram_style("block")
    ) u_value (
      .clk(clk), .i_wr_en(descriptor_i_wr_en), .i_wr_addr(descriptor_i_wr_addr),
      .i_wr_data(descriptor_i_wr_data[field_index]), .i_wr_mask(descriptor_i_wr_mask),
      .i_rd_en(descriptor_i_rd_en), .i_rd_addr(descriptor_i_rd_addr),
      .o_rd_data(descriptor_o_rd_data[field_index])
    );
  end
  assign frontend_p0 = descriptor_forward_valid ? descriptor_forward_data[0] : descriptor_o_rd_data[0][0];
  assign frontend_q0 = descriptor_forward_valid ? descriptor_forward_data[1] : descriptor_o_rd_data[1][0];
  assign frontend_cols = descriptor_forward_valid ? descriptor_forward_data[2] : descriptor_o_rd_data[2][0];
  always_ff @(posedge clk) begin
    if (descriptor_forward) frontend_cols_valid <= req_cols>0 && req_cols<=32'(p_max_cols);
    else if (descriptor_read_available) frontend_cols_valid <= cols_valid[descriptor_read_index];
  end
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
      head<=0;tail<=0;count<=0;active<=0;failed<=0;

    end else if (configure) begin
      head<=0;tail<=0;count<=0;active<=0;failed<=0;

    end else begin
      count<=next_count;

      if (accept) begin
        tags[tail]<=req_tag;
        // 列范围在请求接收时计算，与对应描述符占用同一个队列位置。
        cols_valid[tail]<=req_cols>0 && req_cols<=32'(p_max_cols);
        tail<=increment(tail);
      end
      if (retire) begin head<=increment(head);active<=0;end
      if (launch) active<=1;
      if (frontend_error) failed<=1;

    end
  end
`ifdef NPU_SIM_ASSERT
  initial assert(DEPTH>=2 && TAG_W>=1);
  initial forever @(posedge clk) if(rst_n) begin
    assert(count<=COUNT_W'(DEPTH));
    if(configure) assert(count==0 && !active);
    if(frontend_rsp_valid && active && !rsp_error) assert(rsp_mask!=0);
    if(retire) assert(count!=0);
    if(launch) assert(count>(active ? COUNT_W'(1) : COUNT_W'(0)));
  end
`endif
endmodule

`default_nettype wire
