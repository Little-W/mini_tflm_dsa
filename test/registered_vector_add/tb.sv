`timescale 1ns/1ps
`default_nettype none

module tb_registered_vector_add;
    localparam int LANES = 16;
    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic clear = 1'b0;
    logic valid = 1'b0;
    logic tail = 1'b0;
    logic signed [31:0] lhs [LANES];
    logic signed [31:0] rhs [LANES];
    wire logic output_valid;
    wire logic output_tail;
    wire logic signed [31:0] sum [LANES];
    logic [31:0] expected [LANES];
    logic [31:0] held [LANES];
    bit have_data = 1'b0;
    integer cycles = 0;
    integer comparisons = 0;
    integer clears = 0;
    integer invalid_cycles = 0;
    integer seed = 20261123;
    logic [31:0] boundary [12];

    registered_vector_add #(.p_lanes(LANES)) u_dut (
        .clk(clk), .rst_n(rst_n), .i_clear(clear), .i_valid(valid),
        .i_tile_done(tail), .i_lhs(lhs), .i_rhs(rhs),
        .o_valid(output_valid), .o_tile_done(output_tail), .o_sum(sum)
    );

    // 参考运算直接执行 INT32 加法，同时检查有效信号、清空和保持行为。
    task automatic step;
        bit accepted;
        begin
            accepted = rst_n && valid && !clear;
            for (int lane = 0; lane < LANES; lane++) begin
                expected[lane] = lhs[lane] + rhs[lane];
                held[lane] = sum[lane];
            end
            #1;
            if (clear && output_valid !== 1'b0) $fatal(1, "Clear must suppress output");
            clk = 1'b1;
            #1;
            if (output_valid !== accepted) $fatal(1, "Valid mismatch at cycle %0d", cycles);
            if (output_tail !== (accepted && tail)) $fatal(1, "Tail mismatch at cycle %0d", cycles);
            if (accepted) begin
                for (int lane = 0; lane < LANES; lane++) begin
                    if (sum[lane] !== expected[lane])
                        $fatal(1, "Sum mismatch cycle=%0d lane=%0d lhs=%h rhs=%h actual=%h expected=%h",
                               cycles, lane, lhs[lane], rhs[lane], sum[lane], expected[lane]);
                    comparisons++;
                end
                have_data = 1'b1;
            end else if (have_data && (!valid || clear)) begin
                for (int lane = 0; lane < LANES; lane++) begin
                    if (sum[lane] !== held[lane]) $fatal(1, "Data changed without an accepted input");
                    comparisons++;
                end
            end
            clears += rst_n && clear;
            invalid_cycles += rst_n && !valid;
            cycles++;
            clk = 1'b0;
            #1;
        end
    endtask

    initial begin
        boundary[0] = 32'h00000000;
        boundary[1] = 32'h00000001;
        boundary[2] = 32'h000000ff;
        boundary[3] = 32'h0000ffff;
        boundary[4] = 32'h00ffffff;
        boundary[5] = 32'hffffffff;
        boundary[6] = 32'h7fffffff;
        boundary[7] = 32'h80000000;
        boundary[8] = 32'hff00ff00;
        boundary[9] = 32'h00ff00ff;
        boundary[10] = 32'hfefefefe;
        boundary[11] = 32'h01010101;
        for (int lane = 0; lane < LANES; lane++) begin
            lhs[lane] = '0;
            rhs[lane] = '0;
        end
        step();
        rst_n = 1'b1;
        valid = 1'b1;
        for (int a = 0; a < 12; a++) begin
            for (int b = 0; b < 12; b++) begin
                for (int lane = 0; lane < LANES; lane++) begin
                    lhs[lane] = boundary[(a + lane) % 12];
                    rhs[lane] = boundary[(b + 3 * lane) % 12];
                end
                tail = (b == 11);
                step();
            end
        end
        for (int index = 0; index < 50000; index++) begin
            rst_n = (index % 2053 != 0);
            valid = (index % 7 != 0);
            clear = (index % 173 == 0);
            tail = (index % 19 == 0);
            for (int lane = 0; lane < LANES; lane++) begin
                lhs[lane] = $urandom(seed);
                rhs[lane] = $urandom(seed);
            end
            step();
        end
        valid = 1'b0;
        clear = 1'b0;
        rst_n = 1'b1;
        tail = 1'b1;
        step();
        clear = 1'b1;
        step();
        $display("VECTOR_ADD_PASS cycles=%0d comparisons=%0d clears=%0d invalid_cycles=%0d",
                 cycles, comparisons, clears, invalid_cycles);
        $finish;
    end
endmodule

`default_nettype wire
