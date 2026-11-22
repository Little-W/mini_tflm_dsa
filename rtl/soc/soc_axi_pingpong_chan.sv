// SPDX-License-Identifier: Apache-2.0
`default_nettype none

module soc_axi_pingpong_chan #(
    parameter int unsigned WIDTH = 1
) (
    input  wire logic             clk,
    input  wire logic             rst_n,
    input  wire logic             s_valid,
    output logic             s_ready,
    input  wire logic [WIDTH-1:0] s_data,
    output logic             m_valid,
    input  wire logic             m_ready,
    output logic [WIDTH-1:0] m_data
);

    //! 0. 内部信号
    //! ------------

    logic [WIDTH-1:0] data0_q;
    logic [WIDTH-1:0] data1_q;
    logic             rd_sel_q;
    logic             wr_sel_q;
    logic             occupied_q;
    logic             full_q;
    logic             push;
    logic             pop;

    //! 1. 接收与发送事件
    //! ------------------

    assign push = s_valid && s_ready;
    assign pop = m_valid && m_ready;

    //! 2. 数据与状态更新
    //! ------------------

    // 两项缓冲直接保存非空与满状态，同周期接收和发送保持占用状态。
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            data0_q <= '0;
            data1_q <= '0;
            rd_sel_q <= 1'b0;
            wr_sel_q <= 1'b0;
            occupied_q <= 1'b0;
            full_q <= 1'b0;
        end else begin
            if (push) begin
                if (wr_sel_q) begin
                    data1_q <= s_data;
                end else begin
                    data0_q <= s_data;
                end
                wr_sel_q <= ~wr_sel_q;
            end
            if (pop) begin
                rd_sel_q <= ~rd_sel_q;
            end
            case ({push, pop})
                2'b10: begin
                    occupied_q <= 1'b1;
                    full_q <= occupied_q;
                end
                2'b01: begin
                    occupied_q <= full_q;
                    full_q <= 1'b0;
                end
                default: begin end
            endcase
        end
    end

    //! 3. 输出生成
    //! ------------

    // 输出资格由占用状态直接产生，响应有效信号无需经过计数译码。
    assign s_ready = !full_q;
    assign m_valid = occupied_q;

    // 读位置选择当前发送项，数据在等待接收期间保持稳定。
    assign m_data = rd_sel_q ? data1_q : data0_q;

endmodule

`default_nettype wire
