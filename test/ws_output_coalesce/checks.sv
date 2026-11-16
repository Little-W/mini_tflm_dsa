// SPDX-License-Identifier: Apache-2.0
module ws_output_transport_checks (
    input logic clk,
    input logic rst_n,
    input logic new_job,
    input logic done,
    input logic awvalid,
    input logic awready,
    input logic [31:0] awaddr,
    input logic [7:0] awlen,
    input logic [2:0] awsize,
    input logic wvalid,
    input logic wready,
    input logic group_start,
    input logic [4:0] group_row_tiles
);
    integer requests, beats, groups, max_burst_bytes, smallest_group;
    always @(posedge clk) begin
        if (!rst_n || new_job) begin
            requests = 0; beats = 0; groups = 0;
            max_burst_bytes = 0; smallest_group = 32;
        end else begin
            if (awvalid && awready) begin
                assert ((awaddr & 4095) + ((32'(awlen) + 1) << awsize) <= 4096)
                    else $fatal(1, "AXI write burst crossed a 4 KiB page");
                requests++;
                if (((int'(awlen) + 1) << awsize) > max_burst_bytes)
                    max_burst_bytes = (int'(awlen) + 1) << awsize;
            end
            if (wvalid && wready) beats++;
            if (group_start) begin
                assert (group_row_tiles != 0)
                    else $fatal(1, "WS descriptor has no populated row tiles");
                groups++;
                if (int'(group_row_tiles) < smallest_group)
                    smallest_group = int'(group_row_tiles);
            end
            if (done)
                $display("WS_OUTPUT_COUNTS aw=%0d w=%0d groups=%0d max_burst_bytes=%0d min_group_row_tiles=%0d",
                         requests, beats, groups, max_burst_bytes, smallest_group);
        end
    end
endmodule

bind tb_matrix_layout ws_output_transport_checks u_ws_output_transport_checks (
    .clk(clk), .rst_n(rst_n), .new_job(new_job), .done(u_dut.npu_done_fire),
    .awvalid(awvalid), .awready(awready), .awaddr(awaddr), .awlen(awlen), .awsize(awsize),
    .wvalid(wvalid), .wready(wready),
    .group_start(u_dut.u_npu_top.oa_coalesce_group_start),
    .group_row_tiles(u_dut.u_npu_top.oa_coalesce_rows)
);

module ws_output_fifo_checks #(
    parameter int BANKS = 32,
    parameter int BANK_WIDTH = 5,
    parameter int COUNT_WIDTH = 5,
    parameter int BANK_COUNT_WIDTH = 6
) (
    input logic clk,
    input logic rst_n,
    input logic coalesce_enable,
    input logic transpose_mode,
    input logic ram_read_en,
    input logic [BANK_WIDTH-1:0] read_bank,
    input logic [8:0] logical_row,
    input logic [BANKS-1:0] bank_ready,
    input logic [COUNT_WIDTH-1:0] bank_count [0:BANKS-1],
    input logic finish,
    input logic [BANK_COUNT_WIDTH-1:0] ready_count,
    input logic [BANK_COUNT_WIDTH-1:0] group_tiles
);
    always @(posedge clk) begin
        if (rst_n && coalesce_enable) begin
            if (ram_read_en) begin
                assert (bank_ready[read_bank])
                    else $fatal(1, "Coalesced output read an unpublished FIFO bank");
                if (!transpose_mode)
                    assert (COUNT_WIDTH'(logical_row[3:0]) < bank_count[read_bank])
                        else $fatal(1, "Coalesced output read beyond the populated FIFO rows");
            end
            if (finish)
                assert (group_tiles <= ready_count)
                    else $fatal(1, "Coalesced output released more banks than were populated");
        end
    end
endmodule

bind vec_s8_to_fifo_full ws_output_fifo_checks #(
    .BANKS(BANKS), .BANK_WIDTH(BANK_WIDTH), .COUNT_WIDTH(COUNT_WIDTH),
    .BANK_COUNT_WIDTH(BANK_COUNT_WIDTH)
) u_ws_output_fifo_checks (
    .clk(clk), .rst_n(rst_n), .coalesce_enable(coalesce_enable),
    .transpose_mode(transpose_mode_eff), .ram_read_en(ram_read_en),
    .read_bank(co_issue_bank), .logical_row(co_next_row),
    .bank_ready(bank_ready), .bank_count(bank_count),
    .finish(co_finish), .ready_count(ready_bank_count_q), .group_tiles(co_tiles)
);
