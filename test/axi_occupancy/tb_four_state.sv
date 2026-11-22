`timescale 1ns/1ps

module occupancy_compare #(
    parameter integer WIDTH = 1
) (
    input logic clk, rst_n, s_valid, m_ready,
    input logic [72:0] data,
    output integer checks = 0
);
    wire r_ready, r_valid, c_ready, c_valid, r_legal, c_legal;
    wire [WIDTH-1:0] r_data, c_data;
    wire [2*WIDTH+3:0] r_state, c_state;
    reference #(.WIDTH(WIDTH)) r (
        .clk, .rst_n, .s_valid, .s_ready(r_ready), .s_data(data[WIDTH-1:0]),
        .m_valid(r_valid), .m_ready, .m_data(r_data),
        .formal_state(r_state), .formal_legal(r_legal)
    );
    current #(.WIDTH(WIDTH)) c (
        .clk, .rst_n, .s_valid, .s_ready(c_ready), .s_data(data[WIDTH-1:0]),
        .m_valid(c_valid), .m_ready, .m_data(c_data),
        .formal_state(c_state), .formal_legal(c_legal)
    );

    // 同时检查无效周期的数据、存储内容、读写位置以及占用编码关系。
    task check;
        if ({r_ready, r_valid, r_data, r_state} !== {c_ready, c_valid, c_data, c_state})
            $fatal(1, "Occupancy mismatch width=%0d check=%0d", WIDTH, checks);
        if (checks > 1 && (!r_legal || !c_legal))
            $fatal(1, "Illegal occupancy width=%0d check=%0d", WIDTH, checks);
        checks = checks + 1;
    endtask
    always @(posedge clk or negedge clk) begin
        #0.1; check();
    end
    initial begin
        #0.1; check();
    end
endmodule

module tb_axi_occupancy;
    logic clk = 0, rst_n = 0, s_valid = 0, m_ready = 0;
    logic [72:0] data = 'x;
    wire integer checks [0:8];
    integer cycles = 100000;
    occupancy_compare #(.WIDTH(1)) w1 (.*,.checks(checks[0]));
    occupancy_compare #(.WIDTH(2)) w2 (.*,.checks(checks[1]));
    occupancy_compare #(.WIDTH(34)) w34 (.*,.checks(checks[2]));
    occupancy_compare #(.WIDTH(35)) w35 (.*,.checks(checks[3]));
    occupancy_compare #(.WIDTH(36)) w36 (.*,.checks(checks[4]));
    occupancy_compare #(.WIDTH(54)) w54 (.*,.checks(checks[5]));
    occupancy_compare #(.WIDTH(64)) w64 (.*,.checks(checks[6]));
    occupancy_compare #(.WIDTH(67)) w67 (.*,.checks(checks[7]));
    occupancy_compare #(.WIDTH(73)) w73 (.*,.checks(checks[8]));

    initial begin
        if ($value$plusargs("cycles=%d", cycles)) begin end
        #1;
        for (integer cycle = 0; cycle < cycles; cycle++) begin
            rst_n = (cycle % 997) != 0;
            s_valid = $urandom_range(0, 1);
            m_ready = $urandom_range(0, 1);
            if (cycle % 64 < 8) begin s_valid = 1; m_ready = 0; end
            if (cycle % 64 >= 8 && cycle % 64 < 16) begin s_valid = 0; m_ready = 1; end
            if (cycle % 64 >= 16 && cycle % 64 < 24) begin s_valid = 1; m_ready = 1; end
            // 四态控制不匹配明确的事件组合时，占用状态维持原值。
            if (cycle % 29 == 0 && cycle != 0) s_valid = 1'bx;
            if (cycle % 31 == 0 && cycle != 0) s_valid = 1'bz;
            if (cycle % 37 == 0 && cycle != 0) m_ready = 1'bx;
            if (cycle % 41 == 0 && cycle != 0) m_ready = 1'bz;
            if (cycle % 43 == 0 && cycle != 0) rst_n = 1'bx;
            if (cycle % 47 == 0 && cycle != 0) rst_n = 1'bz;
            data = {$urandom, $urandom, $urandom};
            if (cycle % 11 == 0) data[7:0] = 'x;
            if (cycle % 13 == 0) data[47:32] = 'z;
            if (cycle % 17 == 0) data[72:64] = 'x;
            #1; clk = 1; #1; clk = 0; #1;
        end
        for (integer i = 0; i < 9; i++) begin
            if (checks[i] != 2 * cycles + 1) $fatal(1, "Incomplete width index=%0d", i);
        end
        $display("AXI_OCCUPANCY_PASS cycles=%0d widths=9 output_checks=%0d", cycles, (2*cycles+1)*9);
        $finish;
    end
endmodule
