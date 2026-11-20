// SPDX-License-Identifier: Apache-2.0
`timescale 1ns/1ps
module tb_four_state;
    logic [39:0] A, B;
    logic [3:0] CI;
    logic BI;
    wire [39:0] actual_x, actual_y, actual_co;
    wire [39:0] reference_x, reference_y, reference_co;
    logic [39:0] saved_a, saved_b;
    logic [3:0] saved_ci;
    logic saved_bi;
    integer defined_cases, unknown_cases, seed;
    integer pattern, bit_index, kind, lane, value;

    fpga_dsp_alu4 u_actual (.A(A), .B(B), .CI(CI), .BI(BI),
        .X(actual_x), .Y(actual_y), .CO(actual_co));
    for (genvar part = 0; part < 4; part++) begin : g_reference
        reference_alu #(.A_WIDTH(10), .B_WIDTH(10), .Y_WIDTH(10)) u_reference (
            .A(A[10*part +: 10]), .B(B[10*part +: 10]), .CI(CI[part]), .BI(BI),
            .X(reference_x[10*part +: 10]), .Y(reference_y[10*part +: 10]),
            .CO(reference_co[10*part +: 10]));
    end

    // 四态比较同时核对每一通道；其他通道保持已知输入时应保持独立结果。
    task automatic check_outputs(input bit has_unknown);
        begin
            #1;
            if (actual_x !== reference_x || actual_y !== reference_y || actual_co !== reference_co)
                $fatal(1, "四通道结果不同 A=%h B=%h CI=%h BI=%b X=%h/%h Y=%h/%h CO=%h/%h",
                    A, B, CI, BI, actual_x, reference_x, actual_y, reference_y, actual_co, reference_co);
            if (has_unknown) unknown_cases++;
            else defined_cases++;
        end
    endtask

    initial begin
        defined_cases = 0;
        unknown_cases = 0;
        seed = 32'h4a3b_29d1;
        // 遍历所有进位组合及加减模式，并覆盖各位的进位、借位和相邻通道边界。
        for (value = 0; value < 1024; value++) begin
            for (kind = 0; kind < 2; kind++) begin
                for (pattern = 0; pattern < 16; pattern++) begin
                    A = {10'(value), 10'(~value), 10'd1023, 10'd0};
                    B = {10'd1, 10'(value), 10'(value), 10'(value)};
                    CI = 4'(pattern);
                    BI = 1'(kind);
                    check_outputs(1'b0);
                end
            end
        end
        for (pattern = 0; pattern < 20000; pattern++) begin
            A = {$random(seed), $random(seed)};
            B = {$random(seed), $random(seed)};
            CI = $random(seed);
            BI = $random(seed);
            check_outputs(1'b0);
        end
        // 每个输入位分别注入 X 和 Z，覆盖四个进位与公共加减模式。
        for (pattern = 0; pattern < 32; pattern++) begin
            saved_a = {$random(seed), $random(seed)};
            saved_b = {$random(seed), $random(seed)};
            saved_ci = $random(seed);
            saved_bi = $random(seed);
            for (bit_index = 0; bit_index < 85; bit_index++) begin
                for (kind = 0; kind < 2; kind++) begin
                    A = saved_a; B = saved_b; CI = saved_ci; BI = saved_bi;
                    if (bit_index < 40) A[bit_index] = kind ? 1'bz : 1'bx;
                    else if (bit_index < 80) B[bit_index-40] = kind ? 1'bz : 1'bx;
                    else if (bit_index < 84) CI[bit_index-80] = kind ? 1'bz : 1'bx;
                    else BI = kind ? 1'bz : 1'bx;
                    check_outputs(1'b1);
                end
            end
            // 整个通道的未知操作数不得影响其余三个通道。
            for (lane = 0; lane < 4; lane++) begin
                for (kind = 0; kind < 2; kind++) begin
                    A = saved_a; B = saved_b; CI = saved_ci; BI = saved_bi;
                    A[10*lane +: 10] = kind ? 'z : 'x;
                    B[10*lane +: 10] = kind ? 'z : 'x;
                    CI[lane] = kind ? 1'bz : 1'bx;
                    check_outputs(1'b1);
                end
            end
        end
        $display("{\"passed\":true,\"defined_cases\":%0d,\"four_state_cases\":%0d,\"checked_output_bits\":120}",
            defined_cases, unknown_cases);
        $finish;
    end
endmodule
