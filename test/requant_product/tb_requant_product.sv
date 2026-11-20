`timescale 1ns/1ps
module tb_requant_product;
    logic clk = 0;
    logic i_en;
    logic signed [31:0] i_a, i_b;
    logic signed [63:0] reference_product, generic_product, dsp_product;
    logic signed [63:0] pending_product, expected_product;
    logic signed [31:0] captured_a, captured_b;
    logic signed [63:0] registered_reference, registered_generic, registered_dsp;
    logic signed [63:0] expected_registered_product;
    bit pending_valid = 0;
    bit output_valid = 0;
    bit registered_output_valid = 0;
    int checks = 0;
    int enabled_edges = 0;
    int held_edges = 0;
    int registered_checks = 0;
    logic signed [31:0] directed [0:13];

    quant_product_reference u_reference (
        .clk(clk), .i_en(i_en), .i_a(i_a), .i_b(i_b), .o_product(reference_product)
    );
    registered_multiplier_s32 #(.p_use_dsp(1'b0)) u_generic (
        .clk(clk), .i_en(i_en), .i_a(i_a), .i_b(i_b), .o_product(generic_product)
    );
    registered_multiplier_s32 #(.p_use_dsp(1'b1)) u_dsp (
        .clk(clk), .i_en(i_en), .i_a(i_a), .i_b(i_b), .o_product(dsp_product)
    );
    always_ff @(posedge clk) begin
        if (i_en) begin
            captured_a <= i_a;
            captured_b <= i_b;
        end
    end
    quant_product_reference u_registered_reference (
        .clk(clk), .i_en(i_en), .i_a(captured_a), .i_b(captured_b), .o_product(registered_reference)
    );
    registered_multiplier_s32 #(.p_use_dsp(1'b0), .p_input_register(1'b1)) u_registered_generic (
        .clk(clk), .i_en(i_en), .i_a(i_a), .i_b(i_b), .o_product(registered_generic)
    );
    registered_multiplier_s32 #(.p_use_dsp(1'b1), .p_input_register(1'b1)) u_registered_dsp (
        .clk(clk), .i_en(i_en), .i_a(i_a), .i_b(i_b), .o_product(registered_dsp)
    );

    task automatic sample(input logic enable, input logic signed [31:0] value_a, value_b);
        logic signed [63:0] extended_a, extended_b;
        i_en = enable;
        i_a = value_a;
        i_b = value_b;
        extended_a = {{32{value_a[31]}}, value_a};
        extended_b = {{32{value_b[31]}}, value_b};
        if (enable) begin
            expected_registered_product = expected_product;
            registered_output_valid = output_valid;
            expected_product = pending_product;
            output_valid = pending_valid;
            pending_product = extended_a * extended_b;
            pending_valid = 1;
            enabled_edges++;
        end else begin
            held_edges++;
        end
        clk = 0;
        #1;
        clk = 1;
        #1;
        if (output_valid) begin
            if (reference_product !== expected_product || generic_product !== expected_product ||
                dsp_product !== expected_product) begin
                $fatal(1, "乘积不一致 cycle=%0d enable=%0d expected=%h reference=%h generic=%h dsp=%h",
                       checks, enable, expected_product, reference_product, generic_product, dsp_product);
            end
            if (dsp_product[15:0] !== expected_product[15:0] ||
                dsp_product[63:16] !== expected_product[63:16]) begin
                $fatal(1, "乘积高四十八位和低十六位的采样周期不一致");
            end
            checks++;
        end
        if (registered_output_valid) begin
            if (registered_reference !== expected_registered_product ||
                registered_generic !== expected_registered_product || registered_dsp !== expected_registered_product) begin
                $fatal(1, "输入寄存乘积不一致 cycle=%0d expected=%h reference=%h generic=%h dsp=%h",
                       checks, expected_registered_product, registered_reference, registered_generic, registered_dsp);
            end
            registered_checks++;
        end
        clk = 0;
        #1;
    endtask

    initial begin
        int seed;
        seed = 32'h7915c4a3;
        seed = $urandom(seed);
        directed = '{32'sh80000000, 32'sh7fffffff, -32'sd1, 32'sd0, 32'sd1,
                     32'sh0000ffff, 32'shffff0000, 32'sh00010000, 32'sh8000ffff,
                     32'sh7fff0001, 32'sh5555aaaa, 32'shaaaa5555, 32'sh00008000, 32'shffff8000};
        repeat (11) sample(0, 32'($urandom), 32'($urandom));
        for (int lhs = 0; lhs < 14; lhs++) begin
            for (int rhs = 0; rhs < 14; rhs++) begin
                sample(1, directed[lhs], directed[rhs]);
                sample(0, ~directed[lhs], ~directed[rhs]);
            end
        end
        for (int bit_index = 0; bit_index < 32; bit_index++) begin
            for (int other_bit = 0; other_bit < 32; other_bit++) begin
                sample(1, 32'd1 << bit_index, 32'd1 << other_bit);
                sample(0, ~(32'd1 << bit_index), 32'd1 << other_bit);
                sample(1, 32'd1 << bit_index, ~(32'd1 << other_bit));
            end
        end
        for (int low_half = 0; low_half < 65536; low_half++) begin
            sample(1, {16'h7fff, 16'(low_half)}, 32'sh8000ffff);
            sample(1, {16'h8000, 16'(low_half)}, 32'sh7fffffff);
            sample(0, 32'($urandom), 32'($urandom));
        end
        for (int cycle = 0; cycle < 1000000; cycle++) begin
            sample((cycle % 97 < 81) && ($urandom_range(0, 7) != 0), 32'($urandom), 32'($urandom));
        end
        sample(1, 0, 0);
        sample(1, 0, 0);
        $display("REQUANT_PRODUCT_PASS checks=%0d registered_checks=%0d enabled_edges=%0d held_edges=%0d latency_enabled_edges=2 registered_latency_enabled_edges=3",
                 checks, registered_checks, enabled_edges, held_edges);
        $finish;
    end
endmodule
