// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 各通道保留独立的九位模加结果，组合模块共用同一输入偏移。
(* keep_hierarchy = "yes" *)
module conv_im2col_sample_offsets #(
  parameter int unsigned p_lanes = 8
) (
  input wire logic [p_lanes-1:0][7:0] i_data, // 各通道的八位有符号输入样本
  input wire logic [8:0] i_offset, // 各样本共用的九位模加偏移
  (* use_dsp = "simd" *) output logic [p_lanes-1:0][8:0] o_sum // 完整宽度的模加结果
);
  //! 3. 输出生成
  //! ------------------

  for (genvar lane = 0; lane < p_lanes; lane++) begin : g_lane
    assign o_sum[lane] = {i_data[lane][7], i_data[lane]} + i_offset;
  end
endmodule

`default_nettype wire
