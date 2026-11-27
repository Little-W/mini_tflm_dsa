// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 预测 AXI 地址按传输字节数前进时产生的低八位进位。
// 两组步长候选并行计算，最高步长位只选择已经形成的一位结果。
module soc_ram_low_carry (
    input wire logic [7:0] i_address, // 当前读取字节地址的低八位。
    input wire logic [2:0] i_size, // 每拍传输字节数的二进制对数。
    output logic o_carry // 地址按当前步长前进时向第八位产生的进位。
);
    logic small_suffix;
    (* keep = 1 *) logic [1:0] carry_candidate;

    assign small_suffix = (i_address[2] || (&i_size[1:0])) &&
        (i_address[1] || i_size[1]) &&
        (i_address[0] || (|i_size[1:0]));
    assign carry_candidate[0] = (&i_address[7:3]) && small_suffix;
    assign carry_candidate[1] = i_address[7] &&
        (i_address[6] || (&i_size[1:0])) &&
        (i_address[5] || i_size[1]) &&
        (i_address[4] || (|i_size[1:0]));

    always_comb begin
        o_carry = i_size[2] ? carry_candidate[1] : carry_candidate[0];
        // 未知步长保留完整移位表达式的四态传播结果。
        case (^i_size)
            1'b0, 1'b1: begin end
            default: o_carry = &(i_address | ~(8'hff << i_size));
        endcase
    end
endmodule

`default_nettype wire
