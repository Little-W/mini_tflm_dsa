// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 各组分别计算两种借位输入的差值，再选择实际借位对应的结果。
module borrow_select_subtract #(
    parameter int unsigned p_width = 5,
    parameter int unsigned p_group_width = 3
) (
    input  wire logic [p_width-1:0] i_a,
    input  wire logic [p_width-1:0] i_b,
    output logic [p_width:0] o_difference
);
    localparam int unsigned p_groups = (p_width+p_group_width-1)/p_group_width;
    logic [p_groups:0] borrow;
    (* keep = 1 *) logic [p_width-1:0] difference_zero, difference_one;
    (* keep = 1 *) logic [p_groups-1:0] borrow_zero_out, borrow_one_out;
    logic [p_width:0] difference_value;

    assign borrow[0] = 1'b0;
    for (genvar group_index = 0; group_index < p_groups; group_index++) begin : g_group
        localparam int unsigned p_first = group_index*p_group_width;
        localparam int unsigned p_bits = p_width-p_first < p_group_width ? p_width-p_first : p_group_width;
        logic [p_bits:0] borrow_zero, borrow_one;
        assign borrow_zero[0] = 1'b0;
        assign borrow_one[0] = 1'b1;
        for (genvar bit_index = 0; bit_index < p_bits; bit_index++) begin : g_bit
            logic equal_bit, generate_borrow;
            assign equal_bit = ~(i_a[p_first+bit_index] ^ i_b[p_first+bit_index]);
            assign generate_borrow = ~i_a[p_first+bit_index] & i_b[p_first+bit_index];
            assign borrow_zero[bit_index+1] = generate_borrow | (equal_bit & borrow_zero[bit_index]);
            assign borrow_one[bit_index+1] = generate_borrow | (equal_bit & borrow_one[bit_index]);
            assign difference_zero[p_first+bit_index] =
                i_a[p_first+bit_index] ^ i_b[p_first+bit_index] ^ borrow_zero[bit_index];
            assign difference_one[p_first+bit_index] =
                i_a[p_first+bit_index] ^ i_b[p_first+bit_index] ^ borrow_one[bit_index];
        end
        assign borrow_zero_out[group_index] = borrow_zero[p_bits];
        assign borrow_one_out[group_index] = borrow_one[p_bits];
        assign borrow[group_index+1] = borrow[group_index] ? borrow_one_out[group_index] : borrow_zero_out[group_index];
        assign difference_value[p_first+:p_bits] = borrow[group_index] ?
            difference_one[p_first+:p_bits] : difference_zero[p_first+:p_bits];
    end
    assign difference_value[p_width] = borrow[p_groups];
    // 未知输入保持 SystemVerilog 定宽减法的四态传播规则。
    always_comb begin
        case (^{i_a, i_b})
            1'b0, 1'b1: o_difference = difference_value;
            default: o_difference = 'x;
        endcase
    end
endmodule

`default_nettype wire
