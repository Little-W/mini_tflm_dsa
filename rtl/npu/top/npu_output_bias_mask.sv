// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 为偏置通道边界形成低位掩码，并检查目标值是否为零。
(* keep_hierarchy = "yes" *)
module npu_output_bias_mask #(
    parameter int unsigned p_width = 10
) (
    input wire logic [p_width-1:0] i_target, // 需要比较的目标值
    output logic [p_width-1:0] o_mask, // 目标边界对应的连续低位掩码
    output logic o_zero // 目标边界为零
);
    logic [p_width-1:0] decremented;
    // 每一位直接读取低位全零条件，各位借位并行形成。
    for (genvar bit_index=0; bit_index<p_width; bit_index++) begin : g_decrement
        if (bit_index == 0) begin : g_first
            assign decremented[bit_index] = ~i_target[bit_index];
        end else begin : g_later
            assign decremented[bit_index] = i_target[bit_index] ^ (~|i_target[bit_index-1:0]);
        end
    end
    always_comb begin
        case (^i_target)
            1'b0, 1'b1: o_mask = decremented;
            default: o_mask = i_target - p_width'(1);
        endcase
    end
    assign o_zero = i_target == '0;
endmodule

`default_nettype wire
