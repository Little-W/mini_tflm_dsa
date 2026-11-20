// SPDX-License-Identifier: Apache-2.0
module vector_writeback #(
  parameter int TILE=16,
  parameter int BUS_WIDTH=64,
  parameter int COUNT_WIDTH=$clog2(4*TILE+1)
)(
  input wire clk, rst_n,
  input wire request_valid,
  output wire request_ready,
  input wire [31:0] request_address,
  input wire [COUNT_WIDTH-1:0] request_bytes,
  input wire request_byte_output,
  input wire [32*TILE-1:0] result_words,
  output wire busy, done, error,
  output wire wr_req, wr_start,
  input wire wr_granted,
  output wire [31:0] wr_base_addr, wr_row_stride, wr_rows_to_write,
  output wire [7:0] wr_burst_len_m1,
  output wire [BUS_WIDTH-1:0] src_wdata,
  output logic [BUS_WIDTH/8-1:0] src_wmask,
  output wire src_wvalid,
  input wire src_wready, wr_done, wr_error
);
  localparam int BUS_BYTES=BUS_WIDTH/8;
  localparam int BUS_SHIFT=$clog2(BUS_BYTES);
  localparam int GROUP_COUNT=((4*TILE+BUS_BYTES-1)>>BUS_SHIFT)+2;
  localparam int GROUP_INDEX_WIDTH=$clog2(GROUP_COUNT);
  localparam int ARITH_WIDTH=COUNT_WIDTH>BUS_SHIFT ? COUNT_WIDTH+1 : BUS_SHIFT+2;
  typedef enum logic [1:0] {IDLE, REQUEST, DATA, RESPONSE} state_t;
  state_t state;
  logic [31:0] base_address;
  logic [COUNT_WIDTH-1:0] total_bytes, written_bytes;
  logic [BUS_SHIFT-1:0] lane_offset;
  logic byte_output;
  logic [7:0] burst_length;
  logic [BUS_SHIFT-1:0] first_bank;
  logic [GROUP_INDEX_WIDTH-1:0] group_index_q[BUS_BYTES];
  wire [ARITH_WIDTH-1:0] remaining=ARITH_WIDTH'(total_bytes)-ARITH_WIDTH'(written_bytes);
  wire [ARITH_WIDTH-1:0] available=ARITH_WIDTH'(BUS_BYTES)-ARITH_WIDTH'(lane_offset);
  wire [ARITH_WIDTH-1:0] beat_bytes=remaining<available ? remaining : available;
  wire [ARITH_WIDTH-1:0] beat_end=ARITH_WIDTH'(lane_offset)+beat_bytes;
  wire [ARITH_WIDTH-1:0] request_span=ARITH_WIDTH'(request_address[BUS_SHIFT-1:0])+
      ARITH_WIDTH'(request_bytes)+ARITH_WIDTH'(BUS_BYTES-1);
  wire [7:0] payload_bytes[4*TILE];
  for (genvar index=0;index<4*TILE;index++) begin : g_result_byte
    wire [7:0] word_byte=result_words[8*index+:8];
    if (index<TILE) begin : g_byte
      assign payload_bytes[index]=byte_output ? result_words[32*index+:8] : word_byte;
    end else begin : g_word
      assign payload_bytes[index]=byte_output ? 8'd0 : word_byte;
    end
  end
  wire [BUS_WIDTH-1:0] bank_bytes;
  for (genvar bank=0;bank<BUS_BYTES;bank++) begin : g_byte_bank
    wire [7:0] byte_group[GROUP_COUNT];
    for (genvar group=0;group<GROUP_COUNT;group++) begin : g_group
      localparam int PAYLOAD_INDEX=group*BUS_BYTES+bank-BUS_BYTES;
      if (PAYLOAD_INDEX>=0 && PAYLOAD_INDEX<4*TILE) begin : g_payload
        assign byte_group[group]=payload_bytes[PAYLOAD_INDEX];
      end else begin : g_padding
        assign byte_group[group]=8'd0;
      end
    end
    assign bank_bytes[8*bank+:8]=byte_group[group_index_q[bank]];
    // 每个银行保存独立组地址，当前数据选择无需等待偏移比较和加法。
    always_ff @(posedge clk) begin
      if (request_valid && request_ready) begin
        group_index_q[bank] <= GROUP_INDEX_WIDTH'(
            (BUS_SHIFT+1)'(request_address[BUS_SHIFT-1:0]) < (BUS_SHIFT+1)'(BUS_BYTES-bank));
      end else if (state==DATA && src_wready) begin
        group_index_q[bank] <= group_index_q[bank]+1'b1;
      end
    end
  end
`ifdef ASIC_SYNTHESIS
  localparam bit p_fpga_rotation = 1'b0;
`elsif XILINX_FPGA
  localparam bit p_fpga_rotation = 1'b1;
