`default_nettype none

module tb_count_boundary #(
    parameter int p_width = 32
);
    logic [p_width-1:0] value, limit;
    logic actual;
    wire expected = (value + p_width'(1)) >= limit;
    int checks = 0;

    kernel_count_next_reaches #(.p_width(p_width)) u_dut (
        .i_value(value), .i_limit(limit), .o_reaches(actual)
    );

    task automatic compare;
        #1;
        if (actual !== expected)
            $fatal(1, "Count boundary differs width=%0d value=%h limit=%h actual=%b expected=%b",
                   p_width, value, limit, actual, expected);
        checks++;
    endtask

    initial begin
        // 随机二值覆盖以及相邻上限、最大值回绕与零上限。
        for (int trial = 0; trial < 2048; trial++) begin
            value = p_width'({$urandom, $urandom, $urandom});
            limit = p_width'({$urandom, $urandom, $urandom});
            compare();
            limit = value + p_width'(1);
            compare();
        end
        for (int pattern = 0; pattern < 4; pattern++) begin
            value = {p_width{pattern[0]}};
            limit = {p_width{pattern[1]}};
            compare();
            // 每个操作数的每一位分别检查未知值和高阻值。
            for (int bit_index = 0; bit_index < p_width; bit_index++) begin
                value[bit_index] = 1'bx; compare();
                value[bit_index] = 1'bz; compare();
                value[bit_index] = pattern[0];
                limit[bit_index] = 1'bx; compare();
                limit[bit_index] = 1'bz; compare();
                limit[bit_index] = pattern[1];
            end
        end
        $display("COUNT_BOUNDARY_PASS width=%0d checks=%0d", p_width, checks);
        $finish;
    end
endmodule

`default_nettype wire
