// SPDX-License-Identifier: Apache-2.0
`default_nettype none
// 按 AXI 每拍字节数和突发模式计算下一拍地址，固定地址突发保持当前地址。
module soc_axi_step_address #(
    parameter int unsigned p_width = 32
) (
    input wire logic [p_width-1:0] i_addr /* 当前传输字节地址。 */,
    input wire logic [2:0] i_size /* 单拍字节数的以二为底对数。 */,
    input wire logic [1:0] i_burst /* AXI 突发地址模式。 */,
    output logic [p_width-1:0] o_addr /* 按突发模式计算的下一拍字节地址。 */
);
    logic [p_width-1:0] step;
    logic [p_width-1:0] aligned_addr;
    logic [p_width-1:0] incremented_addr;

    assign step = p_width'(1) << i_size;
    assign aligned_addr = i_addr & ({p_width{1'b1}} << i_size);
    assign incremented_addr = aligned_addr + step;
    assign o_addr = i_burst == 2'b00 ? i_addr : incremented_addr;
endmodule

`default_nettype wire
