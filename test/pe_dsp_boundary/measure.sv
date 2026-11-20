// 完整生产阵列的输出寄存后再测量寄存器间组合路径。
module pe_dsp_boundary_measure (
    input logic clk, rst_n, weight_commit, store_weight_req,
    input logic signed [15:0] weight_in [16], data_in [16],
    input logic signed [31:0] sum_in [16],
    output logic signed [31:0] sum_out [16]
);
    logic signed [31:0] array_sum [16];
    ws_systolic_array #(
        .SIZE(16), .DATA_IN_WIDTH(16), .WEIGHT_WIDTH(16),
        .ACC_WIDTH(32), .p_exchange_weights(1'b0)
    ) u_array (
        .clk(clk), .rst_n(rst_n), .weight_commit(weight_commit),
        .store_weight_req(store_weight_req), .weight_in(weight_in),
        .data_in(data_in), .sum_in(sum_in), .sum_out(array_sum)
    );
    always_ff @(posedge clk) begin
        for (int lane=0; lane<16; lane++) sum_out[lane] <= array_sum[lane];
    end
endmodule
