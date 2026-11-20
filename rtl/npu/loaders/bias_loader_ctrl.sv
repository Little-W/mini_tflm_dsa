/*
 * Bias groups remain available in the two data banks until replacement or
 * init_cfg. A requested group selects its resident bank or starts a DMA load.
 */

module bias_loader_ctrl #(
    parameter int unsigned SIZE      = 8,
    parameter int unsigned BUS_WIDTH = 32,
    parameter int unsigned REG_WIDTH = 32,
    parameter int unsigned COUNT_WIDTH = REG_WIDTH,
    parameter int unsigned GROUP_BLOCKS_MAX = 1
) (
    input  logic clk,
    input  logic rst_n,

    input  logic                 init_cfg,
    input  logic [REG_WIDTH-1:0] bias_base,
    input  logic [REG_WIDTH-1:0] m,
    input  logic [REG_WIDTH-1:0] bias_step_blocks,
    input  logic                 bias_switch,
    input  logic                 bias_last_loop,

    output logic                 load_bias_req,
    input  logic                 load_bias_granted,

    input  logic                 dma_busy,
    input  logic                 dma_done,
    input  logic                 load_block_valid,
    input  logic                 load_block_bank,

    output logic                 dma_start,
    output logic [REG_WIDTH-1:0] dma_base_addr,
    output logic [REG_WIDTH-1:0] dma_rows_to_read,
    output logic [7:0]           dma_burst_len_m1,
    output logic [COUNT_WIDTH-1:0] dma_row_offset,
    output logic                 load_group_done,
    output logic                 load_bank,

    output logic [COUNT_WIDTH-1:0] current_block_idx,
    output logic [COUNT_WIDTH-1:0] load_block_idx,
    output logic [COUNT_WIDTH-1:0] group_blocks_needed,
    output logic [COUNT_WIDTH-1:0] load_blocks_count,
    output logic                 active_bank,
    output logic                 switch_pending
);

  localparam int unsigned SIZE_SHIFT = $clog2(SIZE);
  localparam int unsigned BLOCK_ADDR_SHIFT = SIZE_SHIFT + 2;
  localparam int unsigned CNT_W = (COUNT_WIDTH < 1) ? 1 : COUNT_WIDTH;
  localparam int unsigned LOAD_CNT_BITS = $clog2(33'(GROUP_BLOCKS_MAX) + 33'd1);
  localparam int unsigned LOAD_CNT_W = (LOAD_CNT_BITS < 1) ? 1 :
      ((LOAD_CNT_BITS < CNT_W) ? LOAD_CNT_BITS : CNT_W);
  typedef logic [CNT_W-1:0] count_t;
  typedef logic [LOAD_CNT_W-1:0] load_count_t;

  typedef enum logic [3:0] {
    S_IDLE       = 4'd0,
    S_INIT_GEOM  = 4'd1,
    S_INIT_LAST  = 4'd2,
    S_INIT_MARK  = 4'd3,
    S_INIT_GROUP = 4'd4,
    S_CMD        = 4'd5,
    S_REQ        = 4'd6,
    S_LOAD       = 4'd7,
    S_WAIT       = 4'd8,
    S_NEXT_IDX   = 4'd9,
    S_NEXT_MARK  = 4'd10,
    S_NEXT_GROUP = 4'd11
  } state_t;

  (* fsm_encoding = "sequential" *) state_t state;

  logic [REG_WIDTH-1:0] cfg_bias_base;
  count_t cfg_m;
  count_t cfg_bias_step_blocks;
  count_t num_blocks;
  count_t last_block_elems;
  count_t step_blocks_eff;
  count_t last_group_start_idx;
  logic                 current_is_last_group;
  logic                 bias_switch_d;
  logic                 tail_pending;
  count_t remaining_blocks;
  count_t bounded_load_count;
  load_count_t bounded_load_count_narrow;
  count_t load_tail_offset;
  count_t initial_num_blocks;
  logic load_window_last;
  logic [REG_WIDTH-1:0] tail_base_addr;

  logic [CNT_W-1:0] remaining_i_a, remaining_i_b, remaining_o_sum;
  logic remaining_i_carry, remaining_o_carry;
  logic [REG_WIDTH-1:0] command_address_i_a, command_address_i_b, command_address_o_sum;
  logic command_address_i_carry, command_address_o_carry;
  logic [REG_WIDTH-1:0] tail_address_i_a, tail_address_i_b, tail_address_o_sum;
  logic tail_address_i_carry, tail_address_o_carry;
  logic [CNT_W-1:0] next_index_i_a, next_index_i_b, next_index_o_sum;
  logic next_index_i_carry, next_index_o_carry;

  assign remaining_i_a = num_blocks;
  assign remaining_i_b = ~load_block_idx;
  assign remaining_i_carry = 1'b1;
  parallel_prefix_add #(.p_width(CNT_W)) u_remaining (
      .i_a(remaining_i_a), .i_b(remaining_i_b), .i_carry(remaining_i_carry),
      .o_sum(remaining_o_sum), .o_carry(remaining_o_carry)
  );
  assign bounded_load_count_narrow = (remaining_blocks < count_t'(GROUP_BLOCKS_MAX)) ?
      load_count_t'(remaining_blocks) : load_count_t'(GROUP_BLOCKS_MAX);
  assign bounded_load_count = count_t'(bounded_load_count_narrow);

  assign next_index_i_a = current_block_idx;
  assign next_index_i_b = step_blocks_eff;
  assign next_index_i_carry = 1'b0;
  parallel_prefix_add #(.p_width(CNT_W)) u_next_index (
      .i_a(next_index_i_a), .i_b(next_index_i_b), .i_carry(next_index_i_carry),
      .o_sum(next_index_o_sum), .o_carry(next_index_o_carry)
  );

  assign command_address_i_a = cfg_bias_base;
  assign command_address_i_b = REG_WIDTH'(load_block_idx) << BLOCK_ADDR_SHIFT;
  assign command_address_i_carry = 1'b0;
  parallel_prefix_add #(.p_width(REG_WIDTH)) u_command_address (
      .i_a(command_address_i_a), .i_b(command_address_i_b), .i_carry(command_address_i_carry),
      .o_sum(command_address_o_sum), .o_carry(command_address_o_carry)
  );

  // 命令地址已在 S_CMD 保存，尾块地址在后续请求阶段独立准备。
  assign tail_address_i_a = dma_base_addr;
  assign tail_address_i_b = REG_WIDTH'(load_tail_offset) << BLOCK_ADDR_SHIFT;
  assign tail_address_i_carry = 1'b0;
  parallel_prefix_add #(.p_width(REG_WIDTH)) u_tail_address (
      .i_a(tail_address_i_a), .i_b(tail_address_i_b), .i_carry(tail_address_i_carry),
      .o_sum(tail_address_o_sum), .o_carry(tail_address_o_carry)
  );

  // 二次幂分块先取商再加低位非零标志，显式保留原计数宽度的回绕。
  if ((SIZE == (1 << SIZE_SHIFT)) && (CNT_W > SIZE_SHIFT)) begin : g_initial_blocks
    localparam int unsigned QUOTIENT_W = CNT_W - SIZE_SHIFT;
    logic [QUOTIENT_W-1:0] rounded_i_a, rounded_i_b, rounded_o_sum;
    logic rounded_i_carry, rounded_o_carry;
    assign rounded_i_a = QUOTIENT_W'(cfg_m >> SIZE_SHIFT);
    assign rounded_i_b = '0;
    assign rounded_i_carry = (cfg_m & count_t'(SIZE - 1)) != '0;
    parallel_prefix_add #(.p_width(QUOTIENT_W)) u_rounded (
        .i_a(rounded_i_a), .i_b(rounded_i_b), .i_carry(rounded_i_carry),
        .o_sum(rounded_o_sum), .o_carry(rounded_o_carry)
    );
    assign initial_num_blocks = count_t'(rounded_o_sum);
  end else begin : g_initial_blocks_general
    assign initial_num_blocks = (cfg_m + count_t'(SIZE - 1)) >> SIZE_SHIFT;
  end

  wire bias_switch_rise = bias_switch && !bias_switch_d;
  wire split_tail_group = load_window_last &&
                          (load_blocks_count > count_t'(1)) &&
                          (last_block_elems != count_t'(SIZE));
  logic [REG_WIDTH-1:0] load_rows_full;
  logic [REG_WIDTH-1:0] load_rows_without_tail;
  // 完整行数和扣除尾块后的行数并行计算，范围判断只选择最终结果。
  assign load_rows_full = REG_WIDTH'(load_blocks_count);
  assign load_rows_without_tail = load_rows_full - REG_WIDTH'(1);
  assign load_group_done = dma_done && !tail_pending;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state                  <= S_IDLE;
      cfg_bias_base          <= '0;
      cfg_m                  <= '0;
      cfg_bias_step_blocks   <= '0;
      num_blocks             <= '0;
      last_block_elems       <= '0;
      step_blocks_eff        <= count_t'(1);
      last_group_start_idx   <= '0;
      current_is_last_group  <= 1'b1;
      current_block_idx      <= '0;
      load_block_idx         <= '0;
      group_blocks_needed    <= '0;
      load_blocks_count      <= '0;
      active_bank            <= 1'b0;
      load_bank              <= 1'b0;
      switch_pending         <= 1'b0;
      load_bias_req          <= 1'b0;
      dma_start              <= 1'b0;
      dma_base_addr          <= '0;
      dma_rows_to_read       <= '0;
      dma_burst_len_m1       <= '0;
      dma_row_offset        <= '0;
      tail_pending          <= 1'b0;
      bias_switch_d          <= 1'b0;
      remaining_blocks      <= '0;
      load_tail_offset      <= '0;
      load_window_last      <= 1'b0;
      tail_base_addr        <= '0;
    end else begin
      dma_start     <= 1'b0;
      bias_switch_d <= bias_switch;

      if (init_cfg) begin
        cfg_bias_base        <= bias_base;
        cfg_m                <= count_t'(m);
        cfg_bias_step_blocks <= count_t'(bias_step_blocks);
        num_blocks           <= '0;
        last_block_elems     <= '0;
        step_blocks_eff      <= count_t'(1);
        last_group_start_idx <= '0;
        current_is_last_group <= 1'b1;
        current_block_idx    <= '0;
        load_block_idx       <= '0;
        group_blocks_needed  <= '0;
        load_blocks_count    <= '0;
        active_bank          <= 1'b0;
        load_bank            <= 1'b0;
        switch_pending       <= 1'b0;
        load_bias_req        <= 1'b0;
        dma_base_addr        <= bias_base;
        dma_rows_to_read     <= '0;
        dma_burst_len_m1     <= '0;
        dma_row_offset      <= '0;
        tail_pending        <= 1'b0;
        remaining_blocks    <= '0;
        load_tail_offset    <= '0;
        load_window_last    <= 1'b0;
        tail_base_addr      <= '0;
        state                <= S_INIT_GEOM;
      end else begin
        unique case (state)
          S_IDLE: begin
            load_bias_req <= 1'b0;
            switch_pending <= 1'b0;
          end

          S_INIT_GEOM: begin
            // bias_base==0 means that this operation has no bias tensor.
            // Keep the loader idle instead of reading address zero.
            num_blocks       <= ((cfg_bias_base == '0) || (cfg_m == '0)) ? '0 :
                                initial_num_blocks;
            last_block_elems <= (cfg_m == '0) ? '0 :
                                (((cfg_m & count_t'(SIZE - 1)) == '0)
                                  ? count_t'(SIZE)
                                  : (cfg_m & count_t'(SIZE - 1)));
            step_blocks_eff  <= (cfg_bias_step_blocks == '0) ? count_t'(1) :
                                cfg_bias_step_blocks;
            state            <= S_INIT_LAST;
          end

          S_INIT_LAST: begin
            last_group_start_idx <= (num_blocks <= step_blocks_eff) ? '0 :
                                    (num_blocks - step_blocks_eff);
            state                <= S_INIT_MARK;
          end

          S_INIT_MARK: begin
            current_is_last_group <= (num_blocks == '0) ||
                                     (last_group_start_idx == '0);
            current_block_idx     <= '0;
            load_block_idx        <= '0;
            active_bank           <= 1'b0;
            load_bank             <= 1'b0;
            remaining_blocks      <= num_blocks;
            state                 <= S_INIT_GROUP;
          end

          S_INIT_GROUP: begin
            group_blocks_needed <= (num_blocks == '0) ? '0 :
                                   (current_is_last_group
                                     ? num_blocks
                                     : step_blocks_eff);
            load_blocks_count <= bounded_load_count;
            load_tail_offset <= bounded_load_count - count_t'(1);
            load_window_last <= num_blocks <= count_t'(GROUP_BLOCKS_MAX);
            state               <= S_CMD;
          end

          S_CMD: begin
            dma_base_addr    <= command_address_o_sum;
            dma_rows_to_read <= split_tail_group ? load_rows_without_tail : load_rows_full;
            dma_row_offset  <= '0;
            tail_pending    <= split_tail_group;
            if (group_blocks_needed == '0) begin
              dma_burst_len_m1 <= 8'd0;
            end else if ((load_blocks_count == count_t'(1)) && load_window_last) begin
              dma_burst_len_m1 <= 8'((32'(last_block_elems) + BUS_WIDTH/32-1)/(BUS_WIDTH/32) - 1);
            end else begin
              dma_burst_len_m1 <= 8'((SIZE + BUS_WIDTH/32-1)/(BUS_WIDTH/32) - 1);
            end
            if (group_blocks_needed == '0) begin
              switch_pending <= 1'b0;
              load_bias_req  <= 1'b0;
              state          <= S_IDLE;
            end else if (load_block_valid) begin
              active_bank    <= load_block_bank;
              switch_pending <= 1'b0;
              load_bias_req  <= 1'b0;
              state          <= S_WAIT;
            end else begin
              switch_pending <= 1'b1;
              load_bias_req  <= 1'b1;
              state          <= S_REQ;
            end
          end

          S_REQ: begin
            load_bias_req <= 1'b1;
            if (tail_pending) tail_base_addr <= tail_address_o_sum;
            if (load_bias_granted) begin
              load_bias_req <= 1'b0;
              dma_start     <= 1'b1;
              state         <= S_LOAD;
            end
          end

          S_LOAD: begin
            if (dma_done) begin
              if (tail_pending) begin
                // The final partial block has its own bounded read. Both
                // requests fill the same resident group before it is visible.
                dma_base_addr <= tail_base_addr;
                dma_rows_to_read <= REG_WIDTH'(1);
                dma_burst_len_m1 <= 8'((32'(last_block_elems) + BUS_WIDTH/32-1)/(BUS_WIDTH/32) - 1);
                dma_row_offset <= load_blocks_count - count_t'(1);
                tail_pending <= 1'b0;
                load_bias_req <= 1'b1;
                state <= S_REQ;
              end else begin
                active_bank    <= load_bank;
                switch_pending <= 1'b0;
                state          <= S_WAIT;
              end
            end
          end

          S_WAIT: begin
            if (bias_switch_rise) begin
              if (current_is_last_group && bias_last_loop) begin
                load_bias_req   <= 1'b0;
                switch_pending  <= 1'b0;
                state           <= S_IDLE;
              end else begin
                switch_pending        <= (num_blocks != '0);
                load_bank             <= ~active_bank;
                state                 <= (num_blocks == '0) ? S_IDLE : S_NEXT_IDX;
              end
            end
          end

          S_NEXT_IDX: begin
            load_block_idx <= current_is_last_group ? '0 :
                              next_index_o_sum;
            state          <= S_NEXT_MARK;
          end

          S_NEXT_MARK: begin
            current_block_idx     <= load_block_idx;
            current_is_last_group <= (num_blocks == '0) ||
                                     (load_block_idx >= last_group_start_idx);
            remaining_blocks      <= remaining_o_sum;
            state                 <= S_NEXT_GROUP;
          end

          S_NEXT_GROUP: begin
            group_blocks_needed <= (num_blocks == '0) ? '0 :
                                   (current_is_last_group
                                     ? remaining_blocks
                                     : step_blocks_eff);
            load_blocks_count <= bounded_load_count;
            load_tail_offset <= bounded_load_count - count_t'(1);
            load_window_last <= remaining_blocks <= count_t'(GROUP_BLOCKS_MAX);
            state               <= S_CMD;
          end

          default: state <= S_IDLE;
        endcase
      end
    end
  end

  wire unused_dma_busy = dma_busy;

endmodule
