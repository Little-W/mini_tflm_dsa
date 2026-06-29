/*
 * bias_loader_ctrl — 块顺序控制与双缓冲切换
 * ============================================================
 */

module bias_loader_ctrl #(
    parameter int unsigned SIZE      = 8,
    parameter int unsigned REG_WIDTH = 32
) (
    input  logic clk,
    input  logic rst_n,

    input  logic                 init_cfg,
    input  logic [REG_WIDTH-1:0] bias_base,
    input  logic [REG_WIDTH-1:0] m,
    input  logic                 bias_switch,
    input  logic                 bias_last_loop,

    output logic                 load_bias_req,
    input  logic                 load_bias_granted,

    input  logic                 dma_busy,
    input  logic                 dma_done,

    output logic                 dma_start,
    output logic [REG_WIDTH-1:0] dma_base_addr,
    output logic [REG_WIDTH-1:0] dma_rows_to_read,
    output logic [3:0]           dma_burst_len_m1,
    output logic                 load_bank,

    output logic [REG_WIDTH-1:0] current_block_idx,
    output logic [REG_WIDTH-1:0] load_block_idx,
    output logic                 active_bank
);

  localparam int BYTES_PER_ELEM = 4;

  typedef enum logic [2:0] {
    S_IDLE = 3'd0,
    S_REQ  = 3'd1,
    S_LOAD = 3'd2,
    S_WAIT = 3'd3,
    S_DONE = 3'd4
  } state_t;

  state_t state;
  logic [REG_WIDTH-1:0] num_blocks;
  logic [REG_WIDTH-1:0] last_block_elems;
  logic                 bias_switch_d;
  logic                 bias_switch_pending;

  function automatic logic [REG_WIDTH-1:0] f_block_elems(input logic [REG_WIDTH-1:0] blk_idx);
    if (num_blocks == 0) begin
      f_block_elems = '0;
    end else if (blk_idx < num_blocks - 1) begin
      f_block_elems = REG_WIDTH'(SIZE);
    end else begin
      f_block_elems = last_block_elems;
    end
  endfunction

  function automatic logic [REG_WIDTH-1:0] f_block_beats(input logic [REG_WIDTH-1:0] blk_idx);
    f_block_beats = f_block_elems(blk_idx);
  endfunction

  function automatic logic [3:0] f_block_burst_len(input logic [REG_WIDTH-1:0] blk_idx);
    if (f_block_elems(blk_idx) == 0) begin
      f_block_burst_len = 4'd0;
    end else begin
      f_block_burst_len = 4'(f_block_elems(blk_idx) - 1);
    end
  endfunction

  function automatic logic [REG_WIDTH-1:0] f_next_block(input logic [REG_WIDTH-1:0] blk_idx);
    if (num_blocks == 0) begin
      f_next_block = '0;
    end else if (blk_idx < num_blocks - 1) begin
      f_next_block = blk_idx + 1;
    end else begin
      f_next_block = '0;
    end
  endfunction

  function automatic logic f_has_next(input logic [REG_WIDTH-1:0] blk_idx);
    if (num_blocks == 0) begin
      f_has_next = 1'b0;
    end else if (blk_idx < num_blocks - 1) begin
      f_has_next = 1'b1;
    end else begin
      f_has_next = !bias_last_loop;
    end
  endfunction

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state             <= S_IDLE;
      num_blocks        <= '0;
      last_block_elems  <= '0;
      current_block_idx <= '0;
      load_block_idx    <= '0;
      active_bank       <= 1'b0;
      load_bank         <= 1'b0;
      load_bias_req     <= 1'b0;
      dma_start         <= 1'b0;
      dma_base_addr     <= '0;
      dma_rows_to_read  <= '0;
      dma_burst_len_m1  <= '0;
      bias_switch_d     <= 1'b0;
      bias_switch_pending <= 1'b0;
    end else begin
      dma_start <= 1'b0;
      bias_switch_d <= bias_switch;

      if (bias_switch && !bias_switch_d) begin
        bias_switch_pending <= 1'b1;
      end

      if (init_cfg) begin
        automatic logic [REG_WIDTH-1:0] init_num_blocks;
        automatic logic [REG_WIDTH-1:0] init_last_block_elems;
        automatic logic [REG_WIDTH-1:0] init_rows_to_read;
        automatic logic [3:0]           init_burst_len_m1;

        init_num_blocks       = (m == 0) ? '0 : ((m + SIZE - 1) / SIZE);
        init_last_block_elems = (m == 0) ? '0 : ((m % SIZE) == 0 ? REG_WIDTH'(SIZE) : (m % SIZE));
        if (m == 0) begin
          init_rows_to_read = '0;
          init_burst_len_m1  = 4'd0;
        end else if (init_num_blocks <= 1) begin
          init_rows_to_read = REG_WIDTH'(1);
          init_burst_len_m1 = 4'(init_last_block_elems - 1);
        end else begin
          init_rows_to_read = REG_WIDTH'(1);
          init_burst_len_m1 = 4'(SIZE - 1);
        end

        num_blocks        <= init_num_blocks;
        last_block_elems  <= init_last_block_elems;
        current_block_idx <= '0;
        load_block_idx    <= '0;
        active_bank       <= 1'b0;
        load_bank         <= 1'b0;
        load_bias_req     <= (m != 0);
        dma_base_addr     <= bias_base;
        dma_rows_to_read  <= init_rows_to_read;
        dma_burst_len_m1  <= init_burst_len_m1;
        bias_switch_pending <= 1'b0;
        state             <= (m == 0) ? S_DONE : S_REQ;
      end else begin
        case (state)
          S_IDLE: begin
            load_bias_req <= 1'b0;
          end

          S_REQ: begin
            load_bias_req <= 1'b1;

            if (bias_switch_pending && !load_bias_granted) begin
              bias_switch_pending <= 1'b0;
              current_block_idx    <= load_block_idx;
              active_bank          <= load_bank;
            end

            if (load_bias_granted) begin
              load_bias_req <= 1'b0;
              dma_start     <= 1'b1;
              state         <= S_LOAD;
            end
          end

          S_LOAD: begin
            if (dma_done) begin
              if (load_block_idx == current_block_idx && f_has_next(current_block_idx)) begin
                load_bank         <= ~active_bank;
                load_block_idx    <= f_next_block(current_block_idx);
                dma_base_addr     <= bias_base + REG_WIDTH'(f_next_block(current_block_idx) * SIZE * BYTES_PER_ELEM);
                dma_rows_to_read  <= REG_WIDTH'(1);
                dma_burst_len_m1  <= f_block_burst_len(f_next_block(current_block_idx));
                load_bias_req     <= 1'b1;
                state             <= S_REQ;
              end else begin
                state <= S_WAIT;
              end
            end
          end

          S_WAIT: begin
            if (bias_switch_pending) begin
              bias_switch_pending <= 1'b0;
              if (current_block_idx == num_blocks - 1 && bias_last_loop) begin
                state         <= S_DONE;
                load_bias_req <= 1'b0;
              end else begin
                logic [REG_WIDTH-1:0] next_blk;
                logic [REG_WIDTH-1:0] next_next_blk;

                next_blk = f_next_block(current_block_idx);
                current_block_idx <= next_blk;
                active_bank       <= ~active_bank;
                load_bank         <= active_bank;

                next_next_blk = f_next_block(next_blk);
                if (f_has_next(next_blk)) begin
                  load_block_idx   <= next_next_blk;
                  dma_base_addr    <= bias_base + REG_WIDTH'(next_next_blk * SIZE * BYTES_PER_ELEM);
                  dma_rows_to_read <= REG_WIDTH'(1);
                  dma_burst_len_m1 <= f_block_burst_len(next_next_blk);
                  load_bias_req    <= 1'b1;
                  state            <= S_REQ;
                end
              end
            end
          end

          S_DONE: begin
            load_bias_req <= 1'b0;
          end

          default: state <= S_IDLE;
        endcase
      end
    end
  end

endmodule