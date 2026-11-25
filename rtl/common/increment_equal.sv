// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 相邻两位的比较只依赖本组及前一位，六个输入可独立计算。
module increment_equal_pair #(
    parameter bit p_first = 1'b0,
    parameter int unsigned p_count = 2
) (
    input  wire logic [2:0] i_a,
    input  wire logic [2:0] i_target,
    output logic o_equal
);
    logic first_equal, second_equal;
    assign first_equal = p_first ? i_a[1] ^ i_target[1] :
        ~((i_a[1] ^ i_target[1]) ^ (i_a[0] & ~i_target[0]));
    assign second_equal = ~((i_a[2] ^ i_target[2]) ^ (i_a[1] & ~i_target[1]));
    assign o_equal = first_equal && (p_count == 1 || second_equal);
endmodule

// 比较加一后的定宽结果，每组独立核对两位相邻的进位关系。
module increment_equal #(
    parameter int unsigned p_width = 16
) (
    input  wire logic [p_width-1:0] i_a,
    input  wire logic [p_width-1:0] i_target,
    output logic o_equal
);
    localparam int unsigned p_pairs = (p_width+1)/2;
    logic [p_pairs-1:0] pair_equal;
    for (genvar pair = 0; pair < p_pairs; pair++) begin : g_pair
        localparam int unsigned p_count = p_width-2*pair < 2 ? 1 : 2;
        logic [2:0] a_pair, target_pair;
        for (genvar item = 0; item < 3; item++) begin : g_item
            localparam int p_bit = 2*pair+item-1;
            if (p_bit >= 0 && p_bit < p_width) begin : g_present
                assign a_pair[item] = i_a[p_bit];
                assign target_pair[item] = i_target[p_bit];
            end else begin : g_unused
                assign a_pair[item] = 1'b0;
                assign target_pair[item] = 1'b0;
            end
        end
        increment_equal_pair #(.p_first(pair == 0), .p_count(p_count)) u_pair (
            .i_a(a_pair), .i_target(target_pair), .o_equal(pair_equal[pair])
        );
    end
    assign o_equal = &pair_equal;
endmodule

`default_nettype wire
