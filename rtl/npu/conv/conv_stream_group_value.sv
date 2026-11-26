// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 先形成解码及运行阶段的通道范围，再由配置和描述符提交选择完整结果。
(* keep_hierarchy = "yes" *)
module conv_stream_group_value #(
  parameter int p_width = 9
) (
  input wire logic i_configure, // 当前周期接收新配置
  input wire logic i_commit, // 当前周期提交有效的快速描述符
  input wire logic [3:0] i_decoded_source, // 四种归约解码结果的选择位
  input wire logic i_chunk_end, // 当前传输到达分块末列
  input wire logic [7:0][p_width-1:0] i_candidate, // 推进、配置、提交、四种解码及行首范围
  output logic [p_width-1:0] o_value // 当前事件需要保存的通道范围
);
  logic [p_width-1:0] decoded_value, running_value;
  (* keep = 1 *) logic [p_width-1:0] operation_value;
  logic [7:0] reference_select;
  logic [p_width-1:0] reference_value;
  conv_group_range_select #(.p_choices(4), .p_width(p_width)) u_decoded (
    .i_select(i_decoded_source), .i_data(i_candidate[6:3]), .o_data(decoded_value)
  );
  assign running_value = i_chunk_end ? i_candidate[7] : i_candidate[0];
  assign operation_value = (|i_decoded_source) ? decoded_value : running_value;
  // 完整优先选择保留未知控制值的逐位传播。
  conv_group_range_choice u_reference_select (
    .i_configure(i_configure), .i_commit(i_commit), .i_decoded_source(i_decoded_source),
    .i_chunk_end(i_chunk_end), .o_select(reference_select)
  );
  always_comb begin
    reference_value = '0;
    for (int source = 0; source < 8; source++)
      reference_value |= {p_width{reference_select[source]}} & i_candidate[source];
  end
  always_comb begin
    o_value = reference_value;
    case (^{i_configure, i_commit, i_decoded_source, i_chunk_end, i_candidate})
      1'b0, 1'b1: o_value = i_configure ? i_candidate[1] :
          i_commit ? i_candidate[2] : operation_value;
      default: ;
    endcase
  end
endmodule

`default_nettype wire
