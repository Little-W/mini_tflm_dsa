// SPDX-License-Identifier: Apache-2.0
`ifndef SYNTHESIS
/* verilator lint_off DECLFILENAME */
module vector_engine_observer #(
  parameter int TB_FAILED=0,
  parameter int TB_ADD_MULT=0,
  parameter int TB_ADD_DRAIN=0,
  parameter int TB_ADD_ROUND=0,
  parameter int TB_ADD_ROUND_WAIT=0,
  parameter int TB_ADD_STORE=0,
  parameter int TB_ADD_SUM=0,
  parameter int TB_CONFIGURE=0,
  parameter int TB_DONE=0,
  parameter int TB_EXECUTE=0,
  parameter int TB_EXECUTE_COMMIT=0,
  parameter int TB_IDLE=0,
  parameter int TB_LOAD_WAIT=0,
  parameter int TB_POOL_LOAD_WAIT=0,
  parameter int TB_SOFT_LUT_WAIT=0,
  parameter int TB_SOFT_RUN=0
)(
  input wire hw_clk,
  input wire hw_dma_cfg_ready,
  input wire hw_rd_granted,
  input wire hw_rd_req,
  input wire hw_rst_n,
  input wire hw_soft_done,
  input wire hw_soft_lut_req_valid,
  input wire hw_start,
  input wire [31:0] hw_state,
  input wire hw_writeback_busy,
  input wire hw_dw_issue_fire,
  input wire hw_dw_commit_vld,
  input wire hw_win_busy,
  input wire hw_wr_granted,
  input wire hw_wr_req
);


wire is_EXECUTE=hw_state==TB_EXECUTE_COMMIT || (hw_dw_commit_vld && hw_state!=TB_FAILED);
wire is_FAILED=hw_state==TB_FAILED;
wire is_WB_IDLE=!hw_writeback_busy;
wire is_WB_REQ=hw_wr_req;
logic [31:0] stat_cycles,stat_compute,stat_dma_wait;
always @(posedge hw_clk or negedge hw_rst_n) begin
  if(!hw_rst_n)begin stat_cycles<=0;stat_compute<=0;stat_dma_wait<=0;end
  else if(32'(hw_state)==TB_IDLE && hw_start)begin stat_cycles<=0;stat_compute<=0;stat_dma_wait<=0;end
  else begin
    if(32'(hw_state)!=TB_IDLE && 32'(hw_state)!=TB_DONE)stat_cycles<=stat_cycles+1;
    if(hw_dw_issue_fire || 32'(hw_state)==TB_EXECUTE || 32'(hw_state)==TB_EXECUTE_COMMIT || 32'(hw_state)==TB_ADD_MULT || 32'(hw_state)==TB_ADD_DRAIN || 32'(hw_state)==TB_ADD_ROUND || 32'(hw_state)==TB_ADD_ROUND_WAIT || 32'(hw_state)==TB_ADD_SUM || 32'(hw_state)==TB_ADD_STORE ||
       (32'(hw_state)==TB_SOFT_RUN && !hw_soft_lut_req_valid && !hw_soft_done))stat_compute<=stat_compute+1;
    if(32'(hw_state)==TB_LOAD_WAIT || hw_win_busy || 32'(hw_state)==TB_POOL_LOAD_WAIT || (hw_writeback_busy && !hw_wr_req) ||
       32'(hw_state)==TB_SOFT_LUT_WAIT || (hw_rd_req && !hw_rd_granted) || (hw_wr_req && !hw_wr_granted) ||
       (32'(hw_state)==TB_CONFIGURE && !hw_dma_cfg_ready))stat_dma_wait<=stat_dma_wait+1;
  end
end

endmodule
bind vector_engine vector_engine_observer #(
  .TB_FAILED(32'(FAILED)),
  .TB_ADD_MULT(32'(ADD_MULT)),
  .TB_ADD_DRAIN(32'(ADD_DRAIN)),
  .TB_ADD_ROUND(32'(ADD_ROUND)),
  .TB_ADD_ROUND_WAIT(32'(ADD_ROUND_WAIT)),
  .TB_ADD_STORE(32'(ADD_STORE)),
  .TB_ADD_SUM(32'(ADD_SUM)),
  .TB_CONFIGURE(32'(CONFIGURE)),
  .TB_DONE(32'(DONE)),
  .TB_EXECUTE(32'(EXECUTE)),
  .TB_EXECUTE_COMMIT(32'(EXECUTE_COMMIT)),
  .TB_IDLE(32'(IDLE)),
  .TB_LOAD_WAIT(32'(LOAD_WAIT)),
  .TB_POOL_LOAD_WAIT(32'(POOL_LOAD_WAIT)),
  .TB_SOFT_LUT_WAIT(32'(SOFT_LUT_WAIT)),
  .TB_SOFT_RUN(32'(SOFT_RUN))
) tb_observer(
  .hw_clk(clk),
  .hw_dma_cfg_ready(dma_cfg_ready),
  .hw_rd_granted(rd_granted),
  .hw_rd_req(rd_req),
  .hw_rst_n(rst_n),
  .hw_soft_done(soft_done),
  .hw_soft_lut_req_valid(soft_lut_req_valid),
  .hw_start(start),
  .hw_state(32'(state)),
  .hw_writeback_busy(writeback_busy),
  .hw_dw_issue_fire(dw_issue_fire),
  .hw_dw_commit_vld(dw_commit_vld),
  .hw_win_busy(win_busy),
  .hw_wr_granted(wr_granted),
  .hw_wr_req(wr_req)
);

module vector_input_write_observer #(
  parameter int p_tile=16,
  parameter int p_bus_width=64,
  parameter int p_window_lanes=4,
  parameter int p_dma_size=64,
  parameter int p_stored_elements=32,
  parameter int p_load_wait=0,
  parameter int p_load_a=0
);
  localparam int p_bus_bytes=p_bus_width/8;
  longint unsigned checked_cycles=0, ordinary_cycles=0, window_cycles=0, pool_cycles=0;
  logic ordinary_phase;
  assign ordinary_phase=32'(vector_engine.state)==p_load_wait && 32'(vector_engine.load_kind)==p_load_a;

  // 写入来源及模式直接观察真实向量和 DMA，检查过程不改变请求和响应。
  always @(posedge vector_engine.clk) if (vector_engine.rst_n) begin
    checked_cycles<=checked_cycles+1;
    assert(!vector_engine.global_pool || (vector_engine.spatial && !vector_engine.depthwise));
    assert(!ordinary_phase || !vector_engine.spatial);
    assert(!vector_engine.win_busy || (vector_engine.spatial && !vector_engine.global_pool));
    assert(vector_engine.pool_bank_valid==0 || (vector_engine.spatial && vector_engine.global_pool));
    assert(!(ordinary_phase && vector_engine.window_response_fire));
    assert(!(ordinary_phase && vector_engine.pool_bank_valid!=0));
    assert(!(vector_engine.window_response_fire && vector_engine.pool_bank_valid!=0));
    if(ordinary_phase && vector_engine.rd_valid[0]) ordinary_cycles<=ordinary_cycles+1;
    if(vector_engine.window_response_fire) window_cycles<=window_cycles+1;
    if(vector_engine.pool_bank_valid!=0) pool_cycles<=pool_cycles+1;
  end

  for(genvar entry=0;entry<p_stored_elements && entry<p_dma_size;entry++) begin : g_entry
    localparam int p_s8_lane=entry%p_bus_bytes;
    localparam int p_s16_lane=entry%(p_bus_bytes/2);
    localparam int p_window_bank=entry%p_window_lanes;
    wire load_match=vector_engine.g_input_write[entry].g_buffer.load_match;
    wire window_match=vector_engine.g_input_write[entry].g_buffer.window_match;
    wire pool_match=vector_engine.g_input_write[entry].g_buffer.pool_match;
    wire write_enable=window_match || load_match || pool_match;
    wire signed [15:0] load_value=vector_engine.c.vector_s16 ?
      vector_engine.rd_data[p_s16_lane] : vector_engine.rd_data[p_s8_lane];
    wire signed [15:0] reference_value=pool_match ? vector_engine.pool_bank_data[p_s8_lane] :
      load_match ? load_value : vector_engine.window_bank_data[p_window_bank];
    logic reference_valid;
    logic signed [15:0] reference_data;

    // 每个实际写入与逐项数据选择比较，下一拍再检查完整十六位存储值。
    always @(posedge vector_engine.clk) begin
      if(!vector_engine.rst_n) reference_valid<=1'b0;
      else begin
        if(reference_valid) assert(vector_engine.input_buf[entry]==reference_data);
        assert(vector_engine.g_input_write[entry].g_buffer.write_enable==write_enable);
        if(write_enable) begin
          assert(vector_engine.g_input_write[entry].g_buffer.write_value==reference_value);
          reference_data<=reference_value;
          reference_valid<=1'b1;
        end
      end
    end
  end
  final $display("VECTOR_INPUT_BANKS_PASS cycles=%0d ordinary=%0d window=%0d pool=%0d",
    checked_cycles,ordinary_cycles,window_cycles,pool_cycles);
endmodule
bind vector_engine vector_input_write_observer #(
  .p_tile(TILE),.p_bus_width(BUS_WIDTH),.p_window_lanes(WINDOW_LANES),.p_dma_size(DMA_SIZE),
  .p_stored_elements(INPUT_STORED_ELEMENTS),
  .p_load_wait(32'(LOAD_WAIT)),.p_load_a(32'(LD_A))
) tb_input_write_observer();

module vector_dw_progress_observer #(
  parameter int p_idle=0, p_done=0, p_execute=0, p_finish=0
);
  longint unsigned request_count, issue_count, wait_input, wait_snapshot;
  longint unsigned request_slot_ready, request_slot_reserved, request_queue_wait;
  longint unsigned quant_slot_wait, write_busy_cycles, fetch_padding;
  logic previous_done;
  logic [2:0] owned_slots, peak_owned_slots;

  always_comb begin
    owned_slots=0;
    for (int slot=0;slot<4;slot++)
      owned_slots=owned_slots+3'(vector_engine.input_ready[slot] || vector_engine.input_reserved[slot]);
  end
  // 计数器仅观察请求、槽位和后台流水的等待原因，不参与设计控制。
  always @(posedge vector_engine.clk) begin
    if (!vector_engine.rst_n || (32'(vector_engine.state)==p_idle && vector_engine.start)) begin
      request_count<=0; issue_count<=0; wait_input<=0; wait_snapshot<=0;
      request_slot_ready<=0; request_slot_reserved<=0; request_queue_wait<=0;
      quant_slot_wait<=0; write_busy_cycles<=0; fetch_padding<=0;
      previous_done<=0; peak_owned_slots<=0;
    end else begin
      previous_done<=32'(vector_engine.state)==p_done;
      if (vector_engine.depthwise) begin
        if (vector_engine.window_request_fire) request_count<=request_count+1;
        if (vector_engine.dw_issue_fire) issue_count<=issue_count+1;
        if (32'(vector_engine.state)==p_execute && vector_engine.in_bounds &&
            !vector_engine.input_ready[vector_engine.read_bank]) wait_input<=wait_input+1;
        if (32'(vector_engine.state)==p_finish && vector_engine.dw_snapshot_vld)
          wait_snapshot<=wait_snapshot+1;
        if (vector_engine.window_slot_available) begin
          if (vector_engine.input_ready[vector_engine.wf_bank]) request_slot_ready<=request_slot_ready+1;
          else if (vector_engine.input_reserved[vector_engine.wf_bank]) request_slot_reserved<=request_slot_reserved+1;
          else if (!vector_engine.win_req_ready) request_queue_wait<=request_queue_wait+1;
        end
        if (vector_engine.window_fetch_advance && !vector_engine.window_fetch_in_bounds)
          fetch_padding<=fetch_padding+1;
        if (vector_engine.dw_snapshot_vld && !vector_engine.dw_quant_input_active &&
            vector_engine.dw_result_reserved[vector_engine.dw_quant_next_slot])
          quant_slot_wait<=quant_slot_wait+1;
        if (vector_engine.writeback_busy) write_busy_cycles<=write_busy_cycles+1;
        if (owned_slots>peak_owned_slots) peak_owned_slots<=owned_slots;
        if (32'(vector_engine.state)==p_done && !previous_done)
          $display("VECTOR_DW_PROFILE requests=%0d issues=%0d wait_input=%0d wait_snapshot=%0d slot_ready=%0d slot_reserved=%0d queue_wait=%0d quant_slots=%0d write_busy=%0d padding=%0d peak_owned=%0d",
            request_count,issue_count,wait_input,wait_snapshot,request_slot_ready,request_slot_reserved,
            request_queue_wait,quant_slot_wait,write_busy_cycles,fetch_padding,peak_owned_slots);
      end
    end
  end
endmodule
bind vector_engine vector_dw_progress_observer #(
  .p_idle(32'(IDLE)),.p_done(32'(DONE)),.p_execute(32'(DW_EXECUTE)),.p_finish(32'(DW_FINISH))
) tb_dw_progress_observer();
/* verilator lint_on DECLFILENAME */

module vector_parameter_rows_observer #(
  parameter int p_load_bias=0,
  parameter int p_load_mult=0,
  parameter int p_load_shift=0
);
  longint unsigned commands_one=0, commands_two=0, commands_three=0;
  always @(posedge vector_engine.clk) if(vector_engine.rst_n && vector_engine.rd_start &&
      (32'(vector_engine.load_kind)==p_load_bias || 32'(vector_engine.load_kind)==p_load_mult ||
       32'(vector_engine.load_kind)==p_load_shift)) begin
    case(vector_engine.rd_rows_to_read)
      1: commands_one<=commands_one+1;
      2: commands_two<=commands_two+1;
      3: commands_three<=commands_three+1;
      default: assert(0);
    endcase
  end
  final $display("VECTOR_PARAMETER_ROWS_CHECK one=%0d two=%0d three=%0d",
      commands_one,commands_two,commands_three);
endmodule
bind vector_engine vector_parameter_rows_observer #(
  .p_load_bias(32'(LD_BIAS)), .p_load_mult(32'(LD_MULT)), .p_load_shift(32'(LD_SHIFT))
) tb_parameter_rows();


module vector_tile_overlap_observer #(
  parameter int p_load_wait=0,
  parameter int p_load_weight=0
);
  longint unsigned read_write_cycles=0, write_error_read_cycles=0;
  always @(posedge vector_engine.clk) if(vector_engine.rst_n && vector_engine.depthwise) begin
    if(32'(vector_engine.state)==p_load_wait && 32'(vector_engine.load_kind)==p_load_weight &&
        vector_engine.writeback_busy) read_write_cycles<=read_write_cycles+1;
    if(vector_engine.writeback_error && vector_engine.rd_busy)
      write_error_read_cycles<=write_error_read_cycles+1;
  end
  final $display("VECTOR_TILE_OVERLAP_CHECK read_write=%0d error_during_read=%0d",
      read_write_cycles,write_error_read_cycles);
endmodule
bind vector_engine vector_tile_overlap_observer #(
  .p_load_wait(32'(LOAD_WAIT)), .p_load_weight(32'(LD_WEIGHT))
) tb_tile_overlap();

`endif