`elsif SYNTHESIS
  localparam bit p_fpga_rotation = 1'b1;
`else
  localparam bit p_fpga_rotation = 1'b0;
`endif
  wire [BUS_WIDTH-1:0] rotation_stage[BUS_SHIFT+1];
  assign rotation_stage[0]=bank_bytes;
  for (genvar stage=0;stage<BUS_SHIFT;stage++) begin : g_rotation
    localparam int SHIFT_BITS=8*(1<<stage);
    if (p_fpga_rotation) begin : g_paired_bits
      // 相邻两位共用本级选择位，各自的两个数据来源由同一查找表选择。
      for (genvar pair_index = 0; pair_index < BUS_WIDTH/2; pair_index++) begin : g_pair
        logic [1:0] select_i_first, select_i_second;
        logic select_i_control, select_i_one, select_o_lower, select_o_upper;
        assign select_i_first = rotation_stage[stage][2*pair_index+:2];
        assign select_i_second = {
          rotation_stage[stage][(2*pair_index+1+SHIFT_BITS) % BUS_WIDTH],
          rotation_stage[stage][(2*pair_index+SHIFT_BITS) % BUS_WIDTH]};
        assign select_i_control = first_bank[stage];
        assign select_i_one = 1'b1;
        assign rotation_stage[stage+1][2*pair_index] = select_o_lower;
        assign rotation_stage[stage+1][2*pair_index+1] = select_o_upper;
        LUT6_2 #(.INIT(64'hff00f0f0ccccaaaa)) u_select (
          .I0(select_i_first[0]), .I1(select_i_second[0]),
          .I2(select_i_first[1]), .I3(select_i_second[1]),
          .I4(select_i_control), .I5(select_i_one),
          .O5(select_o_lower), .O6(select_o_upper)
        );
      end
    end else begin : g_generic_bits
      assign rotation_stage[stage+1] = first_bank[stage] ?
        {rotation_stage[stage][SHIFT_BITS-1:0], rotation_stage[stage][BUS_WIDTH-1:SHIFT_BITS]} :
        rotation_stage[stage];
    end
  end
  assign request_ready=state==IDLE;
  assign busy=state!=IDLE;
  assign done=state==RESPONSE && wr_done;
  assign error=done && wr_error;
  assign wr_req=state==REQUEST;
  assign wr_start=wr_req && wr_granted;
  assign wr_base_addr=base_address;
  assign wr_row_stride=32'd0;
  assign wr_rows_to_write=32'd1;
  assign wr_burst_len_m1=burst_length;
  assign src_wvalid=state==DATA;
  assign src_wdata=rotation_stage[BUS_SHIFT];
  for (genvar lane=0;lane<BUS_BYTES;lane++) begin : g_write_mask
    assign src_wmask[lane]=ARITH_WIDTH'(lane)>=ARITH_WIDTH'(lane_offset) &&
        ARITH_WIDTH'(lane)<beat_end;
  end
  // 调用者在写入响应完成前保持结果存储，本控制器只保存事务元数据。
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) state<=IDLE;
    else case (state)
      IDLE: if (request_valid) state<=REQUEST;
      REQUEST: if (wr_granted) state<=DATA;
      DATA: if (src_wready && remaining<=available) state<=RESPONSE;
      RESPONSE: if (wr_done) state<=IDLE;
      default: state<=IDLE;
    endcase
  end
  always_ff @(posedge clk) begin
    if (request_valid && request_ready) begin
      base_address<={request_address[31:BUS_SHIFT],{BUS_SHIFT{1'b0}}};
      burst_length<=8'((request_span>>BUS_SHIFT)-1'b1);
      total_bytes<=request_bytes;
      written_bytes<='0;
      lane_offset<=request_address[BUS_SHIFT-1:0];
      byte_output<=request_byte_output;
      // 起始银行在整个突发中保持不变。
      first_bank<=BUS_SHIFT'(0)-request_address[BUS_SHIFT-1:0];
    end else if (state==DATA && src_wready) begin
      written_bytes<=written_bytes+COUNT_WIDTH'(beat_bytes);
      lane_offset<='0;
    end
  end
`ifdef NPU_SIM_ASSERT
  initial begin
    assert(TILE>=2 && TILE<=64);
    assert(BUS_BYTES>=2 && (BUS_BYTES&(BUS_BYTES-1))==0);
    forever begin
      @(posedge clk);
      if (rst_n) begin
        if (request_valid && request_ready)
          assert(request_bytes>0 && request_bytes<=4*TILE);
        if (src_wvalid) assert(beat_bytes>0 && beat_bytes<=BUS_BYTES && src_wmask!=0);
      end
    end
  end
`endif
endmodule
