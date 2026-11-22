// SPDX-License-Identifier: Apache-2.0
`default_nettype none

module soc_axi_step_address #(
    parameter int unsigned p_width = 32
) (
    input wire logic [p_width-1:0] i_addr,
    input wire logic [2:0] i_size,
    input wire logic [1:0] i_burst,
    output logic [p_width-1:0] o_addr
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
