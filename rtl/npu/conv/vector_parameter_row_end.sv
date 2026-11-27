// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 判断当前 DMA 总线拍是否覆盖参数数组末尾，每个参数占四字节。
// 列索引、拍字节数和元素数保持完整三十二位运算语义，输出为当前周期组合资格。
(* keep_hierarchy = "yes" *)
module vector_parameter_row_end #(
    parameter int p_column_width = 6,
    parameter int p_active_width = 5,
    parameter int p_bus_bytes = 8
) (
    input logic [p_column_width-1:0] i_column_base, // 本拍返回数据的起始字节索引
    input logic [p_active_width-1:0] i_active, // 本行需要返回的四字节参数数量
    output logic o_complete // 当前完整总线拍覆盖本行末尾
);
    assign o_complete = 32'(i_column_base) + 32'(p_bus_bytes) >= (32'(i_active) << 2);
endmodule

`default_nettype wire
