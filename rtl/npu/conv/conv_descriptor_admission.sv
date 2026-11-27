// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 独立准备空闲接收与输出末拍接收条件，列末和快速复用结果只参与末级选择。
(* keep_hierarchy = "yes" *)
module conv_descriptor_admission #(
  parameter bit p_register_descriptor = 1'b1
) (
  input wire logic i_idle_context, // 空闲阶段已经满足配置和运行接收条件
  input wire logic i_output_context, // 数据输出阶段已满足响应、写入和最后一行条件
  input wire logic i_early_output, // 运行项允许在输出完成前准备下一描述符
  input wire logic i_chunk_end, // 本次输出完成分块的最后一列
  input wire logic i_prepared_valid, // 准备槽保存了尚未提交的描述符
  input wire logic [1:0] i_commit_context, // 空闲提交及输出末拍提交的独立前置条件
  input wire logic i_fast, // 输入描述符可以复用已保存的坐标上下文
  input wire logic i_configure, // 当前周期提交新的卷积配置
  output logic o_ready // 前端能够在当前周期接收描述符
);
  logic [3:0] ready_terms;
  logic reference_ready;
  conv_descriptor_admission_terms #(.p_register_descriptor(p_register_descriptor)) u_terms (
    .i_idle(i_idle_context), .i_output(i_output_context), .i_early(i_early_output),
    .i_prepared(i_prepared_valid), .i_commit_context(i_commit_context), .i_configure(i_configure),
    .o_terms(ready_terms)
  );
  assign reference_ready = (i_idle_context || (i_output_context && i_chunk_end) ||
      (i_early_output && i_chunk_end && i_fast)) && !i_configure &&
      (!p_register_descriptor || !i_prepared_valid ||
       ((i_commit_context[0] || (i_commit_context[1] && i_chunk_end)) && i_fast));
  always_comb begin
    o_ready = reference_ready;
    case (^{i_idle_context, i_output_context, i_early_output, i_chunk_end,
             i_prepared_valid, i_commit_context, i_fast, i_configure})
      1'b0, 1'b1: o_ready = ready_terms[0] || (i_fast && ready_terms[1]) ||
          (i_chunk_end && (ready_terms[2] || (i_fast && ready_terms[3])));
      default: ;
    endcase
  end
endmodule

`default_nettype wire
