`timescale 1ns/1ps
module tb_bounded_dsp_chain;
    logic clk = 1'b0;
    logic [31:0] a = 32'd0, b = 32'd0, c = 32'd0, d = 32'd0;
    wire [31:0] actual, expected;
    integer seed = 178913;
    integer comparisons = 0;

    bounded_dsp_chain u_mapped (
        .clk(clk), .i_a(a), .i_b(b), .i_c(c), .i_d(d), .o_y(actual)
    );
    bounded_reference u_reference (
        .clk(clk), .i_a(a), .i_b(b), .i_c(c), .i_d(d), .o_y(expected)
    );
    always #5 clk = ~clk;

    initial begin
        repeat (2) @(negedge clk);
        for (integer index = 0; index < 40004; index = index + 1) begin
            // 边界数值和随机完整三十二位输入均逐周期比较。
            if (index < 4) begin
                a = 32'hffffffff >> index;
                b = 32'h80000000 + index;
                c = 32'h7fffffff - index;
                d = 32'hffffffff - index;
            end else begin
                a = $random(seed); b = $random(seed);
                c = $random(seed); d = $random(seed);
            end
            @(negedge clk);
            if (actual !== expected) $fatal(1, "Arithmetic output mismatch at cycle %0d", index);
            comparisons = comparisons + 1;
        end
        $display("BOUNDED_DSP_CHAIN_PASS comparisons=%0d", comparisons);
        $finish;
    end
endmodule
