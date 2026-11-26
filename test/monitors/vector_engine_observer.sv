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
  parameter bit p_input_bank_storage=1'b0,
  parameter int p_load_wait=0,
  parameter int p_load_a=0
);
  localparam int p_bus_bytes=p_bus_width/8;
  localparam int p_input_banks=p_window_lanes>p_bus_bytes ? p_window_lanes : p_bus_bytes;
  localparam int p_input_index_width=$clog2(p_dma_size);
  localparam int p_pool_row_width=p_input_index_width>$clog2(p_bus_bytes) ?
      p_input_index_width-$clog2(p_bus_bytes) : 1;
  localparam int p_input_rows=(p_stored_elements+p_input_banks-1)/p_input_banks;
  localparam int p_input_row_width=p_input_rows>1 ? $clog2(p_input_rows) : 1;
  longint unsigned checked_cycles=0, ordinary_cycles=0, window_cycles=0, pool_cycles=0;
  logic ordinary_phase;
  assign ordinary_phase=32'(vector_engine.state)==p_load_wait && 32'(vector_engine.load_kind)==p_load_a;

  // 写入来源及模式直接观察真实向量和 DMA，检查过程不改变请求和响应。
  always @(posedge vector_engine.clk) if (vector_engine.rst_n) begin
    checked_cycles<=checked_cycles+1;
    assert(!vector_engine.global_pool || (vector_engine.spatial && !vector_engine.depthwise));
    assert(!ordinary_phase || !vector_engine.spatial);
    assert(!vector_engine.win_busy || (vector_engine.spatial && !vector_engine.global_pool));
    assert(vector_engine.u_operand_store.pool_bank_valid==0 || (vector_engine.spatial && vector_engine.global_pool));
    assert(!(ordinary_phase && vector_engine.window_response_fire));
    assert(!(ordinary_phase && vector_engine.u_operand_store.pool_bank_valid!=0));
    assert(!(vector_engine.window_response_fire && vector_engine.u_operand_store.pool_bank_valid!=0));
    if(ordinary_phase && vector_engine.rd_valid[0]) ordinary_cycles<=ordinary_cycles+1;
    if(vector_engine.window_response_fire) window_cycles<=window_cycles+1;
    if(vector_engine.u_operand_store.pool_bank_valid!=0) pool_cycles<=pool_cycles+1;
  end

  for(genvar entry=0;entry<p_stored_elements && entry<p_dma_size;entry++) begin : g_entry
    localparam int p_s8_lane=entry%p_bus_bytes;
    localparam int p_s16_lane=entry%(p_bus_bytes/2);
    localparam int p_window_bank=entry%p_window_lanes;
    localparam int p_bank=entry%p_input_banks;
    wire load_match=vector_engine.c.vector_s16 ?
        vector_engine.u_operand_store.dma_input_write_valid[p_s16_lane] &&
        vector_engine.u_operand_store.dma_input_write_index[p_s16_lane]==p_input_index_width'(entry) :
        vector_engine.u_operand_store.dma_input_write_valid[p_s8_lane] &&
        vector_engine.u_operand_store.dma_input_write_index[p_s8_lane]==p_input_index_width'(entry);
    wire window_match=vector_engine.u_operand_store.window_bank_valid[p_window_bank] &&
        vector_engine.u_operand_store.window_bank_index[p_window_bank]==p_input_index_width'(entry);
    wire pool_match=vector_engine.u_operand_store.pool_bank_valid[p_s8_lane] &&
        vector_engine.u_operand_store.pool_bank_row[p_s8_lane]==p_pool_row_width'(entry/p_bus_bytes);
    wire actual_write_enable;
    wire signed [15:0] actual_write_value, pool_value;
    if (p_input_bank_storage) begin : g_memory_write
      assign actual_write_enable=vector_engine.u_operand_store.g_input_memory.g_bank[p_bank].write_valid &&
          vector_engine.u_operand_store.g_input_memory.g_bank[p_bank].write_row==p_input_row_width'(entry/p_input_banks);
      assign actual_write_value=vector_engine.u_operand_store.input_bank_data[p_bank];
      assign pool_value=vector_engine.u_operand_store.window_bank_data[p_window_bank];
    end else begin : g_register_write
      assign actual_write_enable=vector_engine.u_operand_store.g_input_write[entry].g_buffer.g_register_value.write_enable;
      assign actual_write_value=vector_engine.u_operand_store.g_input_write[entry].g_buffer.g_register_value.write_value;
      assign pool_value=vector_engine.u_operand_store.g_pool_bank[p_s8_lane].g_rotated_register.data;
    end
    wire write_enable=window_match || load_match || pool_match;
    wire signed [15:0] load_value=vector_engine.c.vector_s16 ?
      vector_engine.rd_data[p_s16_lane] : vector_engine.rd_data[p_s8_lane];
    wire signed [15:0] reference_value=pool_match ? pool_value :
      load_match ? load_value : vector_engine.u_operand_store.window_bank_data[p_window_bank];
    logic reference_valid;
    logic signed [15:0] reference_data;

    // 每个实际写入与逐项数据选择比较，下一拍再检查完整十六位存储值。
    always @(posedge vector_engine.clk) begin
      if(!vector_engine.rst_n) reference_valid<=1'b0;
      else begin
        if(reference_valid) assert(vector_engine.input_buf[entry]==reference_data);
        assert(actual_write_enable==write_enable);
        if(write_enable) begin
          assert(actual_write_value==reference_value);
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
  .p_stored_elements(PE_COUNT>=16 ? 4*TILE : 2*TILE),.p_input_bank_storage(TILE==16 && PE_COUNT==8 && DMA_SIZE==64 && BUS_WIDTH==64 && WINDOW_LANES==8),
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
  logic input_column_in_bounds;

  assign input_column_in_bounds = vector_engine.input_x >= 34'sd0 &&
      $unsigned(vector_engine.input_x) < 34'(vector_engine.c.image.input_w);

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
        if (32'(vector_engine.state)==p_execute && (input_column_in_bounds && vector_engine.u_address.input_row_in_bounds) &&
            !vector_engine.input_ready[vector_engine.read_bank]) wait_input<=wait_input+1;
        if (32'(vector_engine.state)==p_finish && vector_engine.dw_snapshot_vld)
          wait_snapshot<=wait_snapshot+1;
        if (vector_engine.u_address.window_slot_available) begin
          if (vector_engine.input_ready[vector_engine.wf_bank]) request_slot_ready<=request_slot_ready+1;
          else if (vector_engine.input_reserved[vector_engine.wf_bank]) request_slot_reserved<=request_slot_reserved+1;
          else if (!vector_engine.win_req_ready) request_queue_wait<=request_queue_wait+1;
        end
        if (vector_engine.window_fetch_advance && !vector_engine.u_address.window_fetch_in_bounds)
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


// 消费周期直接检查真实引擎中的准备值，检查逻辑不参与生产状态更新。
module vector_control_datapath_observer #(
  parameter int p_tile=16, p_pe_count=8,
  parameter int p_check=0, p_load_req=0, p_load_wait=0,
  parameter int p_lut_req=0, p_lut_wait=0, p_soft_run=0,
  parameter int p_execute=0, p_commit=0, p_vector_next=0, p_reduce=0,
  parameter int p_load_bias=0, p_load_mult=0, p_load_shift=0
);
  import vector_engine_pkg::*;
  logic parameter_valid, lut_valid, previous_execute, previous_valid;
  logic [31:0] saved_stride, previous_state, previous_reduce_index;
  logic saved_two_rows, saved_three_rows, saved_window_valid;
  logic [7:0] saved_lut_index;
  wire [31:0] reference_stride = vector_engine.c.shift_base - vector_engine.c.multiplier_base;
  wire reference_two_rows = vector_engine.c.shift_base > vector_engine.c.multiplier_base;
  wire reference_three_rows = vector_engine.c.bias_base != 0 &&
      vector_engine.c.multiplier_base > vector_engine.c.bias_base && reference_two_rows &&
      vector_engine.c.multiplier_base - vector_engine.c.bias_base == reference_stride;
  wire parameter_phase = (32'(vector_engine.state) == p_load_req ||
      32'(vector_engine.state) == p_load_wait) &&
      (32'(vector_engine.load_kind) == p_load_bias || 32'(vector_engine.load_kind) == p_load_mult ||
       32'(vector_engine.load_kind) == p_load_shift);
  wire reduction_entry = 32'(vector_engine.state) == p_vector_next &&
      !vector_engine.vector_has_more && vector_engine.c.op != VEC_HADAMARD && !vector_engine.add_s8;
  longint unsigned parameter_cycles=0, lut_cycles=0, commit_cycles=0, reduce_cycles=0;

  always @(posedge vector_engine.clk) begin
    if (!vector_engine.rst_n) begin
      parameter_valid <= 1'b0;
      lut_valid <= 1'b0;
      previous_execute <= 1'b0;
      previous_valid <= 1'b0;
      previous_state <= '0;
      previous_reduce_index <= '0;
      saved_stride <= '0;
      saved_two_rows <= 1'b0;
      saved_three_rows <= 1'b0;
      saved_window_valid <= 1'b0;
      saved_lut_index <= '0;
    end else begin
      previous_valid <= 1'b1;
      previous_state <= 32'(vector_engine.state);
      previous_reduce_index <= 32'(vector_engine.reduce_index);
      previous_execute <= 32'(vector_engine.state) == p_execute;
      if (32'(vector_engine.state) == p_check) begin
        saved_stride <= reference_stride;
        saved_two_rows <= reference_two_rows;
        saved_three_rows <= reference_three_rows;
        parameter_valid <= 1'b1;
      end
      if (parameter_valid) begin
        assert (vector_engine.u_address.parameter_row_stride == saved_stride);
        assert (vector_engine.parameter_two_rows == saved_two_rows);
        assert (vector_engine.parameter_three_rows == saved_three_rows);
      end
      if (parameter_phase) begin
        assert (parameter_valid);
        assert (vector_engine.u_address.parameter_row_stride == reference_stride);
        assert (vector_engine.parameter_two_rows == reference_two_rows);
        assert (vector_engine.parameter_three_rows == reference_three_rows);
        parameter_cycles <= parameter_cycles + 1;
      end
      if (32'(vector_engine.state) == p_soft_run && !vector_engine.soft_done &&
          vector_engine.soft_lut_req_valid) begin
        saved_lut_index <= vector_engine.soft_lut_index;
        lut_valid <= 1'b1;
      end
      if (32'(vector_engine.state) == p_lut_req || 32'(vector_engine.state) == p_lut_wait) begin
        assert (lut_valid);
        assert (vector_engine.soft_lut_index_q == saved_lut_index);
        assert (vector_engine.soft_lut_index_q == vector_engine.soft_lut_index);
        assert (vector_engine.rd_base_addr ==
            vector_engine.c.rhs_base + {22'd0, saved_lut_index, 2'b00});
        lut_cycles <= lut_cycles + 1;
      end
      if (32'(vector_engine.state) == p_execute)
        saved_window_valid <= vector_engine.u_address.next_window_valid;
      if (32'(vector_engine.state) == p_commit) begin
        assert (previous_execute);
        assert (vector_engine.next_window_valid_q == saved_window_valid);
        assert (vector_engine.next_window_valid_q == vector_engine.u_address.next_window_valid);
        assert (vector_engine.compute_group_last_q ==
            (vector_engine.compute_index + 32'(p_pe_count) >= vector_engine.active));
        commit_cycles <= commit_cycles + 1;
      end
      if (32'(vector_engine.state) == p_reduce) begin
        assert (32'(vector_engine.reduce_index) < p_tile);
        assert (vector_engine.reduce_alu_i_rhs == vector_engine.acc_buf[vector_engine.reduce_index]);
        assert (previous_valid && (previous_state == p_vector_next || previous_state == p_reduce));
        if (previous_state == p_vector_next) begin
          assert (vector_engine.reduce_index == 0);
        end else begin
          assert (32'(vector_engine.reduce_index) == previous_reduce_index + 1);
        end
        reduce_cycles <= reduce_cycles + 1;
      end
    end
  end
  for (genvar entry=0; entry<p_tile; entry++) begin : g_accumulator_stable
    always @(posedge vector_engine.clk) if (vector_engine.rst_n &&
        (reduction_entry || 32'(vector_engine.state) == p_reduce)) begin
      assert (!vector_engine.u_operand_store.g_accumulator_write[entry].write_enable);
    end
  end
  final $display("VECTOR_CONTROL_DATAPATH_PASS parameter_cycles=%0d lut_cycles=%0d commit_cycles=%0d reduce_cycles=%0d",
      parameter_cycles, lut_cycles, commit_cycles, reduce_cycles);
endmodule
bind vector_engine vector_control_datapath_observer #(
  .p_tile(TILE), .p_pe_count(PE_COUNT), .p_check(32'(CHECK)),
  .p_load_req(32'(LOAD_REQ)), .p_load_wait(32'(LOAD_WAIT)),
  .p_lut_req(32'(SOFT_LUT_REQ)), .p_lut_wait(32'(SOFT_LUT_WAIT)), .p_soft_run(32'(SOFT_RUN)),
  .p_execute(32'(EXECUTE)), .p_commit(32'(EXECUTE_COMMIT)),
  .p_vector_next(32'(VECTOR_NEXT)), .p_reduce(32'(VECTOR_REDUCE)),
  .p_load_bias(32'(LD_BIAS)), .p_load_mult(32'(LD_MULT)), .p_load_shift(32'(LD_SHIFT))
) tb_control_datapath();

`endif

// SPDX-License-Identifier: Apache-2.0
// 检查向量任务、存储槽位、量化有效位和写回等待期间的不变量。
`ifdef NPU_SIM_ASSERT
module vector_engine_invariants #(
  parameter int TILE = 16,
  parameter int BUS_WIDTH = 32,
  parameter int DMA_SIZE = 4*TILE,
  parameter int PE_COUNT = (TILE < 8) ? TILE : 8,
  parameter int WINDOW_LANES = 4,
  parameter bit SHARED_QUANT_ENABLE = 1'b0,
  parameter int QUANT_LANES = SHARED_QUANT_ENABLE ? TILE : 1,
  parameter bit SHARED_STORAGE_ENABLE = 1'b0,
  parameter int SHARED_STORAGE_ADDR_WIDTH = 12,
  parameter int MAX_TAPS = 49,
  parameter int POOL_MAX_TAPS = 256
) ();
  import vector_engine_pkg::*;
  import vector_engine_control_pkg::*;
  localparam int BUS_BYTES=BUS_WIDTH/8;
  localparam int BUS_SHIFT=$clog2(BUS_BYTES);
  localparam int INPUT_BANKS=WINDOW_LANES>BUS_BYTES ? WINDOW_LANES : BUS_BYTES;
  localparam int ACTIVE_COUNT_W = $clog2(TILE + 1);
  localparam int TAP_LIMIT = MAX_TAPS > POOL_MAX_TAPS ? MAX_TAPS : POOL_MAX_TAPS;
  localparam int TAP_COUNT_W = $clog2(TAP_LIMIT + 1);
  localparam int TILE_INDEX_W = $clog2(TILE + PE_COUNT + 1);
  localparam int INPUT_INDEX_W = $clog2(DMA_SIZE);
  localparam int INPUT_STORED_ELEMENTS = PE_COUNT>=16 ? 4*TILE : 2*TILE;
  localparam bit p_input_bank_storage = TILE==16 && PE_COUNT==8 && DMA_SIZE==64 &&
      BUS_WIDTH==64 && WINDOW_LANES==8;
  localparam int p_input_bank_rows = (INPUT_STORED_ELEMENTS+INPUT_BANKS-1)/INPUT_BANKS;
  localparam int p_input_row_width = p_input_bank_rows>1 ? $clog2(p_input_bank_rows) : 1;
  localparam int POOL_GROUP_COUNT=(TILE+PE_COUNT-1)/PE_COUNT;
  localparam int AVG_SCALE_BITS = 8+$clog2(POOL_MAX_TAPS+1);
  localparam int p_window_count_width = $clog2(WINDOW_LANES+1);
  localparam int p_window_count_leaves = 1 << $clog2(WINDOW_LANES);
  localparam int POOL_ROW_W=INPUT_INDEX_W>BUS_SHIFT ? INPUT_INDEX_W-BUS_SHIFT : 1;
  localparam int WEIGHT_DMA_GROUPS=(TILE+BUS_BYTES-1)/BUS_BYTES;
  localparam int ADD_INDEX_WIDTH=$clog2(TILE)>0 ? $clog2(TILE) : 1;
  localparam int POOL_SUM_WIDTH=8+$clog2(POOL_MAX_TAPS);
  localparam int WINDOW_BANK_W=$clog2(WINDOW_LANES);
  localparam int p_bias_words_per_beat = BUS_WIDTH / 32;
  logic input_column_in_bounds;
  vector_coordinate_bound u_input_column_bound (
      .i_coordinate(vector_engine.input_x), .i_limit(vector_engine.c.image.input_w), .o_in_bounds(input_column_in_bounds)
  );
  logic in_bounds;
  logic writeback_metadata_slot;
  assign in_bounds = input_column_in_bounds && vector_engine.u_address.input_row_in_bounds;
  always_ff @(posedge vector_engine.clk) begin
    if (vector_engine.writeback_metadata_capture) writeback_metadata_slot <= vector_engine.dw_result_read_slot;
  end
  logic signed [31:0] soft_exp_previous;
  logic signed [7:0] soft_out_previous;
  always_ff @(posedge vector_engine.clk) begin
    if (vector_engine.soft_exp_we) soft_exp_previous <= vector_engine.soft_exp_data;
    if (vector_engine.soft_out_we) soft_out_previous <= vector_engine.soft_out_data;
    if (vector_engine.rst_n && vector_engine.soft_exp_write_valid) assert(vector_engine.soft_lut_data === soft_exp_previous);
    if (vector_engine.rst_n && vector_engine.soft_out_write_valid) assert(vector_engine.soft_out_data === soft_out_previous);
  end
  logic [31:0] input_position[4],input_tap[4];
  logic writeback_metadata_stalled;
  logic writeback_metadata_match;
  logic previous_writeback_sink_fire;
  assign writeback_metadata_match = vector_engine.writeback_metadata_valid &&
      (!vector_engine.depthwise || writeback_metadata_slot == vector_engine.dw_result_read_slot);
  logic [31:0] previous_writeback_address;
  logic [$clog2(4*TILE+1)-1:0] previous_writeback_bytes;
  logic previous_writeback_last, previous_writeback_coalesce;
  logic [32*TILE-1:0] previous_writeback_words;
  // 纯乘法在接收边沿保存零累加值，下一采样边沿检查实际 PE 状态。
  for (genvar lane=0;lane<PE_COUNT;lane++) begin : g_pe_multiply_state
    assert property (@(posedge vector_engine.clk) disable iff (!vector_engine.rst_n)
      (vector_engine.pe_operand_en && vector_engine.vector_hadamard) |=>
      (vector_engine.g_pe[lane].u_pe.op == PE_MUL &&
       vector_engine.g_pe[lane].u_pe.acc === 32'sd0));
  end
  // 逐次接收操作数并独立累加，检查快照值及后续像素的偏置初始化。
  for (genvar entry=0;entry<TILE;entry++) begin : g_dw_snapshot_reference
    localparam int p_lane_index = entry % PE_COUNT;
    localparam int p_group_base = entry - p_lane_index;
    logic signed [31:0] accumulator;
    logic signed [31:0] product;
    assign product = 32'($signed(vector_engine.input_lane[p_lane_index])) *
        32'($signed(vector_engine.weight_lane[p_lane_index]));
    always_ff @(posedge vector_engine.clk) begin
      if (vector_engine.rst_n && vector_engine.depthwise) begin
        if (vector_engine.state_output_init || vector_engine.dw_snapshot_fire)
          accumulator <= vector_engine.u_operand_store.bias_buf[entry];
        else if (vector_engine.dw_issue_fire && vector_engine.active_lane_mask[entry] &&
                 vector_engine.compute_index == TILE_INDEX_W'(p_group_base))
          accumulator <= accumulator + product;
        if (vector_engine.dw_snapshot_fire && vector_engine.active_lane_mask[entry]) begin
          assert(vector_engine.dw_snapshot_value[entry] === accumulator);
          if (SHARED_STORAGE_ENABLE)
            assert(vector_engine.o_ps_write_data[32*entry+:32] === accumulator);
        end
      end
    end
    assert property (@(posedge vector_engine.clk) disable iff (!vector_engine.rst_n)
      vector_engine.dw_snapshot_fire |=>
      vector_engine.acc_buf[entry] === $past(vector_engine.u_operand_store.bias_buf[entry]));
    if (!SHARED_STORAGE_ENABLE) begin : g_private_capture
      logic pending;
      logic signed [31:0] expected_value;
      always_ff @(posedge vector_engine.clk) begin
        if (!vector_engine.rst_n) pending <= 1'b0;
        else begin
          if (pending) assert(vector_engine.quant_req_accumulator[entry] === expected_value);
          pending <= vector_engine.dw_snapshot_fire && vector_engine.active_lane_mask[entry];
          if (vector_engine.dw_snapshot_fire) expected_value <= accumulator;
        end
      end
    end
  end
  int unsigned snapshot_forwarded = 0;
  int unsigned snapshot_buffered = 0;
  int unsigned snapshot_partial_group = 0;
  int unsigned snapshot_multiple_groups = 0;
  always @(posedge vector_engine.clk) begin
    if (vector_engine.rst_n && vector_engine.dw_snapshot_fire) begin
      if (vector_engine.dw_commit_vld) begin
        snapshot_forwarded++;
        if (32'(vector_engine.active) % PE_COUNT != 0) snapshot_partial_group++;
        if (32'(vector_engine.active) > PE_COUNT) snapshot_multiple_groups++;
      end else snapshot_buffered++;
    end
  end
  final $display("VECTOR_DW_SNAPSHOT_CHECK forwarded=%0d buffered=%0d partial_group=%0d multiple_groups=%0d",
      snapshot_forwarded, snapshot_buffered, snapshot_partial_group, snapshot_multiple_groups);
  always @(posedge vector_engine.clk) begin
    if (!vector_engine.rst_n) begin
      writeback_metadata_stalled <= 1'b0;
      previous_writeback_sink_fire <= 1'b0;
    end else begin
      if (vector_engine.state==AVG_WAIT && vector_engine.avg_phase==4'd9)
        assert(vector_engine.avg_signed_q === (vector_engine.avg_negative ? -$signed({1'b0,vector_engine.avg_magnitude_q}) :
            $signed({1'b0,vector_engine.avg_magnitude_q})));
      if (vector_engine.writeback_sink_fire && !vector_engine.depthwise) assert(!vector_engine.result_byte_pending);
      assert(!(vector_engine.result_background_write && vector_engine.result_serial_write));
      if (vector_engine.state_pool_store) assert(!vector_engine.result_byte_pending);
      assert(vector_engine.state_dw_execute === (vector_engine.state==DW_EXECUTE));
      assert(vector_engine.state_weight_read_phase === (vector_engine.state==OUTPUT_INIT || vector_engine.state==DW_EXECUTE || vector_engine.state==DW_FINISH));
      for (int lane=0;lane<TILE;lane++) assert(vector_engine.active_lane_mask[lane] === (32'(lane)<vector_engine.active));
      for (int group=0;group<POOL_GROUP_COUNT;group++) begin
        assert(vector_engine.compute_pool_group[group] === (vector_engine.compute_index==TILE_INDEX_W'(group*PE_COUNT)));
      end
      if (p_input_bank_storage) assert(vector_engine.window_write_pending == (|vector_engine.u_operand_store.window_bank_valid));
      if (SHARED_STORAGE_ENABLE && vector_engine.o_weight_write_en) begin
        assert(!vector_engine.o_weight_read_en);
        assert(|vector_engine.o_weight_write_mask);
      end
      if (vector_engine.pe_operand_en) begin
        assert(vector_engine.vector_hadamard == (vector_engine.pe_op == PE_MUL));
      end
      if (vector_engine.state_compute_commit && vector_engine.global_pool)
        assert(vector_engine.pool_pixel_has_more_q == (vector_engine.pool_pixel+1<vector_engine.pool_pixels));
      if (vector_engine.state==VECTOR_NEXT && !vector_engine.vector_has_more && !vector_engine.vector_hadamard && !vector_engine.add_s8)
        assert(vector_engine.serial_acc_read_data === vector_engine.acc_buf[0]);
      if (vector_engine.state==VECTOR_REDUCE && vector_engine.reduce_index+1<TILE)
        assert(vector_engine.serial_acc_read_data === vector_engine.acc_buf[vector_engine.reduce_index+TILE_INDEX_W'(1)]);
      if (vector_engine.dw_snapshot_fire) assert(!vector_engine.dw_issue_fire);
      assert(vector_engine.writeback_accept_pending == previous_writeback_sink_fire);
      assert(!(vector_engine.writeback_metadata_valid && vector_engine.writeback_accept_pending));
      if (vector_engine.writeback_metadata_valid && !vector_engine.state_failed)
        assert(vector_engine.writeback_request_valid && writeback_metadata_match);
      if (vector_engine.state==TAP_CHECK) assert(vector_engine.dw_in_bounds == in_bounds);
      if (vector_engine.state_dw_finish || vector_engine.state==OUTPUT_NEXT) begin
        assert(vector_engine.channel_has_more == (vector_engine.channel_base+vector_engine.active<vector_engine.channels));
        assert(vector_engine.channel_next == 16'(vector_engine.channel_base+vector_engine.active));
      end
      assert(vector_engine.window_fetch_phase == (vector_engine.state_output_init || vector_engine.state==TAP_CHECK || vector_engine.state==WINDOW_WAIT || vector_engine.state==EXECUTE || vector_engine.state_compute_commit || vector_engine.state==TAP_NEXT || vector_engine.state==QUANT_INIT || vector_engine.state==OUTPUT_NEXT || vector_engine.state==AVG_START || vector_engine.state==AVG_POWER_DELAY || vector_engine.state==AVG_POWER_CLAMP || vector_engine.state==AVG_POWER_STORE || vector_engine.state==AVG_WAIT || vector_engine.state_pool_store || vector_engine.state==WRITE_PREP || vector_engine.state_dw_execute || vector_engine.state_dw_finish));
      previous_writeback_sink_fire <= vector_engine.writeback_sink_fire;
      assert(vector_engine.state_failed == (vector_engine.state==FAILED));
      assert(vector_engine.state_compute_commit == (vector_engine.state==EXECUTE_COMMIT));
      assert(vector_engine.state_pool_store == (vector_engine.state==POOL_STORE));
      assert(vector_engine.state_output_init == (vector_engine.state==OUTPUT_INIT));
      assert(vector_engine.state_vector_init == (vector_engine.state==VECTOR_INIT));
      assert(vector_engine.state_dw_finish == (vector_engine.state==DW_FINISH));
      assert(vector_engine.ready == (vector_engine.state==IDLE));
      assert(vector_engine.done_valid == (vector_engine.state==DONE));
      assert(vector_engine.dma_cfg_valid == (vector_engine.state==CONFIGURE));
      assert(vector_engine.rd_req == (vector_engine.state==LOAD_REQ || vector_engine.state==POOL_LOAD_REQ || vector_engine.state==SOFT_LUT_REQ));
      if (vector_engine.writeback_request_valid && writeback_metadata_match) begin
        assert(vector_engine.writeback_metadata_address == vector_engine.writeback_request_address);
        assert(vector_engine.writeback_metadata_bytes == vector_engine.writeback_request_bytes);
        assert(vector_engine.writeback_metadata_last == vector_engine.writeback_request_last);
        assert(vector_engine.writeback_metadata_coalesce ==
            (vector_engine.depthwise && vector_engine.channels==32'(vector_engine.dw_result_count[vector_engine.dw_result_read_slot])));
      end
      if (writeback_metadata_stalled && !vector_engine.state_failed) begin
        assert(vector_engine.writeback_request_valid && writeback_metadata_match);
        assert(vector_engine.writeback_metadata_address == previous_writeback_address);
        assert(vector_engine.writeback_metadata_bytes == previous_writeback_bytes);
        assert(vector_engine.writeback_metadata_last == previous_writeback_last);
        assert(vector_engine.writeback_metadata_coalesce == previous_writeback_coalesce);
        if (vector_engine.byte_output) begin
          for (int entry=0; entry<TILE; entry++)
            assert(vector_engine.writeback_words[32*entry+:8] == previous_writeback_words[32*entry+:8]);
        end else assert(vector_engine.writeback_words == previous_writeback_words);
      end
      if (vector_engine.window_response_fault) begin
        assert(!vector_engine.dw_issue_fire);
        assert(!vector_engine.win_req_valid);
      end
      writeback_metadata_stalled <= vector_engine.writeback_request_valid && writeback_metadata_match && !vector_engine.writeback_sink_ready;
      previous_writeback_address <= vector_engine.writeback_metadata_address;
      previous_writeback_bytes <= vector_engine.writeback_metadata_bytes;
      previous_writeback_last <= vector_engine.writeback_metadata_last;
      previous_writeback_coalesce <= vector_engine.writeback_metadata_coalesce;
      previous_writeback_words <= vector_engine.writeback_words;
    end
  end
  initial forever begin
    @(posedge vector_engine.clk or negedge vector_engine.rst_n);
    if (!vector_engine.rst_n) begin
      for (int bank=0;bank<4;bank++) begin
        input_position[bank]<=0;input_tap[bank]<=0;
      end
    end else if (vector_engine.window_request_fire) begin
      input_position[vector_engine.wf_bank]<=vector_engine.fetch_position;input_tap[vector_engine.wf_bank]<=vector_engine.u_control.fetch_tap;
    end
  end
  initial begin
    assert(TILE>=2 && TILE<=64 && (TILE&(TILE-1))==0);
    assert(PE_COUNT>=1 && PE_COUNT<=TILE && TILE%PE_COUNT==0);
    assert(DMA_SIZE>=4*TILE && MAX_TAPS>=1 && MAX_TAPS<=255);
    assert(POOL_MAX_TAPS>=1 && POOL_MAX_TAPS<=65535);
  end
  initial forever @(posedge vector_engine.clk) if (vector_engine.rst_n) begin
    if (vector_engine.writeback_busy_raw) assert(vector_engine.writeback_busy);
    assert(vector_engine.spatial == (vector_engine.c.op <= MINPOOL_S8) && vector_engine.depthwise == (vector_engine.c.op == DW_S8));
    assert(vector_engine.add_s8 == (vector_engine.c.op == ADD_S8) && vector_engine.softmax_s8 == (vector_engine.c.op == SOFTMAX_S8));
    assert(vector_engine.byte_output == (vector_engine.spatial || vector_engine.add_s8 || vector_engine.softmax_s8));
    assert(vector_engine.binary_vector == (vector_engine.c.op == VEC_DOT || vector_engine.c.op == VEC_HADAMARD || vector_engine.add_s8));
    assert(vector_engine.avg_pool == (vector_engine.c.op == AVGPOOL_S8) && vector_engine.max_pool == (vector_engine.c.op == MAXPOOL_S8));
    assert(vector_engine.min_pool == (vector_engine.c.op == MINPOOL_S8) && vector_engine.vector_hadamard == (vector_engine.c.op == VEC_HADAMARD));
    assert(vector_engine.vector_max == (vector_engine.c.op == VEC_MAX) && vector_engine.vector_min == (vector_engine.c.op == VEC_MIN));
    if (vector_engine.state == VECTOR_NEXT) begin
      assert(vector_engine.vector_has_more == vector_engine.u_address.vector_has_more_comb);
      assert(vector_engine.vector_next_active == vector_engine.u_address.vector_next_active_comb);
    end
    if (vector_engine.global_pool && (vector_engine.state == POOL_LOAD_PREP || vector_engine.state == EXECUTE || vector_engine.state_compute_commit))
      assert(vector_engine.pool_taps_remaining == vector_engine.taps - vector_engine.u_control.pool_offset);
    if (vector_engine.state == POOL_LOAD_PREP) begin
      assert(vector_engine.u_address.cache_power_two == vector_engine.u_address.cache_power_two_next && vector_engine.u_address.cache_channel_shift == vector_engine.u_address.cache_channel_shift_next);
      assert(vector_engine.u_address.pool_capacity == (vector_engine.u_address.cache_power_two_next && vector_engine.active >= 4 ?
          (INPUT_INDEX_W+1)'(2*TILE) >> vector_engine.u_address.cache_channel_shift_next : (INPUT_INDEX_W+1)'(1)));
    end
    if (vector_engine.state == QUANT_INIT || vector_engine.state == AVG_START || vector_engine.state == AVG_POWER_STORE || vector_engine.state == AVG_WAIT)
      assert(vector_engine.avg_power_two == vector_engine.u_address.avg_power_two_next && vector_engine.avg_shift == vector_engine.u_address.avg_shift_next);
    if (vector_engine.q_valid[6]) begin
      assert(vector_engine.u_activation.minimum_before_offset == $signed({vector_engine.c.activation_min[7],vector_engine.c.activation_min[7:0]}) -
          $signed({vector_engine.c.output_offset[7],vector_engine.c.output_offset[7:0]}));
      assert(vector_engine.u_activation.maximum_before_offset == $signed({vector_engine.c.activation_max[7],vector_engine.c.activation_max[7:0]}) -
          $signed({vector_engine.c.output_offset[7],vector_engine.c.output_offset[7:0]}));
    end
    if (vector_engine.src_wvalid && !vector_engine.src_wready) begin
      assert(vector_engine.wr_busy);
    end
    if (vector_engine.state==EXECUTE) assert(vector_engine.active>0 && vector_engine.active<=TILE && vector_engine.compute_index<vector_engine.active);
    if (vector_engine.weight_row_last_fire) assert(vector_engine.load_tap<vector_engine.taps);
    if (vector_engine.state==LOAD_WAIT && vector_engine.load_kind==LD_WEIGHT && vector_engine.read_done_q && !vector_engine.read_error_q)
      assert(32'(vector_engine.load_tap)+32'(vector_engine.weight_row_last_fire)==32'(vector_engine.taps));
    if (vector_engine.state==LOAD_WAIT && vector_engine.read_done_q && !vector_engine.read_error_q &&
        (vector_engine.load_kind==LD_BIAS || vector_engine.load_kind==LD_MULT || vector_engine.load_kind==LD_SHIFT))
      assert(vector_engine.u_control.parameter_rows_remaining==0);
    if (vector_engine.state==ADD_MULT || vector_engine.state==ADD_DRAIN || vector_engine.state==ADD_ROUND || vector_engine.state==ADD_ROUND_WAIT || vector_engine.state==ADD_SUM || vector_engine.state==ADD_STORE) begin
      assert(vector_engine.add_s8 && vector_engine.active>0 && vector_engine.active<=TILE && vector_engine.compute_index<vector_engine.active);
      assert(vector_engine.add_stage<=2 && vector_engine.add_right>=1 && vector_engine.add_right<=62);
      if (vector_engine.state==ADD_SUM)
        assert($signed(64'(vector_engine.add_scaled_a))+$signed(vector_engine.add_rounded)>=-64'sd2147483648 &&
               $signed(64'(vector_engine.add_scaled_a))+$signed(vector_engine.add_rounded)<=64'sd2147483647);
    end
    if (vector_engine.window_request_fire) begin
      // 复用尚未清空的输入槽时，旧数据必须已经被当前通道组捕获。
      if (vector_engine.input_ready[vector_engine.wf_bank]) begin
        assert(vector_engine.dw_issue_fire && vector_engine.dw_group_last);
        assert(vector_engine.wf_bank == vector_engine.read_bank);
        assert(!(vector_engine.window_response_fire && vector_engine.win_rsp_tag == vector_engine.read_bank));
      end
      assert((!vector_engine.input_ready[vector_engine.wf_bank] || vector_engine.u_address.input_slot_release) && !vector_engine.input_reserved[vector_engine.wf_bank]);
      assert(vector_engine.win_req_cols>0 && vector_engine.win_req_cols<=TILE);
    end
    if (vector_engine.window_response_fire) begin
      assert(vector_engine.input_reserved[vector_engine.win_rsp_tag]);
      if(!vector_engine.win_rsp_error) begin
        assert(vector_engine.win_rsp_mask!=0 && vector_engine.win_rsp_col+32'(vector_engine.u_address.window_response_count)<=vector_engine.active);
        if(vector_engine.win_rsp_last) assert(vector_engine.window_received+32'(vector_engine.u_address.window_response_count)==vector_engine.active);
      end
    end
    if (vector_engine.state==WINDOW_WAIT) assert(in_bounds && vector_engine.tap<vector_engine.taps);
    if (vector_engine.state==POOL_LOAD_REQ) begin
      assert(vector_engine.global_pool && vector_engine.input_range_mode && vector_engine.pool_pixels>0 && vector_engine.pool_elements<=DMA_SIZE);
      assert(vector_engine.u_control.pool_offset+vector_engine.pool_pixels<=vector_engine.taps);
    end
    if (vector_engine.state==EXECUTE && vector_engine.global_pool) assert(vector_engine.pool_pixel<vector_engine.pool_pixels && vector_engine.pool_input_index+vector_engine.active<=vector_engine.pool_elements);
    if ((vector_engine.state==EXECUTE || vector_engine.dw_issue_fire) && vector_engine.spatial && !vector_engine.global_pool) begin
      assert(vector_engine.input_ready[vector_engine.read_bank]);
      assert(input_position[vector_engine.read_bank]==vector_engine.position && input_tap[vector_engine.read_bank]==vector_engine.tap);
    end
  end
endmodule

bind vector_engine vector_engine_invariants #(
  .TILE(TILE),
  .BUS_WIDTH(BUS_WIDTH),
  .DMA_SIZE(DMA_SIZE),
  .PE_COUNT(PE_COUNT),
  .WINDOW_LANES(WINDOW_LANES),
  .SHARED_QUANT_ENABLE(SHARED_QUANT_ENABLE),
  .QUANT_LANES(QUANT_LANES),
  .SHARED_STORAGE_ENABLE(SHARED_STORAGE_ENABLE),
  .SHARED_STORAGE_ADDR_WIDTH(SHARED_STORAGE_ADDR_WIDTH),
  .MAX_TAPS(MAX_TAPS),
  .POOL_MAX_TAPS(POOL_MAX_TAPS)
) u_invariants ();
`endif
