// SPDX-License-Identifier: Apache-2.0
`default_nettype none
// 用两个存储槽缓冲有效数据，在输入与输出独立握手时保持传输顺序。
module soc_axi_pingpong_chan #(
    parameter int unsigned WIDTH = 1
) (
    input  wire logic             clk /* 模块工作时钟。 */,
    input  wire logic             rst_n /* 低电平有效复位。 */,
    input  wire logic             s_valid /* 输入数据有效。 */,
    output logic             s_ready /* 可接收输入数据。 */,
    input  wire logic [WIDTH-1:0] s_data /* 待缓冲的输入数据。 */,
    output logic             m_valid /* 缓冲区输出数据有效。 */,
    input  wire logic             m_ready /* 下游可接收输出数据。 */,
    output logic [WIDTH-1:0] m_data /* 缓冲区输出数据。 */
);

    //! 0. 内部信号
    //! ------------

`ifdef XILINX_FPGA
    localparam bit p_distributed_storage = WIDTH >= 24;
`else
    localparam bit p_distributed_storage = 1'b0;
`endif

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
            rd_sel_q <= 1'b0;
            wr_sel_q <= 1'b0;
            occupied_q <= 1'b0;
            full_q <= 1'b0;
        end else begin
            if (push) begin
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

    // FPGA 的宽通道采用单写口、异步读口存储，两个逻辑槽保持原有读写顺序。
    // 额外的常零行供复位后尚未写入的槽读取，运行中复位无需改写数据存储。
    if (p_distributed_storage) begin : g_distributed_storage
        (* ram_style = "distributed" *) logic [WIDTH-1:0] data_memory [0:3];
        logic initialized0_q, initialized1_q;
        logic [1:0] read_address;

        initial begin
            data_memory[2] = '0;
            data_memory[3] = '0;
        end
        always_ff @(posedge clk) begin
            if (!rst_n) begin
                initialized0_q <= 1'b0;
                initialized1_q <= 1'b0;
            end else if (push) begin
                if (wr_sel_q) initialized1_q <= 1'b1;
                else initialized0_q <= 1'b1;
            end
        end
        // 每次接收只写入一个槽，写地址由已保存的位置直接给出。
        always_ff @(posedge clk) begin
            if (!rst_n) begin
            end else if (push) begin
                data_memory[{1'b0, wr_sel_q}] <= s_data;
            end
        end
        assign data0_q = initialized0_q ? data_memory[0] : '0;
        assign data1_q = initialized1_q ? data_memory[1] : '0;
        assign read_address = (rd_sel_q ? initialized1_q : initialized0_q)
                            ? {1'b0, rd_sel_q} : 2'd2;
        assign m_data = data_memory[read_address];
    end else begin : g_register_storage
        // 窄通道及通用实现直接保存两个数据字，复位同时清除两个槽。
        always_ff @(posedge clk) begin
            if (!rst_n) begin
                data0_q <= '0;
                data1_q <= '0;
            end else if (push) begin
                if (wr_sel_q) data1_q <= s_data;
                else data0_q <= s_data;
            end
        end
        assign m_data = rd_sel_q ? data1_q : data0_q;
    end

endmodule

`default_nettype wire
