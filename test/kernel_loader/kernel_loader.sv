module kernel_loader #(
    parameter int unsigned DATA_WIDTH   = 8,
    parameter int unsigned SIZE         = 4,
    parameter int unsigned BUS_WIDTH    = 32,
    parameter int unsigned REG_WIDTH    = 32,
    parameter int unsigned CACHE_BLOCKS = 1
) (
    input  logic                        clk,
    input  logic                        rst_n,
    input  logic                        init_cfg,
    output logic                        load_weight_req,
    input  logic                        load_weight_granted,
    input  logic                        send_weight_trigger,
    input  logic [REG_WIDTH-1:0]        k,
    input  logic [REG_WIDTH-1:0]        n,
    input  logic [REG_WIDTH-1:0]        m,
    input  logic [REG_WIDTH-1:0]        rhs_base,
    input  logic [REG_WIDTH-1:0]        rhs_row_stride_b,
    input  logic signed [REG_WIDTH-1:0] rhs_zp,
    input  logic [REG_WIDTH-1:0]        ia_reuse_num,
    input  logic [REG_WIDTH-1:0]        w_reuse_num,
    output logic                        icb_cmd_valid,
    input  logic                        icb_cmd_ready,
    output logic                        icb_cmd_read,
    output logic [REG_WIDTH-1:0]        icb_cmd_addr,
    output logic [3:0]                  icb_cmd_len,
    input  logic                        icb_rsp_valid,
    output logic                        icb_rsp_ready,
    input  logic [BUS_WIDTH-1:0]        icb_rsp_rdata,
    input  logic                        icb_rsp_err,
    output logic                        weight_sending_done,
    output logic                        store_weight_req,
    output logic signed [DATA_WIDTH-1:0] weight_out [SIZE],
    output logic                        weight_data_valid
);

  typedef enum logic [1:0] {TOP_IDLE, TOP_INIT, TOP_RUN} top_state_t;

  top_state_t top_state;

  logic [REG_WIDTH-1:0] cfg_k, cfg_n, cfg_m;
  logic [REG_WIDTH-1:0] cfg_rhs_base, cfg_rhs_row_stride_b;
  logic signed [REG_WIDTH-1:0] cfg_rhs_zp;
  logic [REG_WIDTH-1:0] cfg_ia_reuse_num, cfg_w_reuse_num;

  logic cfg_valid;
  logic ctrl_all_done;

  logic                        dma_start;
  logic [REG_WIDTH-1:0]        dma_tile_base_addr;
  logic [REG_WIDTH-1:0]        dma_rows_to_read;
  logic [REG_WIDTH-1:0]        dma_row_stride_b;
  logic [REG_WIDTH-1:0]        dma_valid_cols;
  logic signed [REG_WIDTH-1:0] dma_rhs_zp;
  logic                        buf_load_start;
  logic                        buf_send_start;
  logic                        dma_busy;
  logic                        dma_done;

  logic                        dma_row_valid;
  logic [$clog2(SIZE)-1:0]     dma_row_idx;
  logic signed [DATA_WIDTH-1:0] dma_row_data [SIZE];

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      top_state          <= TOP_IDLE;
      cfg_valid          <= 1'b0;
      cfg_k              <= '0;
      cfg_n              <= '0;
      cfg_m              <= '0;
      cfg_rhs_base       <= '0;
      cfg_rhs_row_stride_b <= '0;
      cfg_rhs_zp         <= '0;
      cfg_ia_reuse_num   <= '0;
      cfg_w_reuse_num    <= '0;
    end else begin
      case (top_state)
        TOP_IDLE: begin
          cfg_valid <= 1'b0;
          if (init_cfg) begin
            top_state <= TOP_INIT;
          end
        end

        TOP_INIT: begin
          cfg_k               <= k;
          cfg_n               <= n;
          cfg_m               <= m;
          cfg_rhs_base        <= rhs_base;
          cfg_rhs_row_stride_b<= rhs_row_stride_b;
          cfg_rhs_zp          <= rhs_zp;
          cfg_ia_reuse_num    <= ia_reuse_num;
          cfg_w_reuse_num     <= w_reuse_num;
          cfg_valid           <= 1'b1;
          top_state           <= TOP_RUN;
        end

        TOP_RUN: begin
          if (ctrl_all_done) begin
            cfg_valid  <= 1'b0;
            top_state  <= TOP_IDLE;
          end
        end
      endcase
    end
  end

  kernel_loader_ctrl #(
    .SIZE      (SIZE),
    .REG_WIDTH (REG_WIDTH)
  ) u_ctrl (
    .clk                   (clk),
    .rst_n                 (rst_n),
    .cfg_valid             (cfg_valid),
    .cfg_k                 (cfg_k),
    .cfg_n                 (cfg_n),
    .cfg_m                 (cfg_m),
    .cfg_rhs_base          (cfg_rhs_base),
    .cfg_rhs_row_stride_b  (cfg_rhs_row_stride_b),
    .cfg_rhs_zp            (cfg_rhs_zp),
    .cfg_ia_reuse_num      (cfg_ia_reuse_num),
    .cfg_w_reuse_num       (cfg_w_reuse_num),
    .load_weight_granted   (load_weight_granted),
    .send_weight_trigger    (send_weight_trigger),
    .buf_weight_data_valid  (weight_data_valid),
    .buf_weight_sending_done(weight_sending_done),
    .load_weight_req       (load_weight_req),
    .dma_start             (dma_start),
    .dma_tile_base_addr    (dma_tile_base_addr),
    .dma_rows_to_read      (dma_rows_to_read),
    .dma_row_stride_b      (dma_row_stride_b),
    .dma_valid_cols        (dma_valid_cols),
    .dma_rhs_zp            (dma_rhs_zp),
    .buf_load_start        (buf_load_start),
    .buf_send_start        (buf_send_start),
    .ctrl_all_done         (ctrl_all_done),
    .tile_row_dbg          (),
    .tile_col_dbg          (),
    .repeat_dbg            ()
  );

  block_dma #(
    .DATA_WIDTH (DATA_WIDTH),
    .SIZE       (SIZE),
    .BUS_WIDTH  (BUS_WIDTH),
    .REG_WIDTH  (REG_WIDTH)
  ) u_dma (
    .clk            (clk),
    .rst_n          (rst_n),
    .start          (dma_start),
    .tile_base_addr (dma_tile_base_addr),
    .row_stride_b   (dma_row_stride_b),
    .rows_to_read   (dma_rows_to_read),
    .valid_cols     (dma_valid_cols),
    .rhs_zp         (dma_rhs_zp),
    .busy           (dma_busy),
    .done           (dma_done),
    .row_valid      (dma_row_valid),
    .row_idx        (dma_row_idx),
    .row_data       (dma_row_data),
    .icb_cmd_valid  (icb_cmd_valid),
    .icb_cmd_ready  (icb_cmd_ready),
    .icb_cmd_read   (icb_cmd_read),
    .icb_cmd_addr   (icb_cmd_addr),
    .icb_cmd_len    (icb_cmd_len),
    .icb_rsp_valid  (icb_rsp_valid),
    .icb_rsp_ready  (icb_rsp_ready),
    .icb_rsp_rdata  (icb_rsp_rdata),
    .icb_rsp_err    (icb_rsp_err)
  );

  kernel_loader_buffer #(
    .DATA_WIDTH (DATA_WIDTH),
    .SIZE       (SIZE)
  ) u_buf (
    .clk                 (clk),
    .rst_n               (rst_n),
    .load_start          (buf_load_start),
    .row_valid           (dma_row_valid),
    .row_idx             (dma_row_idx),
    .row_data            (dma_row_data),
    .load_done           (dma_done),
    .send_start          (buf_send_start),
    .weight_data_valid   (weight_data_valid),
    .weight_sending_done (weight_sending_done),
    .store_weight_req    (store_weight_req),
    .weight_out          (weight_out)
  );

endmodule
