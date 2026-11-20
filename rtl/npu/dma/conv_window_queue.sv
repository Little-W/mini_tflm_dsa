// SPDX-License-Identifier: Apache-2.0
// Ordered window descriptors share one image frontend. Each accepted tag owns
// its destination until the final response is consumed.
module conv_window_queue #(
  parameter int DEPTH=4,
  parameter int TAG_W=2,
  parameter int COL_W=4,
  parameter int PTR_W=(DEPTH<=1 ? 1 : $clog2(DEPTH)),
  parameter int COUNT_W=$clog2(DEPTH+1),
  parameter int p_max_cols=16
) (
  input logic clk,rst_n,configure,enable,
  input logic req_valid,
  output logic req_ready,
  input logic [31:0] req_p0,req_q0,req_cols,
  input logic [TAG_W-1:0] req_tag,
  output logic rsp_valid,
  input logic rsp_ready,
  output logic [TAG_W-1:0] rsp_tag,
  output logic [COL_W-1:0] rsp_col,
  output logic signed [15:0] rsp_data[4],
  output logic [3:0] rsp_mask,
  output logic rsp_last,rsp_error,busy,
  output logic frontend_valid,frontend_active,
  input logic frontend_ready,
  output logic [31:0] frontend_p0,frontend_q0,frontend_cols,
  output logic frontend_cols_valid,
  input logic frontend_rsp_valid,
  output logic frontend_rsp_ready,
  input logic [COL_W-1:0] frontend_rsp_col,
  input logic signed [15:0] frontend_rsp_data[4],
  input logic [3:0] frontend_rsp_mask,
  input logic frontend_rsp_last,frontend_error);
  logic [31:0] p0[DEPTH],q0[DEPTH],cols[DEPTH];
  logic cols_valid[DEPTH];
  logic [TAG_W-1:0] tags[DEPTH];
  logic [PTR_W-1:0] head,tail,present;
  logic [COUNT_W-1:0] count,next_count;
  logic active,failed,accept,retire,launch,response_fire;
  logic descriptor_available,descriptor_prepared;
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
      busy <= next_count != COUNT_W'(0);
    end
  end
  assign frontend_active=active;
  assign rsp_valid=count!=0 && (failed || frontend_error || (active && frontend_rsp_valid));
  assign rsp_error=failed || frontend_error;
  assign rsp_tag=tags[head];
  assign rsp_col=rsp_error ? '0 : frontend_rsp_col;
  assign rsp_mask=rsp_error ? '0 : frontend_rsp_mask;
  assign rsp_last=rsp_error || frontend_rsp_last;
  for (genvar lane=0;lane<4;lane++)
    assign rsp_data[lane]=rsp_error ? 16'sd0 : frontend_rsp_data[lane];
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
  // 当前窗口执行时提前保存下一项描述符，队列索引变化在此结束组合计算。
  // 已准备项仍占用原队列位置，直至对应的最后一次响应被接收。
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) descriptor_prepared<=1'b0;
    else if (configure) descriptor_prepared<=1'b0;
    else descriptor_prepared<=descriptor_available && !launch;
  end
  always_ff @(posedge clk) begin
    if (descriptor_available) begin
      frontend_p0<=p0[present];
      frontend_q0<=q0[present];
      frontend_cols<=cols[present];
      frontend_cols_valid<=cols_valid[present];
    end
  end
  always_comb begin
    next_count=count;
    case ({accept,retire})
      2'b10:next_count=count+1'b1;
      2'b01:next_count=count-1'b1;
      default:;
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
        p0[tail]<=req_p0;q0[tail]<=req_q0;cols[tail]<=req_cols;tags[tail]<=req_tag;
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
