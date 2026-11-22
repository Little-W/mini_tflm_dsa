module accumulator_formal (
    input logic clk,
    input logic rst_n,
    input logic i_clear,
    input logic i_vld,
    input logic [19:0] i_value,
    input logic i_increment
);
    logic [31:0] actual_sum;
    logic [31:0] reference_sum;
    logic [20:0] rounded_value;
    logic [20:0] saved_value;
    logic saved_valid;
    logic started = 1'b0;

    vector_softmax_accumulator u_dut (
        .clk(clk), .rst_n(rst_n), .i_clear(i_clear), .i_vld(i_vld),
        .i_value(i_value), .i_increment(i_increment), .o_sum(actual_sum)
    );

    // 独立定义先求完整二十一位舍入值，再进行模 2^32 的累计。
    assign rounded_value = {1'b0, i_value} + {20'd0, i_increment};
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) saved_valid <= 1'b0;
        else if (i_clear) saved_valid <= 1'b0;
        else saved_valid <= i_vld;
    end
    always_ff @(posedge clk) begin
        saved_value <= rounded_value;
        if (!rst_n || i_clear) reference_sum <= '0;
        else if (saved_valid) reference_sum <= reference_sum + {11'd0, saved_value};
        started <= 1'b1;
        if (started) assert(actual_sum == reference_sum);
    end
endmodule
