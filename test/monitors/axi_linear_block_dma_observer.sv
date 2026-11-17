// SPDX-License-Identifier: Apache-2.0
`ifndef SYNTHESIS
/* verilator lint_off DECLFILENAME */
module axi_linear_block_dma_observer #(
  parameter int TB_RD_CONTEXT_DEPTH=0,
  parameter int TB_RD_CTX_DEPTH=0,
  parameter int TB_RD_OUTS_MAX=0,
  parameter int TB_RD_OUTS_W=0,
  parameter int TB_RD_TAG_WIDTH=0,
  parameter int TB_SIZE=0,
  parameter int TB_WR_OUTS_W=0
);

    logic dma_trace_en;
    initial begin
        dma_trace_en = 1'b0;
        if ($test$plusargs("NPU_DMA_TRACE")) dma_trace_en = 1'b1;
    end

    initial begin
        assert(TB_RD_CONTEXT_DEPTH > 0 && TB_RD_TAG_WIDTH > 0)
            else $fatal(1,"read context depth and tag width must be positive");
    end
    always_ff @(posedge axi_linear_block_dma.clk) begin
        if (axi_linear_block_dma.rst_n) begin
            if (axi_linear_block_dma.rd_accept_start) assert(axi_linear_block_dma.rd_rows_to_read > 0 && axi_linear_block_dma.rd_rows_to_read <= TB_SIZE)
                else $fatal(1,"read descriptor rows exceed the configured block size");
            if (axi_linear_block_dma.rd_r_last_hs) assert(axi_linear_block_dma.rd_outstanding_cnt != '0 || axi_linear_block_dma.rd_ar_hs)
                else $fatal(1,"read response has no outstanding AXI request");
            assert(32'(axi_linear_block_dma.rd_context_count) <= TB_RD_CTX_DEPTH);
            assert(axi_linear_block_dma.rd_outstanding_cnt <= TB_RD_OUTS_W'(TB_RD_OUTS_MAX));
            if (axi_linear_block_dma.rd_done && dma_trace_en)
                $display("[AXI_DMA_TRACE] rd_done tag=%0d error=%0d contexts=%0d outstanding=%0d",
                         axi_linear_block_dma.rd_response_tag,axi_linear_block_dma.rd_error,axi_linear_block_dma.rd_context_count,axi_linear_block_dma.rd_outstanding_cnt);
        end
    end

    longint unsigned wr_trace_aw_count;
    longint unsigned wr_trace_cross_aw_count;
    longint unsigned wr_trace_w_count;
    logic [TB_WR_OUTS_W-1:0] wr_trace_max_outs;

    always_ff @(posedge axi_linear_block_dma.clk) begin
        if (!axi_linear_block_dma.rst_n) begin
            wr_trace_aw_count       <= '0;
            wr_trace_cross_aw_count <= '0;
            wr_trace_w_count        <= '0;
            wr_trace_max_outs       <= '0;
        end else if (axi_linear_block_dma.wr_start && !axi_linear_block_dma.wr_active && !axi_linear_block_dma.abort) begin
            wr_trace_aw_count       <= '0;
            wr_trace_cross_aw_count <= '0;
            wr_trace_w_count        <= '0;
            wr_trace_max_outs       <= '0;
        end else if (axi_linear_block_dma.wr_active) begin
            if (axi_linear_block_dma.wr_aw_hs) begin
                wr_trace_aw_count <= wr_trace_aw_count + 1'b1;
                if (axi_linear_block_dma.wr_pending_cmd_cross) wr_trace_cross_aw_count <= wr_trace_cross_aw_count + 1'b1;
                if (!axi_linear_block_dma.wr_b_hs && ((axi_linear_block_dma.wr_outstanding_cnt + 1'b1) > wr_trace_max_outs)) begin
                    wr_trace_max_outs <= axi_linear_block_dma.wr_outstanding_cnt + 1'b1;
                end else if (axi_linear_block_dma.wr_b_hs && (axi_linear_block_dma.wr_outstanding_cnt > wr_trace_max_outs)) begin
                    wr_trace_max_outs <= axi_linear_block_dma.wr_outstanding_cnt;
                end
            end
            if (axi_linear_block_dma.wr_w_hs) begin
                wr_trace_w_count <= wr_trace_w_count + 1'b1;
            end
            if (axi_linear_block_dma.wr_done_r && dma_trace_en) begin
                $display("[AXI_DMA_TRACE] wr_done base=%08x stride=%0d rows=%0d len_m1=%0d aw=%0d aw_cross=%0d w=%0d max_out=%0d",
                         axi_linear_block_dma.wr_cfg_base_addr, axi_linear_block_dma.wr_cfg_row_stride, axi_linear_block_dma.wr_cfg_rows,
                         axi_linear_block_dma.wr_cfg_burst_len_m1, wr_trace_aw_count,
                         wr_trace_cross_aw_count, wr_trace_w_count,
                         wr_trace_max_outs);
            end
        end
    end

endmodule
bind axi_linear_block_dma axi_linear_block_dma_observer #(
  .TB_RD_CONTEXT_DEPTH(32'(RD_CONTEXT_DEPTH)),
  .TB_RD_CTX_DEPTH(32'(RD_CTX_DEPTH)),
  .TB_RD_OUTS_MAX(32'(RD_OUTS_MAX)),
  .TB_RD_OUTS_W(32'(RD_OUTS_W)),
  .TB_RD_TAG_WIDTH(32'(RD_TAG_WIDTH)),
  .TB_SIZE(32'(SIZE)),
  .TB_WR_OUTS_W(32'(WR_OUTS_W))
) tb_observer();
/* verilator lint_on DECLFILENAME */
`endif
