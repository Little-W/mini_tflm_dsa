// 两个数据存储体保存偏置分组，命中时复用驻留数据，未命中时请求 DMA 装载。

module bias_loader_ctrl #(
    parameter int unsigned SIZE      = 8,
    parameter int unsigned BUS_WIDTH = 32,
    parameter int unsigned REG_WIDTH = 32,
    parameter int unsigned COUNT_WIDTH = REG_WIDTH,
    parameter int unsigned GROUP_BLOCKS_MAX = 1
) (
    input  logic clk /* 工作时钟 */,
    input  logic rst_n /* 低有效复位 */,

    input  logic                 init_cfg /* 接收任务参数并初始化当前模块 */,
    input  logic [REG_WIDTH-1:0] bias_base /* 偏置数组的首字节地址，零表示不使用偏置 */,
    input  logic [REG_WIDTH-1:0] m /* 输出矩阵列数 */,
    input  logic [REG_WIDTH-1:0] bias_step_blocks /* 每次偏置切换前进的偏置块数 */,
    input  logic                 bias_switch /* 切换到下一偏置分组 */,
    input  logic                 bias_last_loop /* 当前任务已进入最后一个偏置复用循环 */,

    output logic                 load_bias_req /* 请求共享 DMA 装载偏置分组 */,
    input  logic                 load_bias_granted /* 偏置装载请求已获得共享 DMA 授予 */,

    input  logic                 dma_busy /* DMA 接口：块传输正在执行 */,
    input  logic                 dma_done /* DMA 接口：本次块传输完成 */,
    input  logic                 load_block_valid /* 缓冲区确认一个偏置块已经写入完成 */,
    input  logic                 load_block_bank /* 已写入完成偏置块所属的存储体 */,

    output logic                 dma_start /* DMA 接口：启动本次块传输 */,
    output logic [REG_WIDTH-1:0] dma_base_addr /* DMA 接口：本次传输的首字节地址 */,
    output logic [REG_WIDTH-1:0] dma_rows_to_read /* DMA 接口：本次块传输的行数 */,
    output logic [7:0]           dma_burst_len_m1 /* DMA 接口：每行突发传输拍数减一 */,
    output logic [COUNT_WIDTH-1:0] dma_row_offset /* 当前 DMA 数据在目标偏置分组内的行偏移 */,
    output logic                 load_group_done /* 目标偏置分组的全部块装载完成 */,
    output logic                 load_bank /* 当前 DMA 装载写入的偏置存储体 */,

    output logic [COUNT_WIDTH-1:0] current_block_idx /* 当前正在使用的偏置分组起始块编号 */,
    output logic [COUNT_WIDTH-1:0] load_block_idx /* 当前正在装载的偏置块编号 */,
    output logic [COUNT_WIDTH-1:0] group_blocks_needed /* 当前偏置分组实际需要的块数 */,
    output logic [COUNT_WIDTH-1:0] o_current_block_idx_nxt /* 偏置分组切换后的起始块编号 */,
    output logic [COUNT_WIDTH-1:0] o_group_blocks_needed_nxt /* 下一偏置分组实际需要的块数 */,
    output logic [COUNT_WIDTH-1:0] load_blocks_count /* 本次装载已完成的偏置块数 */,
    output logic                 active_bank /* 当前供阵列读取的偏置存储体 */,
    output logic                 switch_pending /* 等待目标偏置分组就绪的切换请求 */
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
  // 准备阶段先保存原始元素数，随后复用为分块数量。
  count_t geometry_count;
  count_t last_block_elems;
  count_t step_blocks;
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

  localparam int unsigned p_arithmetic_width = (REG_WIDTH > CNT_W) ? REG_WIDTH : CNT_W;
  logic [p_arithmetic_width-1:0] arithmetic_i_a;
  logic [p_arithmetic_width-1:0] arithmetic_i_b;
  logic [p_arithmetic_width-1:0] arithmetic_o_sum;
  logic arithmetic_i_carry;
  logic arithmetic_o_carry;

  // 各项地址和计数运算分别属于互斥状态，共用一个完整位宽的加减单元。
  // 运算结果在对应状态写入目的寄存器，状态之间保持原有准备周期。
  always_comb begin
    arithmetic_i_a = '0;
    arithmetic_i_b = '0;
    arithmetic_i_carry = 1'b0;
    case (state)
      S_INIT_LAST: begin
        arithmetic_i_a = p_arithmetic_width'(geometry_count);
        arithmetic_i_b = ~p_arithmetic_width'(step_blocks);
        arithmetic_i_carry = 1'b1;
      end
      S_CMD: begin
        arithmetic_i_a = p_arithmetic_width'(cfg_bias_base);
        arithmetic_i_b = p_arithmetic_width'(REG_WIDTH'(load_block_idx) << BLOCK_ADDR_SHIFT);
      end
      S_REQ: begin
        arithmetic_i_a = p_arithmetic_width'(dma_base_addr);
        arithmetic_i_b = p_arithmetic_width'(REG_WIDTH'(load_tail_offset) << BLOCK_ADDR_SHIFT);
      end
      S_NEXT_IDX: begin
        arithmetic_i_a = p_arithmetic_width'(current_block_idx);
        arithmetic_i_b = p_arithmetic_width'(step_blocks);
      end
      S_NEXT_MARK: begin
        arithmetic_i_a = p_arithmetic_width'(geometry_count);
        arithmetic_i_b = ~p_arithmetic_width'(load_block_idx);
        arithmetic_i_carry = 1'b1;
      end
    endcase
  end
  (* keep_hierarchy = "yes" *)
  parallel_prefix_add #(
      .p_width(p_arithmetic_width), .p_group_width(8), .p_preserve_groups(1'b1),
      .p_dsp_split_width((p_arithmetic_width+1)/2), .p_keep_carry(1'b0)
  ) u_arithmetic (
      .i_a(arithmetic_i_a), .i_b(arithmetic_i_b), .i_carry(arithmetic_i_carry),
      .o_sum(arithmetic_o_sum), .o_carry(arithmetic_o_carry)
  );
  assign bounded_load_count_narrow = (remaining_blocks < count_t'(GROUP_BLOCKS_MAX)) ?
      load_count_t'(remaining_blocks) : load_count_t'(GROUP_BLOCKS_MAX);
  assign bounded_load_count = count_t'(bounded_load_count_narrow);

  // 二次幂分块先取商再加低位非零标志，显式保留原计数宽度的回绕。
  if ((SIZE == (1 << SIZE_SHIFT)) && (CNT_W > SIZE_SHIFT)) begin : g_initial_blocks
    localparam int unsigned QUOTIENT_W = CNT_W - SIZE_SHIFT;
    logic [QUOTIENT_W-1:0] rounded_i_a, rounded_i_b, rounded_o_sum;
    logic rounded_i_carry, rounded_o_carry;
    assign rounded_i_a = QUOTIENT_W'(geometry_count >> SIZE_SHIFT);
    assign rounded_i_b = '0;
    assign rounded_i_carry = (geometry_count & count_t'(SIZE - 1)) != '0;
    parallel_prefix_add #(.p_width(QUOTIENT_W)) u_rounded (
        .i_a(rounded_i_a), .i_b(rounded_i_b), .i_carry(rounded_i_carry),
        .o_sum(rounded_o_sum), .o_carry(rounded_o_carry)
    );
    assign initial_num_blocks = count_t'(rounded_o_sum);
  end else begin : g_initial_blocks_general
    assign initial_num_blocks = (geometry_count + count_t'(SIZE - 1)) >> SIZE_SHIFT;
  end

  logic bias_switch_rise;
  assign bias_switch_rise = bias_switch && !bias_switch_d;
  logic split_tail_group;
  assign split_tail_group = load_window_last &&
                          (load_blocks_count > count_t'(1)) &&
                          (last_block_elems != count_t'(SIZE));
  logic [REG_WIDTH-1:0] load_rows_full;
  logic [REG_WIDTH-1:0] load_rows_without_tail;
  count_t final_row_offset;
  // 完整行数和扣除尾块后的行数并行计算，范围判断只选择最终结果。
  assign load_rows_full = REG_WIDTH'(load_blocks_count);
  assign load_rows_without_tail = load_rows_full - REG_WIDTH'(1);
  assign final_row_offset = load_blocks_count - count_t'(1);
  assign load_group_done = dma_done && !tail_pending;

  // 控制器和驻留比较共用本边沿的分组位置，命中状态与分组寄存器同时更新。
  always_comb begin
    o_current_block_idx_nxt = current_block_idx;
    o_group_blocks_needed_nxt = group_blocks_needed;
    case (state)
      S_INIT_MARK: o_current_block_idx_nxt = '0;
      S_NEXT_MARK: o_current_block_idx_nxt = load_block_idx;
      S_INIT_GROUP: begin
        o_group_blocks_needed_nxt = (geometry_count == '0) ? '0 :
            (current_is_last_group ? geometry_count : step_blocks);
      end
      S_NEXT_GROUP: begin
        o_group_blocks_needed_nxt = (geometry_count == '0) ? '0 :
            (current_is_last_group ? remaining_blocks : step_blocks);
      end
      default: begin
      end
    endcase
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state                  <= S_IDLE;
      cfg_bias_base          <= '0;
      geometry_count         <= '0;
      last_block_elems       <= '0;
      step_blocks        <= count_t'(1);
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
        geometry_count       <= count_t'(m);
        last_block_elems     <= '0;
        step_blocks      <= (count_t'(bias_step_blocks) == '0) ? count_t'(1) :
                            count_t'(bias_step_blocks);
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
        current_block_idx <= o_current_block_idx_nxt;
        group_blocks_needed <= o_group_blocks_needed_nxt;
        case (state)
          S_IDLE: begin
            load_bias_req <= 1'b0;
            switch_pending <= 1'b0;
          end

          S_INIT_GEOM: begin
            // 零基地址表示本次任务不使用偏置张量，准备结果保持零块。
            geometry_count       <= ((cfg_bias_base == '0) || (geometry_count == '0)) ? '0 :
                                initial_num_blocks;
            last_block_elems <= (geometry_count == '0) ? '0 :
                                (((geometry_count & count_t'(SIZE - 1)) == '0)
                                  ? count_t'(SIZE)
                                  : (geometry_count & count_t'(SIZE - 1)));
            state            <= S_INIT_LAST;
          end

          S_INIT_LAST: begin
            last_group_start_idx <= (geometry_count <= step_blocks) ? '0 :
                                    count_t'(arithmetic_o_sum);
            state                <= S_INIT_MARK;
          end

          S_INIT_MARK: begin
            current_is_last_group <= (geometry_count == '0) ||
                                     (last_group_start_idx == '0);
            load_block_idx        <= '0;
            active_bank           <= 1'b0;
            load_bank             <= 1'b0;
            remaining_blocks      <= geometry_count;
            state                 <= S_INIT_GROUP;
          end

          S_INIT_GROUP: begin
            load_blocks_count <= bounded_load_count;
            load_tail_offset <= bounded_load_count - count_t'(1);
            load_window_last <= geometry_count <= count_t'(GROUP_BLOCKS_MAX);
            state               <= S_CMD;
          end

          S_CMD: begin
            dma_base_addr    <= REG_WIDTH'(arithmetic_o_sum);
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
            if (tail_pending) tail_base_addr <= REG_WIDTH'(arithmetic_o_sum);
            if (load_bias_granted) begin
              load_bias_req <= 1'b0;
              dma_start     <= 1'b1;
              state         <= S_LOAD;
            end
          end

          S_LOAD: begin
            if (dma_done) begin
              if (tail_pending) begin
                // 尾部不足一块时单独请求，两次装载完成后才公开该驻留分组。
                dma_base_addr <= tail_base_addr;
                dma_rows_to_read <= REG_WIDTH'(1);
                dma_burst_len_m1 <= 8'((32'(last_block_elems) + BUS_WIDTH/32-1)/(BUS_WIDTH/32) - 1);
                dma_row_offset <= final_row_offset;
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
                switch_pending        <= (geometry_count != '0);
                load_bank             <= ~active_bank;
                state                 <= (geometry_count == '0) ? S_IDLE : S_NEXT_IDX;
              end
            end
          end

          S_NEXT_IDX: begin
            load_block_idx <= current_is_last_group ? '0 :
                              count_t'(arithmetic_o_sum);
            state          <= S_NEXT_MARK;
          end

          S_NEXT_MARK: begin
            current_is_last_group <= (geometry_count == '0) ||
                                     (load_block_idx >= last_group_start_idx);
            remaining_blocks      <= count_t'(arithmetic_o_sum);
            state                 <= S_NEXT_GROUP;
          end

          S_NEXT_GROUP: begin
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

endmodule
