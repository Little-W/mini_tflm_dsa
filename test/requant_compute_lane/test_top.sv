`default_nettype none

// 同步参数存储在接收数据后提供参数，两个配置使用相同的七拍数值检查。
module requant_compute_lane_test #(
    parameter bit p_delayed_parameters = 1'b0
) (
    input wire logic clk, rst_n, i_en, i_clear, i_valid, i_lane_enable,
    input wire logic signed [31:0] i_value, i_multiplier,
    input wire logic [6:0] i_amount,
    input wire logic i_s16,
    input wire logic signed [31:0] i_dst_offset, i_activation_min, i_activation_max,
    output wire logic o_valid,
    output wire logic signed [7:0] o_s8,
    output wire logic signed [15:0] o_s16
);
    logic signed [31:0] multiplier;
    logic [6:0] amount;

    if (p_delayed_parameters) begin : g_synchronous_parameters
        always_ff @(posedge clk) begin
            if (rst_n && i_en && !i_clear) begin
                multiplier <= i_multiplier;
                amount <= i_amount;
            end
        end
    end else begin : g_direct_parameters
        assign multiplier = i_multiplier;
        assign amount = i_amount;
    end

`ifdef REQUANT_MAPPED
    requant_compute_lane u_lane (
`else
    requant_compute_lane #(.p_delayed_parameters(p_delayed_parameters)) u_lane (
`endif
        .clk(clk), .rst_n(rst_n), .i_en(i_en), .i_clear(i_clear),
        .i_valid(i_valid), .i_lane_enable(i_lane_enable), .i_value(i_value),
        .i_multiplier(multiplier), .i_amount(amount), .i_s16(i_s16),
        .i_dst_offset(i_dst_offset), .i_activation_min(i_activation_min),
        .i_activation_max(i_activation_max), .o_valid(o_valid), .o_s8(o_s8), .o_s16(o_s16)
    );
endmodule

`default_nettype wire
