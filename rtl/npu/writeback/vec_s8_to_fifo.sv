// SPDX-License-Identifier: Apache-2.0
`default_nettype none

module vec_s8_to_fifo #(
    parameter integer VLEN  = 16,
    parameter integer BANKS = 16,
    parameter integer BUS_WIDTH = 32,
    parameter integer ENABLE_TRANSPOSE = 1,
    // 启用时，合并输出从开始到完成期间须保持 transpose_mode。
    parameter bit p_cyclic_storage = 1'b0,
    parameter bit p_precomputed_watermark = 1'b0
) (
    input  wire                 clk,
    input  wire                 rst_n,
    input  wire                 in_valid,
    input  wire                 in_tile_done,
    input  wire [   VLEN*8-1:0] in_vec_s8,
    output wire                 oa_fifo_req,
    input  wire                 transpose_mode,
    input  wire                 coalesce_enable,
    input  wire                 coalesce_group_start,
    input  wire [31:0]          coalesce_rows,
    input  wire [31:0]          coalesce_cols,
    input  wire [          31:0] reserve_banks,
    input  wire [31:0] i_ready_bank_threshold,
    input  wire [$clog2(VLEN)-1:0] vec_valid_num_col,
    input  wire [$clog2(VLEN)-1:0] vec_valid_num_row,
    output wire                 output_valid,
    input  wire                 output_ready,
    output wire                 output_row_switch,
    output wire [BUS_WIDTH/8-1:0] output_mask,
    output wire [BUS_WIDTH-1:0] output_data,
    output wire                 fifo_full_flag
);

  generate
    if (ENABLE_TRANSPOSE == 0) begin : g_linear
      wire unused_transpose_mode = transpose_mode;
      vec_s8_to_fifo_linear #(
        .VLEN (VLEN),
        .BANKS(BANKS),
        .BUS_WIDTH(BUS_WIDTH),
        .p_precomputed_watermark(p_precomputed_watermark)
      ) u_linear (
        .clk              (clk),
        .rst_n            (rst_n),
        .in_valid         (in_valid),
        .in_tile_done     (in_tile_done),
        .in_vec_s8        (in_vec_s8),
        .oa_fifo_req      (oa_fifo_req),
        .reserve_banks    (reserve_banks),
        .i_ready_bank_threshold(i_ready_bank_threshold),
        .vec_valid_num_col(vec_valid_num_col),
        .vec_valid_num_row(vec_valid_num_row),
        .output_valid     (output_valid),
        .output_ready     (output_ready),
        .output_row_switch(output_row_switch),
        .output_mask      (output_mask),
        .output_data      (output_data),
        .fifo_full_flag   (fifo_full_flag)
      );

    end else begin : g_full
      // Two register entries isolate the RAM read controls from DMA READY.
      // Start a new tile only after the previous tile's entries drain, so
      // the writer has advanced the tail dimensions before they are sampled.
      localparam integer SKID_WIDTH = BUS_WIDTH + BUS_WIDTH/8 + 1;
      logic [SKID_WIDTH-1:0] skid[2];
      logic skid_rd, skid_wr;
      logic [1:0] skid_count;
      wire inner_req, inner_valid, inner_switch;
      wire [BUS_WIDTH/8-1:0] inner_mask;
      wire [BUS_WIDTH-1:0] inner_data;
      logic writer_ready_q;
      always_ff @(posedge clk) begin
        if(!rst_n) writer_ready_q<=0;
        else writer_ready_q<=output_ready;
      end
      wire inner_ready=writer_ready_q && skid_count<2;
      wire put=inner_valid && inner_ready;
      wire take=output_valid && output_ready;
      assign oa_fifo_req=inner_req || inner_valid || skid_count!=0;
      assign output_valid=skid_count!=0;
      assign output_data=skid[skid_rd][BUS_WIDTH-1:0];
      assign output_mask=skid[skid_rd][BUS_WIDTH+:BUS_WIDTH/8];
      assign output_row_switch=take && skid[skid_rd][SKID_WIDTH-1];
      always_ff @(posedge clk) begin
        if(!rst_n) begin skid_rd<=0;skid_wr<=0;skid_count<=0;end
        else begin
          case({put,take})
            2'b10: skid_count<=skid_count+1'b1;
            2'b01: skid_count<=skid_count-1'b1;
            default:;
          endcase
          if(put) begin skid[skid_wr]<={inner_switch,inner_mask,inner_data};skid_wr<=!skid_wr;end
          if(take) skid_rd<=!skid_rd;
        end
      end
      vec_s8_to_fifo_full #(
        .VLEN (VLEN),
        .BANKS(BANKS),
        .BUS_WIDTH(BUS_WIDTH),
        .ENABLE_TRANSPOSE(ENABLE_TRANSPOSE),
        .p_cyclic_storage(p_cyclic_storage),
        .p_precomputed_watermark(p_precomputed_watermark)
      ) u_full (
        .clk              (clk),
        .rst_n            (rst_n),
        .start_permitted   (skid_count==0),
        .in_valid         (in_valid),
        .in_tile_done     (in_tile_done),
        .in_vec_s8        (in_vec_s8),
        .oa_fifo_req      (inner_req),
        .transpose_mode   (transpose_mode),
        .coalesce_enable  (coalesce_enable),
        .coalesce_group_start(coalesce_group_start),
        .coalesce_rows    (coalesce_rows),
        .coalesce_cols    (coalesce_cols),
        .reserve_banks    (reserve_banks),
        .i_ready_bank_threshold(i_ready_bank_threshold),
        .vec_valid_num_col(vec_valid_num_col),
        .vec_valid_num_row(vec_valid_num_row),
        .output_valid     (inner_valid),
        .output_ready     (inner_ready),
        .output_row_switch(inner_switch),
        .output_mask      (inner_mask),
        .output_data      (inner_data),
        .fifo_full_flag   (fifo_full_flag)
      );

    end
  endgenerate

endmodule

`default_nettype wire
