module tb;
    logic [31:0] operand_a, operand_b, negated, next_address;
    logic unsigned_less, signed_less, compressed;
    logic [32:0] unsigned_difference, signed_difference;
    logic [31:0] random_state = 32'h731b286d;
    integer checks = 0;

    pico_operand_comparison u_compare (
        .i_a(operand_a), .i_b(operand_b),
        .o_unsigned_less(unsigned_less), .o_signed_less(signed_less)
    );
    pico_result_negation u_negation (.i_value(operand_a), .o_value(negated));
    pico_sequential_address u_sequential (
        .i_address(operand_a), .i_compressed(compressed), .o_address(next_address)
    );
    assign unsigned_difference = {1'b0, operand_a} - {1'b0, operand_b};
    assign signed_difference = {1'b0, ~operand_a[31], operand_a[30:0]} -
        {1'b0, ~operand_b[31], operand_b[30:0]};

    function automatic [31:0] next_random;
        random_state = random_state ^ (random_state << 13);
        random_state = random_state ^ (random_state >> 17);
        random_state = random_state ^ (random_state << 5);
        return random_state;
    endfunction

    function automatic four_value(input [1:0] value);
        case (value)
            0: return 1'b0;
            1: return 1'b1;
            2: return 1'bx;
            3: return 1'bz;
        endcase
    endfunction

    task automatic check_outputs;
        #1;
        if (unsigned_less !== unsigned_difference[32] ||
            signed_less !== signed_difference[32] ||
            negated !== (32'd0-operand_a) ||
            next_address !== (operand_a+(compressed ? 32'd2 : 32'd4))) begin
            $fatal(1, "CPU arithmetic mismatch a=%h b=%h compressed=%b",
                operand_a, operand_b, compressed);
        end
        checks++;
    endtask

    initial begin
        // 已知输入和未知输入使用相同的定宽算术参考。
        for (integer sample_index = 0; sample_index < 65536; sample_index++) begin
            operand_a = next_random();
            operand_b = next_random();
            compressed = four_value(2'(sample_index));
            check_outputs();
            for (integer bit_index = 0; bit_index < 32; bit_index++) begin
                operand_a[bit_index] = four_value(2'(next_random()));
                operand_b[bit_index] = four_value(2'(next_random()));
            end
            check_outputs();
        end
        // 单个位的未知值覆盖所有字节和最高符号位。
        for (integer bit_index = 0; bit_index < 32; bit_index++) begin
            operand_a = 32'hffffffff;
            operand_b = 32'h00000000;
            operand_a[bit_index] = 1'bx;
            check_outputs();
            operand_a[bit_index] = 1'bz;
            check_outputs();
            operand_a = 32'h00000000;
            operand_b = 32'hffffffff;
            operand_b[bit_index] = 1'bx;
            check_outputs();
            operand_b[bit_index] = 1'bz;
            check_outputs();
        end
        $display("PASS checks=%0d", checks);
        $finish;
    end
endmodule
