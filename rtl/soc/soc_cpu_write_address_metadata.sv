// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 在 CPU 写地址进入两项缓冲时保存目的端口，发送阶段直接选择对应的译码结果。
// 接收与发送事件来自同一写地址缓冲，保存位置和读取位置与地址数据同时推进。
module soc_cpu_write_address_metadata #(
    parameter int unsigned ADDR_WIDTH = 32,
    parameter int unsigned CPU_MEM_DP = 65536,
    parameter logic [31:0] CPU_RAM_BASE = 32'h0000_0000,
    parameter logic [31:0] NPU_AXIL_BASE = 32'h1000_0000,
    parameter logic [31:0] UART_BASE = 32'h0200_0000,
    parameter logic [31:0] SOC_CTRL_BASE = 32'h2000_0000
) (
    input wire logic clk, // 写地址缓冲的工作时钟。
    input wire logic rst_n, // 同步低有效复位，与写地址数据使用相同复位。
    input wire logic i_push, // 写地址缓冲在本周期接收一个地址。
    input wire logic i_pop, // 写地址缓冲在本周期发送一个地址。
    input wire logic [ADDR_WIDTH-1:0] i_addr, // 当前待接收的完整 CPU 字节地址。
    output logic [4:0] o_input_dest_flags, // 当前输入地址的 RAM、NPU、UART、控制和错误目的标志。
    output logic [4:0] o_dest_flags // 缓冲区当前发送地址的目的标志，顺序与地址数据一致。
);
    localparam int unsigned CPU_ADDR_LSB = 2;
    localparam int unsigned CPU_RANGE_BITS = CPU_ADDR_LSB + ((CPU_MEM_DP <= 1) ? 0 : $clog2(CPU_MEM_DP));
    logic [4:0] first_flags_q, second_flags_q;
    logic write_select_q, read_select_q;
    function automatic logic [4:0] decode_cpu_flags(input logic [ADDR_WIDTH-1:0] addr);
        logic [31:0] offset;
        logic ram_selected;
        begin
            offset = addr[31:0] - CPU_RAM_BASE;
            // 二次幂容量且起点按容量排列时，直接比较地址高位。
            if (CPU_MEM_DP > 0 && (CPU_MEM_DP & (CPU_MEM_DP-1)) == 0 &&
                CPU_RANGE_BITS <= 32 &&
                (CPU_RAM_BASE & (32'(CPU_MEM_DP)*32'd4-32'd1)) == 32'd0) begin
                ram_selected = ((addr[31:0] ^ CPU_RAM_BASE) >>
                    CPU_RANGE_BITS) == 32'd0;
            end else begin
                ram_selected = ((CPU_RAM_BASE == 32'h0) || (addr[31:0] >= CPU_RAM_BASE)) &&
                    (32'(offset[31:CPU_ADDR_LSB]) < 32'(CPU_MEM_DP));
            end
            if (ram_selected) begin
                decode_cpu_flags = 5'b00001;
            end else if (addr[31:28] == NPU_AXIL_BASE[31:28]) begin
                decode_cpu_flags = 5'b00010;
            end else if (addr[31:12] == UART_BASE[31:12]) begin
                decode_cpu_flags = 5'b00100;
            end else if (addr[31:28] == SOC_CTRL_BASE[31:28]) begin
                decode_cpu_flags = 5'b01000;
            end else begin
                decode_cpu_flags = 5'b10000;
            end
        end
    endfunction

    assign o_input_dest_flags = decode_cpu_flags(i_addr);
    assign o_dest_flags = read_select_q ? second_flags_q : first_flags_q;

    // 地址数据复位为零，因此目的标志复位为零地址的完整译码值。
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            first_flags_q <= decode_cpu_flags('0);
            second_flags_q <= decode_cpu_flags('0);
            write_select_q <= 1'b0;
            read_select_q <= 1'b0;
        end else begin
            if (i_push) begin
                if (write_select_q) second_flags_q <= o_input_dest_flags;
                else first_flags_q <= o_input_dest_flags;
                write_select_q <= !write_select_q;
            end
            if (i_pop) read_select_q <= !read_select_q;
        end
    end
endmodule

`default_nettype wire
