`timescale 1ns/1ps

module pingpong_compare #(
    parameter integer WIDTH = 1
) (
    input logic clk,
    input logic rst_n,
    input logic s_valid,
    input logic m_ready,
    input logic [72:0] data,
    output integer checks = 0
);
    wire r_ready, r_valid, c_ready, c_valid;
    wire [WIDTH-1:0] r_data, c_data;

    soc_axi_pingpong_chan_reference #(.WIDTH(WIDTH)) r (
        .clk(clk), .rst_n(rst_n), .s_valid(s_valid), .s_ready(r_ready),
        .s_data(data[WIDTH-1:0]), .m_valid(r_valid), .m_ready(m_ready), .m_data(r_data)
    );
    soc_axi_pingpong_chan #(.WIDTH(WIDTH)) c (
        .clk(clk), .rst_n(rst_n), .s_valid(s_valid), .s_ready(c_ready),
        .s_data(data[WIDTH-1:0]), .m_valid(c_valid), .m_ready(m_ready), .m_data(c_data)
    );

    // 包括无效周期的数据输出，以及两个数据寄存器和全部控制状态。
    task check;
        if ({r_ready, r_valid, r_data, r.data0_q, r.data1_q, r.rd_sel_q, r.wr_sel_q, r.count_q} !==
            {c_ready, c_valid, c_data, c.data0_q, c.data1_q, c.rd_sel_q, c.wr_sel_q, c.count_q}) begin
            $fatal(1, "Pingpong mismatch width=%0d check=%0d", WIDTH, checks);
        end
        checks = checks + 1;
    endtask

    always @(posedge clk or negedge clk) begin
        #0.1; check();
    end

    initial begin
        #0.1; check();
    end
endmodule

module tb_soc_pingpong;
    logic clk = 0, rst_n = 0, s_valid = 0, m_ready = 0;
    logic [72:0] data = 'x;
    wire integer checks [0:8];
    pingpong_compare #(.WIDTH(1)) w1 (.*,.checks(checks[0]));
    pingpong_compare #(.WIDTH(2)) w2 (.*,.checks(checks[1]));
    pingpong_compare #(.WIDTH(34)) w34 (.*,.checks(checks[2]));
    pingpong_compare #(.WIDTH(35)) w35 (.*,.checks(checks[3]));
    pingpong_compare #(.WIDTH(36)) w36 (.*,.checks(checks[4]));
    pingpong_compare #(.WIDTH(54)) w54 (.*,.checks(checks[5]));
    pingpong_compare #(.WIDTH(64)) w64 (.*,.checks(checks[6]));
    pingpong_compare #(.WIDTH(67)) w67 (.*,.checks(checks[7]));
    pingpong_compare #(.WIDTH(73)) w73 (.*,.checks(checks[8]));

    initial begin
        #1;
        for (integer cycle = 0; cycle < 100000; cycle = cycle + 1) begin
            // 周期性清空状态，并覆盖连续填满、连续排空及同时接收发送。
            rst_n = (cycle % 997) != 0;
            s_valid = $urandom_range(0, 1);
            m_ready = $urandom_range(0, 1);
            if (cycle % 64 < 8) begin s_valid = 1; m_ready = 0; end
            if (cycle % 64 >= 8 && cycle % 64 < 16) begin s_valid = 0; m_ready = 1; end
            if (cycle % 64 >= 16 && cycle % 64 < 24) begin s_valid = 1; m_ready = 1; end
            data = {$urandom, $urandom, $urandom};
            if (cycle % 11 == 0) data[7:0] = 'x;
            if (cycle % 13 == 0) data[47:32] = 'x;
            if (cycle % 17 == 0) data[72:64] = 'x;
            #1; clk = 1; #1; clk = 0; #1;
        end
        for (integer i = 0; i < 9; i = i + 1) begin
            if (checks[i] != 200001) $fatal(1, "Incomplete checks width index=%0d", i);
        end
        $display("SOC_PINGPONG_FOUR_STATE_PASS cycles=100000 widths=9 output_checks=1800009");
        $finish;
    end
endmodule
