`timescale 1ns/1ps
module tb_weight_mux;
    logic clk = 0, commit_weight = 0, store_weight_req = 0;
    logic signed [15:0] weight_in = 'x, data_in = 'x;
    logic signed [31:0] sum_in = 'x;
    wire signed [15:0] r_data, c_data, r_weight, c_weight;
    wire signed [31:0] r_sum, c_sum;

    ws_systolic_cell_reference #(.DATA_IN_WIDTH(16), .WEIGHT_WIDTH(16), .ACC_WIDTH(32)) r (
        .clk(clk), .commit_weight(commit_weight), .store_weight_req(store_weight_req),
        .weight_in(weight_in), .data_in(data_in), .sum_in(sum_in),
        .data_out(r_data), .weight_out(r_weight), .sum_out(r_sum)
    );
    ws_systolic_cell #(.DATA_IN_WIDTH(16), .WEIGHT_WIDTH(16), .ACC_WIDTH(32)) c (
        .clk(clk), .commit_weight(commit_weight), .store_weight_req(store_weight_req),
        .weight_in(weight_in), .data_in(data_in), .sum_in(sum_in),
        .data_out(c_data), .weight_out(c_weight), .sum_out(c_sum)
    );

    task check;
        if ({r_data, r_weight, r_sum, r.weight_active, r.weight_prefetch, r.data_reg, r.sum_reg} !==
            {c_data, c_weight, c_sum, c.weight_active, c.weight_prefetch, c.data_reg, c.sum_reg}) begin
            $fatal(1, "Weight cell differs");
        end
    endtask

    initial begin
        #1; check();
        for (integer cycle = 0; cycle < 100000; cycle = cycle + 1) begin
            commit_weight = $urandom_range(0, 1);
            store_weight_req = $urandom_range(0, 1);
            weight_in = $urandom;
            data_in = $urandom;
            sum_in = $urandom;
            // 覆盖未装载的未知权重，以及数据通路中的未知位传播。
            if (cycle % 11 == 0) weight_in[7:0] = 'x;
            if (cycle % 13 == 0) weight_in[15:8] = 'x;
            if (cycle % 17 == 0) data_in = 'x;
            if (cycle % 19 == 0) sum_in = 'x;
            #1; check(); clk = 1; #1; check(); clk = 0;
        end
        $display("WEIGHT_MUX_FOUR_STATE_PASS cycles=100000 output_checks=200001");
        $finish;
    end
endmodule
