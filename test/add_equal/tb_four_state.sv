// SPDX-License-Identifier: Apache-2.0
`timescale 1ns / 1ps
`default_nettype none

module tb_add_equal_four_state #(
    parameter int unsigned p_width = 32
);
    logic [p_width-1:0] i_a, i_b, i_target;
    logic i_carry_in;
    wire logic candidate_equal, preserved_equal;
    logic [p_width-1:0] carry_needed, carry_generated, carry_expected;
    logic unused_final_carry, reference_equal;
    logic [3*p_width:0] stimulus;
    integer tests;
    integer seed;
    integer unused_random;

    add_equal #(.p_width(p_width)) u_default (
        .i_a(i_a), .i_b(i_b), .i_target(i_target),
        .i_carry_in(i_carry_in), .o_equal(candidate_equal)
    );
    add_equal #(.p_width(p_width), .p_preserve_bits(1'b1)) u_preserved (
        .i_a(i_a), .i_b(i_b), .i_target(i_target),
        .i_carry_in(i_carry_in), .o_equal(preserved_equal)
    );

    // 向量逻辑相等保留已知不匹配位及未知位共同出现时的四态语义。
    assign carry_needed = i_a ^ i_b ^ i_target;
    assign carry_generated = (i_a & i_b) | ((i_a | i_b) & ~i_target);
    assign {unused_final_carry, carry_expected} = {carry_generated, i_carry_in};
    assign reference_equal = carry_needed == carry_expected;

    task automatic check_result;
        #1;
        if (candidate_equal !== reference_equal)
            $fatal(1, "ADD_EQUAL_FOUR_STATE_MISMATCH width=%0d a=%b b=%b target=%b carry=%b actual=%b expected=%b",
                p_width, i_a, i_b, i_target, i_carry_in, candidate_equal, reference_equal);
        if (preserved_equal !== reference_equal)
            $fatal(1, "ADD_EQUAL_PRESERVED_MISMATCH width=%0d", p_width);
        tests++;
    endtask

    initial begin
        tests = 0;
        seed = 32'h2741_6ab3;
        unused_random = $urandom(seed);
        if (p_width <= 2) begin
            // 一位和两位组合穷举全部 0、1、X、Z 输入。
            for (int pattern = 0; pattern < (1 << (2*(3*p_width+1))); pattern++) begin
                for (int bit_index = 0; bit_index < 3*p_width+1; bit_index++) begin
                    case ((pattern >> (2*bit_index)) & 3)
                        0: stimulus[bit_index] = 1'b0;
                        1: stimulus[bit_index] = 1'b1;
                        2: stimulus[bit_index] = 1'bx;
                        3: stimulus[bit_index] = 1'bz;
                    endcase
                end
                {i_a, i_b, i_target, i_carry_in} = stimulus;
                check_result();
            end
        end else begin
            // 宽输入同时覆盖精确相等、已知不相等及少量未知位影响多个比较条件的情况。
            for (int sample = 0; sample < 6000; sample++) begin
                for (int bit_index = 0; bit_index < 3*p_width+1; bit_index++)
                    stimulus[bit_index] = 1'($urandom());
                {i_a, i_b, i_target, i_carry_in} = stimulus;
                if (sample % 3 != 0) i_target = i_a + i_b + p_width'(i_carry_in);
                if (sample % 3 == 2) i_target[sample % p_width] = ~i_target[sample % p_width];
                stimulus = {i_a, i_b, i_target, i_carry_in};
                for (int unknown_index = 0; unknown_index < sample % 5; unknown_index++)
                    stimulus[$urandom_range(3*p_width, 0)] = unknown_index[0] ? 1'bx : 1'bz;
                {i_a, i_b, i_target, i_carry_in} = stimulus;
                check_result();
            end
        end
        $display("ADD_EQUAL_FOUR_STATE_PASS width=%0d tests=%0d", p_width, tests);
        $finish;
    end
endmodule

`default_nettype wire
