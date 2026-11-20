`timescale 1ns/1ps
module tb_vector_scalar;
    logic clk=0;
    logic signed [31:0] a, b;
    logic signed [63:0] reference_product, candidate_product, generic_product;
    logic signed [63:0] expected_previous;
    bit expected_valid=0;
    int checks=0;
    logic signed [31:0] directed [0:13];
    vector_scalar_multiplier_reference u_reference (.clk(clk), .a(a), .b(b), .product(reference_product));
    vector_scalar_multiplier #(.p_use_dsp(1'b1)) u_candidate (.clk(clk), .a(a), .b(b), .product(candidate_product));

    vector_scalar_multiplier #(.p_use_dsp(1'b0)) u_generic (.clk(clk), .a(a), .b(b), .product(generic_product));

    task automatic sample(input logic signed [31:0] value_a, value_b);
        logic signed [63:0] extended_a, extended_b;
        a=value_a;
        b=value_b;
        extended_a={{32{a[31]}},a};
        extended_b={{32{b[31]}},b};
        clk=0;
        #1;
        clk=1;
        #1;
        if (expected_valid) begin
            if (reference_product !== expected_previous)
                $fatal(1,"reference result cycle=%0d actual=%h expected=%h",checks,reference_product,expected_previous);
            if (generic_product !== expected_previous)
                $fatal(1,"generic result cycle=%0d actual=%h expected=%h",checks,generic_product,expected_previous);
            if (candidate_product !== expected_previous)
                $fatal(1,"candidate result cycle=%0d actual=%h expected=%h",checks,candidate_product,expected_previous);
            if (candidate_product[15:0] !== expected_previous[15:0] ||
                candidate_product[63:16] !== expected_previous[63:16])
                $fatal(1,"product segments use different input cycles");
            checks++;
        end
        expected_previous=extended_a*extended_b;
        expected_valid=1;
        clk=0;
        #1;
    endtask

    initial begin
        int seed;
        seed=32'h25d17a9c;
        seed=$urandom(seed);
        directed='{32'sh80000000,32'sh7fffffff,-32'sd1,32'sd0,32'sd1,
                   32'sh0000ffff,32'shffff0000,32'sh00010000,32'sh8000ffff,
                   32'sh7fff0001,32'sh5555aaaa,32'shaaaa5555,32'sh00008000,32'shffff8000};
        for (int lhs=0;lhs<14;lhs++)
            for (int rhs=0;rhs<14;rhs++) sample(directed[lhs],directed[rhs]);
        for (int bit_index=0;bit_index<32;bit_index++) begin
            for (int other_bit=0;other_bit<32;other_bit++) begin
                sample(32'd1<<bit_index,32'd1<<other_bit);
                sample(~(32'd1<<bit_index),32'd1<<other_bit);
                sample(32'd1<<bit_index,~(32'd1<<other_bit));
            end
        end
        for (int low_half=0;low_half<65536;low_half++) begin
            sample({16'h7fff,16'(low_half)},32'sh8000ffff);
            sample({16'h8000,16'(low_half)},32'sh7fffffff);
        end
        for (int cycle=0;cycle<1000000;cycle++) sample(32'($urandom),32'($urandom));
        sample(0,0);
        $display("VECTOR_SCALAR_PASS checks=%0d latency_edges=2 initiation_interval=1",checks);
        $finish;
    end
endmodule
