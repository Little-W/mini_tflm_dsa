module block_dma #(
    parameter int unsigned DATA_WIDTH = 8,
    parameter int unsigned SIZE       = 4,
    parameter int unsigned BUS_WIDTH  = 32,
    parameter int unsigned REG_WIDTH  = 32
) (
    input  logic                         clk,
    input  logic                         rst_n,
    input  logic                         start,
    input  logic [REG_WIDTH-1:0]         tile_base_addr,
    input  logic [REG_WIDTH-1:0]         row_stride_b,
    input  logic [REG_WIDTH-1:0]         rows_to_read,
    input  logic [REG_WIDTH-1:0]         valid_cols,
    input  logic signed [REG_WIDTH-1:0]  rhs_zp,
    output logic                         busy,
    output logic                         done,
    output logic                         row_valid,
    output logic [$clog2(SIZE)-1:0]      row_idx,
    output logic signed [DATA_WIDTH-1:0] row_data [SIZE],
    output logic                         icb_cmd_valid,
    input  logic                         icb_cmd_ready,
    output logic                         icb_cmd_read,
    output logic [REG_WIDTH-1:0]         icb_cmd_addr,
    output logic [3:0]                   icb_cmd_len,
    input  logic                         icb_rsp_valid,
    output logic                         icb_rsp_ready,
    input  logic [BUS_WIDTH-1:0]         icb_rsp_rdata,
    input  logic                         icb_rsp_err
);

  typedef enum logic [1:0] {S_IDLE, S_ISSUE, S_WAIT_RSP} state_t;
  state_t state;

  logic [REG_WIDTH-1:0] base_r;
  logic [REG_WIDTH-1:0] stride_r;
  logic [REG_WIDTH-1:0] rows_r;
  logic [REG_WIDTH-1:0] row_cnt;

  assign icb_cmd_read  = 1'b1;
  assign icb_cmd_len   = 4'd0;
  assign icb_rsp_ready = (state == S_WAIT_RSP);

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state        <= S_IDLE;
      busy         <= 1'b0;
      done         <= 1'b0;
      row_valid    <= 1'b0;
      row_idx      <= '0;
      row_cnt      <= '0;
      base_r       <= '0;
      stride_r     <= '0;
      rows_r       <= '0;
      icb_cmd_valid <= 1'b0;
      icb_cmd_addr  <= '0;
      for (int i = 0; i < SIZE; i++) begin
        row_data[i] <= '0;
      end
    end else begin
      row_valid <= 1'b0;
      done      <= 1'b0;

      if (start && state == S_IDLE) begin
        busy     <= 1'b1;
        base_r   <= tile_base_addr;
        stride_r <= row_stride_b;
        rows_r   <= rows_to_read;
        row_cnt  <= '0;
        state    <= S_ISSUE;
      end

      case (state)
        S_IDLE: begin
          busy <= 1'b0;
          icb_cmd_valid <= 1'b0;
        end

        S_ISSUE: begin
          busy <= 1'b1;
          if (!icb_cmd_valid) begin
            icb_cmd_valid <= 1'b1;
            icb_cmd_addr  <= base_r + row_cnt * stride_r;
          end
          if (icb_cmd_valid && icb_cmd_ready) begin
            icb_cmd_valid <= 1'b0;
            state <= S_WAIT_RSP;
          end
        end

        S_WAIT_RSP: begin
          busy <= 1'b1;
          if (icb_rsp_valid && icb_rsp_ready) begin
            if (icb_rsp_err) begin
              state <= S_IDLE;
              busy  <= 1'b0;
              done  <= 1'b1;
            end else begin
              for (int c = 0; c < SIZE; c++) begin
                if (c < valid_cols) begin
                  row_data[c] <= $signed(icb_rsp_rdata[c*DATA_WIDTH +: DATA_WIDTH]) + $signed(rhs_zp[DATA_WIDTH-1:0]);
                end else begin
                  row_data[c] <= '0;
                end
              end
              row_idx   <= row_cnt[$clog2(SIZE)-1:0];
              row_valid  <= 1'b1;
              if (row_cnt == rows_r - 1) begin
                done  <= 1'b1;
                state <= S_IDLE;
                busy  <= 1'b0;
              end else begin
                row_cnt <= row_cnt + 1;
                state   <= S_ISSUE;
              end
            end
          end
        end
      endcase
    end
  end

endmodule
