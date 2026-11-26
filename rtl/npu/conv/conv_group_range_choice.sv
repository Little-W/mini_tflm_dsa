// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 统一配置、描述符、归约解码和流式推进的组范围优先级，输出完整候选选择。
(* keep_hierarchy = "yes" *)
module conv_group_range_choice (
  input wire logic i_configure, // 当前周期接收新配置
  input wire logic i_commit, // 当前周期提交有效的快速描述符
  input wire logic [3:0] i_decoded_source, // 归约解码选择的四种起点范围
  input wire logic i_chunk_end, // 当前输出传输到达分块末列
  output logic [7:0] o_select // 传输、配置、描述符、四种解码和行首范围的选择位
);
  always_comb begin
    o_select = '0;
    o_select[0] = !i_chunk_end;
    o_select[7] = i_chunk_end;
    case (1'b1)
      i_configure: o_select = 8'b00000010;
      i_commit: o_select = 8'b00000100;
      (|i_decoded_source): begin
        o_select = '0;
        o_select[6:3] = i_decoded_source;
      end
      default: ;
    endcase
  end
endmodule

`default_nettype wire
