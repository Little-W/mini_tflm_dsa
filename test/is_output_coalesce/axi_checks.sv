// SPDX-License-Identifier: Apache-2.0
module is_output_coalesce_axi_checks (
    input logic clk,
    input logic rst_n,
    input logic awvalid,
    input logic awready,
    input logic [31:0] awaddr,
    input logic [7:0] awlen,
    input logic [2:0] awsize,
    input logic coalesce_enable,
    input logic [31:0] cols,
    input logic [31:0] reuse,
    input logic [31:0] dst_base,
    input logic [31:0] dst_stride
);
    wire [31:0] group_bytes = reuse << 4;
    wire expected_coalesce = reuse >= 2 && reuse <= 16 &&
        (reuse & (reuse - 1)) == 0 && (cols & (group_bytes - 1)) == 0 &&
        (dst_base & (group_bytes - 1)) == 0 &&
        (dst_stride & (group_bytes - 1)) == 0;
    always @(posedge clk) begin
        if (rst_n && awvalid && awready) begin
            assert ((awaddr & 4095) + ((32'(awlen) + 1) << awsize) <= 4096)
                else $fatal(1, "AXI write burst crossed a 4 KiB page");
            assert (coalesce_enable == expected_coalesce)
                else $fatal(1, "IS output grouping configuration differs");
            if (expected_coalesce) begin
                assert (((32'(awlen) + 1) << awsize) == group_bytes)
                    else $fatal(1, "IS output burst length differs");
                assert ((awaddr & (group_bytes - 1)) == 0)
                    else $fatal(1, "IS output burst address differs");
            end
        end
    end
endmodule

bind tb_matrix_layout is_output_coalesce_axi_checks u_is_output_coalesce_axi_checks (
    .clk(clk), .rst_n(rst_n), .awvalid(awvalid), .awready(awready),
    .awaddr(awaddr), .awlen(awlen), .awsize(awsize),
    .coalesce_enable(u_dut.u_npu_top.oa_row_coalesce),
    .cols(cfg[5]), .reuse(cfg[6]), .dst_base(cfg[17]), .dst_stride(cfg[20])
);
