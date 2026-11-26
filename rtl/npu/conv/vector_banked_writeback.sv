// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 按总线字接收结果，两个字节银行组分别保存待发数据与当前事务。
module vector_banked_writeback #(
  parameter int TILE = 16,
  parameter int BUS_WIDTH = 64,
  parameter int COUNT_WIDTH = $clog2(4*TILE+1),
  parameter bit p_coalesce_bytes_only = 1'b1
) (
  input  wire logic clk /* 模块工作时钟。 */, rst_n /* 低有效复位输入。 */,
  input  wire logic request_valid, // 本次向量结果写回请求有效。
  output logic request_ready, // 能够接收本次向量结果及写回描述符。
  input  wire logic [31:0] request_address, // 本次结果的目标字节地址。
  input  wire logic [COUNT_WIDTH-1:0] request_bytes, // 本次结果包含的有效字节数。
  input  wire logic request_byte_output, // 每个三十二位结果仅输出其低八位。
  input  wire logic [32*TILE-1:0] result_words, // 按通道排列的三十二位计算结果。
  input  wire logic request_coalesce, // 允许与相邻地址的待写结果合并。
  input  wire logic request_last, // 该请求为当前结果序列的最后一项。
  input  wire logic flush, // 将当前已缓存的结果发送到写入器。
  output logic busy /* 仍有待发送结果或在途写事务。 */, done /* 当前结果序列的写回完成。 */, error /* 当前结果序列发生写回错误。 */,
  output logic wr_req /* 向共享 DMA 仲裁器请求写入资源。 */, wr_start /* 在获得授权后启动本次写事务。 */,
  input  wire logic wr_granted, // 共享 DMA 仲裁器授予写入资源。
  output logic [31:0] wr_base_addr /* 当前写事务的起始字节地址。 */, wr_row_stride /* 当前写事务相邻行的字节间隔。 */, wr_rows_to_write /* 当前写事务需要输出的行数。 */,
  output logic [7:0] wr_burst_len_m1, // 当前写事务突发拍数减一。
  output logic [BUS_WIDTH-1:0] src_wdata, // 当前待发送的总线数据。
  output logic [BUS_WIDTH/8-1:0] src_wmask, // 当前总线数据的有效字节掩码。
  output logic src_wvalid, // 当前待发送的总线数据有效。
  input  wire logic src_wready /* 下游写入器允许接收本拍数据。 */, wr_done /* 下游写入器完成当前事务。 */, wr_error /* 下游写入器报告当前事务错误。 */
);
  //! 0. 内部定义
  //! ----------------

  localparam int BUS_BYTES = BUS_WIDTH/8;
  localparam int BUS_SHIFT = $clog2(BUS_BYTES);
  localparam int CAPACITY = 4*TILE;
  localparam int GROUP_COUNT = (CAPACITY+BUS_BYTES-1)/BUS_BYTES;
  localparam int ROW_WIDTH = GROUP_COUNT<=1 ? 1 : $clog2(GROUP_COUNT);
  localparam int BANK_DEPTH = 1 << (ROW_WIDTH+1);
  localparam int ARITH_WIDTH = COUNT_WIDTH>BUS_SHIFT ? COUNT_WIDTH+1 : BUS_SHIFT+2;
  typedef enum logic [1:0] {IDLE, REQUEST, DATA, RESPONSE} state_t;
  state_t c_st, n_st;
  logic pending_slot, payload_slot;
  logic [31:0] pending_address, payload_address;
  logic [32:0] pending_end_address;
  logic [32:0] request_end_address;
  logic [COUNT_WIDTH-1:0] pending_bytes, total_bytes, written_bytes;
  logic pending_last;
  logic [7:0] payload_burst_length;
  logic [ROW_WIDTH:0] beats_remaining;
  logic [BUS_BYTES-1:0] first_mask, last_mask, final_mask;
  logic [BUS_SHIFT-1:0] final_count;
  logic [BUS_SHIFT-1:0] lane_offset, first_bank;
  logic [COUNT_WIDTH:0] appended_bytes;
  logic append_compatible, append_fits, append_allowed;
  logic request_prepared, prepared_compatible, prepared_fits;
  logic publish_fire, request_fire, data_fire;
  logic copy_active, copy_word_fire, copy_cancel, copy_last;
  logic [ROW_WIDTH-1:0] copy_source_q, copy_row_q;
  logic [BUS_SHIFT-1:0] copy_offset_q;
  logic [ROW_WIDTH-1:0] source_group, destination_row;
  logic [BUS_SHIFT-1:0] destination_offset;
  logic [ARITH_WIDTH-1:0] copy_remaining, remaining, available, beat_bytes, pending_span;
  logic [BUS_SHIFT:0] copy_count;
  logic [BUS_WIDTH-1:0] source_word, bank_word;
  logic [BUS_WIDTH-1:0] store_rotation [0:BUS_SHIFT];
  logic [BUS_WIDTH-1:0] output_rotation [0:BUS_SHIFT];
  logic [ROW_WIDTH-1:0] read_row [BUS_BYTES];
  logic read_enable;

  //! 1. 接收资格与传输数量
  //! ------------------------

  assign request_end_address = {1'b0, request_address} + 33'(request_bytes);
  assign appended_bytes = {1'b0, pending_bytes} + {1'b0, request_bytes};
  assign append_compatible = pending_bytes==0 ||
      (request_coalesce && (!p_coalesce_bytes_only || request_byte_output) &&
       !pending_end_address[32] && request_address==pending_end_address[31:0]);
  assign append_fits = appended_bytes <= (COUNT_WIDTH+1)'(CAPACITY);
  assign copy_cancel = copy_active && (!request_valid || flush);
  assign publish_fire = (c_st==IDLE || (c_st==RESPONSE && wr_done && !wr_error)) &&
      pending_bytes!=0 && (!copy_active || copy_cancel) &&
      (pending_last || flush || pending_bytes==COUNT_WIDTH'(CAPACITY) ||
       (request_valid && request_prepared && (!prepared_compatible || !prepared_fits)));
  assign append_allowed = request_prepared && !flush && !pending_last &&
      prepared_compatible && prepared_fits && !publish_fire;
  assign source_group = copy_active ? copy_source_q : '0;
  assign destination_row = copy_active ? copy_row_q : ROW_WIDTH'(pending_bytes >> BUS_SHIFT);
  assign destination_offset = copy_active ? copy_offset_q : BUS_SHIFT'(pending_bytes);
  assign copy_remaining = ARITH_WIDTH'(request_bytes) -
      (ARITH_WIDTH'(source_group) << BUS_SHIFT);
  assign copy_count = copy_remaining > ARITH_WIDTH'(BUS_BYTES) ?
      (BUS_SHIFT+1)'(BUS_BYTES) : (BUS_SHIFT+1)'(copy_remaining);
  assign copy_last = copy_remaining <= ARITH_WIDTH'(BUS_BYTES);
  assign copy_word_fire = request_valid && append_allowed;
  // 最后一个总线字存入银行时确认请求，生产方在此之前保存地址、长度和数据。
  assign request_ready = append_allowed && copy_last;
  assign request_fire = request_valid && request_ready;
  assign data_fire = c_st==DATA && src_wready;
  assign remaining = ARITH_WIDTH'(total_bytes) - ARITH_WIDTH'(written_bytes);
  assign available = ARITH_WIDTH'(BUS_BYTES) - ARITH_WIDTH'(lane_offset);
  assign beat_bytes = remaining<available ? remaining : available;
  assign pending_span = ARITH_WIDTH'(pending_address[BUS_SHIFT-1:0]) +
      ARITH_WIDTH'(pending_bytes) + ARITH_WIDTH'(BUS_BYTES-1);
  assign read_enable = publish_fire || (data_fire && remaining>available);

  //! 2. 按银行保存与读取数据
  //! --------------------------

  // 源地址的低位为固定通道号，每个银行只选择当前组中的一个字节。
  for (genvar bank=0; bank<BUS_BYTES; bank++) begin : g_source_bank
    logic [7:0] word_group [1<<ROW_WIDTH];
    logic [7:0] byte_group [1<<ROW_WIDTH];
    logic [7:0] source_bytes [1<<ROW_WIDTH];
    for (genvar group=0; group<(1<<ROW_WIDTH); group++) begin : g_group
      localparam int INDEX = group*BUS_BYTES+bank;
      if (INDEX<CAPACITY) begin : g_word
        assign word_group[group] = result_words[8*INDEX+:8];
      end else begin : g_word_padding
        assign word_group[group] = '0;
      end
      if (INDEX<TILE) begin : g_byte
        assign byte_group[group] = result_words[32*INDEX+:8];
      end else begin : g_byte_padding
        assign byte_group[group] = '0;
      end
      // 固定分组内选择输出格式，再按源组号读取，保留未知选择的逐位传播。
      assign source_bytes[group] = request_byte_output ? byte_group[group] : word_group[group];
    end
    assign source_word[8*bank+:8] = source_bytes[source_group];
  end
  assign store_rotation[0] = source_word;
  for (genvar stage=0; stage<BUS_SHIFT; stage++) begin : g_store_rotation
    localparam int SHIFT_BITS = 8*(1<<stage);
    assign store_rotation[stage+1] = destination_offset[stage] ?
        {store_rotation[stage][BUS_WIDTH-SHIFT_BITS-1:0],
         store_rotation[stage][BUS_WIDTH-1:BUS_WIDTH-SHIFT_BITS]} : store_rotation[stage];
  end
  for (genvar bank=0; bank<BUS_BYTES; bank++) begin : g_storage_bank
    logic [BUS_SHIFT-1:0] source_lane;
    logic [ROW_WIDTH-1:0] write_row, next_read_row;
    logic [ROW_WIDTH:0] write_address, read_address;
    logic write_enable;
    logic [7:0] read_data;
    (* ram_style = "block" *) logic [7:0] memory [0:BANK_DEPTH-1];

    assign source_lane = BUS_SHIFT'(bank) - destination_offset;
    assign write_row = destination_row + ROW_WIDTH'(BUS_SHIFT'(bank)<destination_offset);
    assign write_address = {pending_slot, write_row};
    assign write_enable = copy_word_fire && {1'b0, source_lane}<copy_count;
    assign next_read_row = written_bytes==0 && first_bank!=0 ?
        ROW_WIDTH'(BUS_SHIFT'(bank)<first_bank) : read_row[bank]+ROW_WIDTH'(1);
    assign read_address = publish_fire ? {pending_slot, {ROW_WIDTH{1'b0}}} :
        {payload_slot, next_read_row};
    always_ff @(posedge clk) begin
      if (write_enable) memory[write_address] <= store_rotation[BUS_SHIFT][8*bank+:8];
      if (read_enable) read_data <= memory[read_address];
    end
    assign bank_word[8*bank+:8] = read_data;
    always_ff @(posedge clk) begin
      if (publish_fire) read_row[bank] <= '0;
      else if (data_fire && remaining>available) read_row[bank] <= next_read_row;
    end
  end

  //! 3. 更新接收与事务状态
  //! ------------------------

  // 请求保持有效期间先保存地址连续性与容量检查，复制循环只使用寄存结果。
  // 提交或发布会改变待发缓冲的边界，随后为下一项请求重新计算接收资格。
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) request_prepared <= 1'b0;
    else if (flush || !request_valid || request_fire || publish_fire)
      request_prepared <= 1'b0;
    else if (!request_prepared) request_prepared <= 1'b1;
  end
  always_ff @(posedge clk) begin
    if (!request_prepared && request_valid && !flush && !publish_fire) begin
      prepared_compatible <= append_compatible;
      prepared_fits <= append_fits;
    end
  end
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      copy_active <= 1'b0;
      copy_source_q <= '0;
      copy_row_q <= '0;
      copy_offset_q <= '0;
    end else if (copy_cancel || publish_fire) begin
      copy_active <= 1'b0;
    end else if (copy_word_fire) begin
      copy_active <= !copy_last;
      copy_source_q <= source_group + ROW_WIDTH'(1);
      copy_row_q <= destination_row + ROW_WIDTH'(1);
      copy_offset_q <= destination_offset;
    end
  end
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      pending_slot <= 1'b0;
      pending_address <= '0;
      pending_end_address <= '0;
      pending_bytes <= '0;
      pending_last <= 1'b0;
    end else if (publish_fire) begin
      pending_slot <= !pending_slot;
      pending_bytes <= '0;
      pending_last <= 1'b0;
    end else if (request_fire) begin
      if (pending_bytes==0) pending_address <= request_address;
      pending_end_address <= request_end_address;
      pending_bytes <= appended_bytes[COUNT_WIDTH-1:0];
      pending_last <= request_last || !request_coalesce || (p_coalesce_bytes_only && !request_byte_output);
    end
  end
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) c_st <= IDLE;
    else c_st <= n_st;
  end
  always_comb begin
    n_st = c_st;
    case (c_st)
      IDLE: if (publish_fire) n_st = REQUEST;
      REQUEST: if (wr_granted) n_st = DATA;
      DATA: if (data_fire && remaining<=available) n_st = RESPONSE;
      RESPONSE: if (wr_done) n_st = publish_fire ? REQUEST : IDLE;
      default: n_st = IDLE;
    endcase
  end
  always_ff @(posedge clk) begin
    if (publish_fire) begin
      payload_slot <= pending_slot;
      payload_address <= {pending_address[31:BUS_SHIFT], {BUS_SHIFT{1'b0}}};
      payload_burst_length <= 8'((pending_span >> BUS_SHIFT)-1'b1);
      beats_remaining <= (ROW_WIDTH+1)'(pending_span >> BUS_SHIFT);
      src_wmask <= first_mask;
      last_mask <= final_mask;
      total_bytes <= pending_bytes;
      written_bytes <= '0;
      lane_offset <= pending_address[BUS_SHIFT-1:0];
      first_bank <= BUS_SHIFT'(0)-pending_address[BUS_SHIFT-1:0];
    end else if (data_fire) begin
      written_bytes <= written_bytes + COUNT_WIDTH'(beat_bytes);
      lane_offset <= '0;
      beats_remaining <= beats_remaining - (ROW_WIDTH+1)'(1);
      src_wmask <= beats_remaining==(ROW_WIDTH+1)'(2) ? last_mask : '1;
    end
  end

  //! 4. 输出与握手
  //! ----------------

  assign output_rotation[0] = bank_word;
  for (genvar stage=0; stage<BUS_SHIFT; stage++) begin : g_output_rotation
    localparam int SHIFT_BITS = 8*(1<<stage);
    assign output_rotation[stage+1] = first_bank[stage] ?
        {output_rotation[stage][SHIFT_BITS-1:0], output_rotation[stage][BUS_WIDTH-1:SHIFT_BITS]} :
        output_rotation[stage];
  end
  assign src_wdata = output_rotation[BUS_SHIFT];
  assign src_wvalid = c_st==DATA;
  assign final_count = pending_address[BUS_SHIFT-1:0] + BUS_SHIFT'(pending_bytes);
  for (genvar lane=0; lane<BUS_BYTES; lane++) begin : g_byte_mask
    logic [BUS_SHIFT-1:0] distance;
    assign distance = BUS_SHIFT'(lane)-pending_address[BUS_SHIFT-1:0];
    assign first_mask[lane] = BUS_SHIFT'(lane)>=pending_address[BUS_SHIFT-1:0] &&
        ARITH_WIDTH'(pending_bytes)>ARITH_WIDTH'(distance);
    assign final_mask[lane] = final_count==0 || BUS_SHIFT'(lane)<final_count;
  end
  assign busy = c_st!=IDLE || pending_bytes!=0 || copy_active || request_prepared;
  assign done = c_st==RESPONSE && wr_done;
  assign error = done && wr_error;
  assign wr_req = c_st==REQUEST;
  assign wr_start = wr_req && wr_granted;
  assign wr_base_addr = payload_address;
  assign wr_row_stride = 32'd0;
  assign wr_rows_to_write = 32'd1;
  assign wr_burst_len_m1 = payload_burst_length;

`ifdef NPU_SIM_ASSERT
  initial begin
    assert(TILE>=1 && BUS_BYTES>=4 && (BUS_BYTES&(BUS_BYTES-1))==0);
    assert(COUNT_WIDTH>0 && COUNT_WIDTH<=16);
  end
  always @(posedge clk) if (rst_n) begin
    assert(!(publish_fire && copy_word_fire));
    if (copy_word_fire) assert(appended_bytes<=(COUNT_WIDTH+1)'(CAPACITY));
    if (request_fire) assert(request_prepared && copy_last);
    if (request_prepared && request_valid && !flush) begin
      assert(prepared_compatible == append_compatible);
      assert(prepared_fits == append_fits);
    end
    if (c_st!=IDLE && pending_bytes!=0) assert(payload_slot!=pending_slot);
    if (data_fire) begin
      assert(beat_bytes!=0);
      assert(beats_remaining!=0);
      for (int lane=0;lane<BUS_BYTES;lane++) begin
        assert(src_wmask[lane] == (BUS_SHIFT'(lane)>=lane_offset &&
            remaining>ARITH_WIDTH'(BUS_SHIFT'(lane)-lane_offset)));
      end
    end
  end
`endif
endmodule

`default_nettype wire
