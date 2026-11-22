// SPDX-License-Identifier: Apache-2.0
`default_nettype none
// 将结果存入写入队列，连续字节结果可以合并为同一突发。
module vector_writeback #(
  parameter int TILE=16,
  parameter int BUS_WIDTH=64,
  parameter int COUNT_WIDTH=$clog2(4*TILE+1),
  parameter bit p_coalesce_bytes_only=1'b0
)(
  input wire logic clk, rst_n,
  input wire logic request_valid,
  output logic request_ready,
  input wire logic [31:0] request_address,
  input wire logic [COUNT_WIDTH-1:0] request_bytes,
  input wire logic request_byte_output,
  input wire logic [32*TILE-1:0] result_words,
  input wire logic request_coalesce = 1'b0,
  input wire logic request_last = 1'b1,
  input wire logic flush = 1'b0,
  output logic busy, done, error,
  output logic wr_req, wr_start,
  input wire logic wr_granted,
  output logic [31:0] wr_base_addr, wr_row_stride, wr_rows_to_write,
  output logic [7:0] wr_burst_len_m1,
  output logic [BUS_WIDTH-1:0] src_wdata,
  output logic [BUS_WIDTH/8-1:0] src_wmask,
  output logic src_wvalid,
  input wire logic src_wready, wr_done, wr_error
);
  //! 0. 队列存储与事务状态
  //! -----------------------

  localparam int BUS_BYTES=BUS_WIDTH/8;
  localparam int BUS_SHIFT=$clog2(BUS_BYTES);
  localparam int CAPACITY=4*TILE;
  localparam int GROUP_COUNT=((CAPACITY+BUS_BYTES-1)>>BUS_SHIFT)+2;
  localparam int GROUP_INDEX_WIDTH=$clog2(GROUP_COUNT);
  localparam int ARITH_WIDTH=COUNT_WIDTH>BUS_SHIFT ? COUNT_WIDTH+1 : BUS_SHIFT+2;
  typedef enum logic [1:0] {IDLE, REQUEST, DATA, RESPONSE} state_t;
  state_t c_st, n_st;
  logic [31:0] base_address, pending_address;
  logic [COUNT_WIDTH-1:0] total_bytes, written_bytes, pending_bytes;
  logic [BUS_SHIFT-1:0] lane_offset, first_bank;
  logic [7:0] burst_length;
  logic [GROUP_INDEX_WIDTH-1:0] group_index [BUS_BYTES];
  logic [7:0] pending_data [CAPACITY], payload_data [CAPACITY];
  logic [8*CAPACITY-1:0] request_aligned_data;
  logic pending_last, append_compatible, append_fits;
  logic request_fire, publish_fire, data_fire;
  logic [COUNT_WIDTH:0] appended_bytes;
  logic [32:0] pending_end_address;
  (* keep = 1 *) logic [3:0] append_address_byte_equal;
  logic [ARITH_WIDTH-1:0] remaining, available, beat_bytes, pending_span;
  logic [BUS_WIDTH-1:0] bank_bytes;
  logic [BUS_WIDTH-1:0] rotation_stage [BUS_SHIFT+1];

  //! 1. 检查追加条件与生成写入事件
  //! -------------------------------

  assign appended_bytes = {1'b0,pending_bytes}+{1'b0,request_bytes};
  // 各字节独立比较连续地址，最后只归并四个比较结果。
  for (genvar part = 0; part < 4; part++) begin : g_append_address_compare
    assign append_address_byte_equal[part] =
        request_address[part*8+:8] == pending_end_address[part*8+:8];
  end
  assign append_compatible = pending_bytes==0 ||
      (request_coalesce && (!p_coalesce_bytes_only || request_byte_output) &&
       !pending_end_address[32] && (&append_address_byte_equal));
  assign append_fits = appended_bytes <= (COUNT_WIDTH+1)'(CAPACITY);
  // 满队列、末尾标记和地址不连续均使待写数据尽早进入写事务。
  assign publish_fire = (c_st==IDLE || (c_st==RESPONSE && wr_done && !wr_error)) && pending_bytes!=0 &&
      (pending_last || flush || pending_bytes==COUNT_WIDTH'(CAPACITY) ||
       (request_valid && (!append_compatible || !append_fits)));
  // 可追加请求只需检查主动发布条件，地址与容量判断各经过一次组合计算。
  assign request_ready = !pending_last && append_compatible && append_fits &&
      !((c_st==IDLE || (c_st==RESPONSE && wr_done && !wr_error)) && pending_bytes!=0 &&
        (flush || pending_bytes==COUNT_WIDTH'(CAPACITY)));
  assign request_fire = request_valid && request_ready;
  assign data_fire = c_st==DATA && src_wready;
  assign remaining = ARITH_WIDTH'(total_bytes)-ARITH_WIDTH'(written_bytes);
  assign available = ARITH_WIDTH'(BUS_BYTES)-ARITH_WIDTH'(lane_offset);
  assign beat_bytes = remaining<available ? remaining : available;
  assign pending_span = ARITH_WIDTH'(pending_address[BUS_SHIFT-1:0])+
      ARITH_WIDTH'(pending_bytes)+ARITH_WIDTH'(BUS_BYTES-1);

  // 字节合并模式仅旋转 TILE 个有效字节，完整数据字直接装入空队列。
  // 超出 TILE 的字节请求仍以零填充，保留各请求长度对应的输出内容。
  if (p_coalesce_bytes_only && ((TILE & (TILE-1)) == 0)) begin : g_byte_coalescing
    logic [8*TILE-1:0] byte_rotation [0:$clog2(TILE)];
    logic [COUNT_WIDTH:0] byte_end;

    assign byte_end = {1'b0, pending_bytes} + (COUNT_WIDTH+1)'(TILE);
    for (genvar lane=0;lane<TILE;lane++) begin : g_lane
      assign byte_rotation[0][8*lane+:8] = result_words[32*lane+:8];
    end
    for (genvar stage=0;stage<$clog2(TILE);stage++) begin : g_rotation
      localparam int SHIFT_BITS=8*(1<<stage);
      assign byte_rotation[stage+1] = pending_bytes[stage] ?
          {byte_rotation[stage][8*TILE-SHIFT_BITS-1:0],
           byte_rotation[stage][8*TILE-1:8*TILE-SHIFT_BITS]} : byte_rotation[stage];
    end
    for (genvar entry=0;entry<CAPACITY;entry++) begin : g_entry
      assign request_aligned_data[8*entry+:8] = !request_byte_output ? result_words[8*entry+:8] :
          ((COUNT_WIDTH+1)'(entry)<byte_end ? byte_rotation[$clog2(TILE)][8*(entry%TILE)+:8] : 8'd0);
    end
  end else begin : g_general_coalescing
    logic [7:0] request_data [CAPACITY];
    logic [8*CAPACITY-1:0] request_shift [0:$clog2(CAPACITY)];

    for (genvar entry=0;entry<CAPACITY;entry++) begin : g_request_byte
      if (entry<TILE) begin : g_byte_output
        assign request_data[entry] = request_byte_output ? result_words[32*entry+:8] : result_words[8*entry+:8];
      end else begin : g_word_output
        assign request_data[entry] = request_byte_output ? 8'd0 : result_words[8*entry+:8];
      end
      assign request_shift[0][8*entry+:8] = request_data[entry];
    end
    // 低于移位量的位置不会被该请求写入，因此可以直接传递中间数据。
    for (genvar stage=0;stage<$clog2(CAPACITY);stage++) begin : g_request_shift
      localparam int SHIFT_BYTES=1<<stage;
      for (genvar entry=0;entry<CAPACITY;entry++) begin : g_entry
        if (entry>=SHIFT_BYTES) begin : g_in_range
          assign request_shift[stage+1][8*entry+:8] = pending_bytes[stage] ?
              request_shift[stage][8*(entry-SHIFT_BYTES)+:8] : request_shift[stage][8*entry+:8];
        end else begin : g_unused_position
          assign request_shift[stage+1][8*entry+:8] = request_shift[stage][8*entry+:8];
        end
      end
    end
    assign request_aligned_data = request_shift[$clog2(CAPACITY)];
  end

  //! 2. 保存队列数据与推进写事务
  //! -----------------------------

  // 待写队列与当前事务分别保存数据，写出停顿期间当前数据保持不变。
  for (genvar entry=0;entry<CAPACITY;entry++) begin : g_payload_storage
    always_ff @(posedge clk) begin
      if (request_fire && COUNT_WIDTH'(entry)>=pending_bytes &&
          (COUNT_WIDTH+1)'(entry)<appended_bytes) begin
        pending_data[entry] <= request_aligned_data[8*entry+:8];
      end
      if (publish_fire) begin
        payload_data[entry] <= pending_data[entry];
      end
    end
  end
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      pending_bytes <= '0;
      pending_last <= 1'b0;
      pending_address <= '0;
      pending_end_address <= '0;
    end else if (publish_fire) begin
      pending_bytes <= '0;
      pending_last <= 1'b0;
    end else if (request_fire) begin
      if (pending_bytes==0) begin
        pending_address <= request_address;
      end
      // 接收时记录下一连续地址，后续追加检查直接比较已保存的末地址。
      pending_end_address <= {1'b0, request_address} + 33'(request_bytes);
      pending_bytes <= appended_bytes[COUNT_WIDTH-1:0];
      pending_last <= request_last || !request_coalesce || (p_coalesce_bytes_only && !request_byte_output);
    end
  end

  // 状态寄存器与转移条件共同描述接收、数据发送和响应等待的顺序。
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      c_st <= IDLE;
    end else begin
      c_st <= n_st;
    end
  end
  always_comb begin
    n_st = c_st;
    case (c_st)
      IDLE: begin
        if (publish_fire) begin
          n_st = REQUEST;
        end
      end
      REQUEST: begin
        if (wr_granted) begin
          n_st = DATA;
        end
      end
      DATA: begin
        if (data_fire && remaining<=available) begin
          n_st = RESPONSE;
        end
      end
      RESPONSE: begin
        if (wr_done) begin
          n_st = publish_fire ? REQUEST : IDLE;
        end
      end
      default: begin
        n_st = IDLE;
      end
    endcase
  end
  always_ff @(posedge clk) begin
    if (publish_fire) begin
      base_address <= {pending_address[31:BUS_SHIFT],{BUS_SHIFT{1'b0}}};
      burst_length <= 8'((pending_span>>BUS_SHIFT)-1'b1);
      total_bytes <= pending_bytes;
      written_bytes <= '0;
      lane_offset <= pending_address[BUS_SHIFT-1:0];
      first_bank <= BUS_SHIFT'(0)-pending_address[BUS_SHIFT-1:0];
    end else if (data_fire) begin
      written_bytes <= written_bytes+COUNT_WIDTH'(beat_bytes);
      lane_offset <= '0;
    end
  end
  for (genvar bank=0;bank<BUS_BYTES;bank++) begin : g_byte_bank
    logic [7:0] byte_group [GROUP_COUNT];
    for (genvar group=0;group<GROUP_COUNT;group++) begin : g_group
      localparam int PAYLOAD_INDEX=group*BUS_BYTES+bank-BUS_BYTES;
      if (PAYLOAD_INDEX>=0 && PAYLOAD_INDEX<CAPACITY) begin : g_payload
        assign byte_group[group] = payload_data[PAYLOAD_INDEX];
      end else begin : g_padding
        assign byte_group[group] = 8'd0;
      end
    end
    assign bank_bytes[8*bank+:8] = byte_group[group_index[bank]];
    always_ff @(posedge clk) begin
      if (publish_fire) begin
        group_index[bank] <= GROUP_INDEX_WIDTH'(
            (BUS_SHIFT+1)'(pending_address[BUS_SHIFT-1:0]) < (BUS_SHIFT+1)'(BUS_BYTES-bank));
      end else if (data_fire) begin
        group_index[bank] <= group_index[bank]+1'b1;
      end
    end
  end

  //! 3. 生成总线数据与完成状态
  //! ---------------------------

  assign rotation_stage[0] = bank_bytes;
  for (genvar stage=0;stage<BUS_SHIFT;stage++) begin : g_rotation
    localparam int SHIFT_BITS=8*(1<<stage);
    assign rotation_stage[stage+1] = first_bank[stage] ?
        {rotation_stage[stage][SHIFT_BITS-1:0],rotation_stage[stage][BUS_WIDTH-1:SHIFT_BITS]} : rotation_stage[stage];
  end
  assign busy = c_st!=IDLE || pending_bytes!=0;
  assign done = c_st==RESPONSE && wr_done;
  assign error = done && wr_error;
  assign wr_req = c_st==REQUEST;
  assign wr_start = wr_req && wr_granted;
  assign wr_base_addr = base_address;
  assign wr_row_stride = 32'd0;
  assign wr_rows_to_write = 32'd1;
  assign wr_burst_len_m1 = burst_length;
  assign src_wvalid = c_st==DATA;
  assign src_wdata = rotation_stage[BUS_SHIFT];
  for (genvar lane=0;lane<BUS_BYTES;lane++) begin : g_write_mask
    logic [BUS_SHIFT-1:0] byte_distance;

    // 每个字节直接比较剩余长度与距首字节的距离，独立生成写掩码。
    assign byte_distance = BUS_SHIFT'(lane) - lane_offset;
    assign src_wmask[lane] = BUS_SHIFT'(lane) >= lane_offset &&
        remaining > ARITH_WIDTH'(byte_distance);
  end
endmodule
`default_nettype wire
