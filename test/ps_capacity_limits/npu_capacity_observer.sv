// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 在配置第二级的对应相位比较原始容量算式与生产容量结果。
module npu_capacity_observer #(
  parameter bit p_shared_ram_enabled = 1'b1,
  parameter int unsigned p_physical_banks = 7,
  parameter logic [63:0] p_frame_word_limit = 64'd2048
) (
  input logic i_clk,
  input logic i_rst_n,
  input logic i_stage2_valid,
  input logic [2:0] i_capacity_phase,
  input logic [31:0] i_bank_count,
  input logic [31:0] i_bank_depth,
  input logic [63:0] i_frames,
  input logic [63:0] i_raw_frame_words,
  input logic [63:0] i_long_frame_words,
  input logic [63:0] i_raw_total,
  input logic [63:0] i_long_total,
  input logic [63:0] i_admission_words,
  input logic i_raw_fits,
  input logic i_long_fits,
  input logic i_admission_fits
);
  always @(posedge i_clk) begin
    if (i_rst_n && i_stage2_valid && p_shared_ram_enabled &&
        i_bank_count < 32'(p_physical_banks)) begin
      // 相位 0 保存有界行数与帧数，从相位 1 开始使用这些寄存值。
      if (i_capacity_phase >= 3'd1) begin
        assert (i_raw_fits == (i_frames == 64'd0 ||
            (i_raw_frame_words <= p_frame_word_limit && i_raw_total <= 64'(i_bank_depth))))
          else $fatal(1, "Raw bank capacity differs");
        assert (i_long_fits == (i_frames == 64'd0 ||
            (i_long_frame_words <= p_frame_word_limit && i_long_total <= 64'(i_bank_depth))))
          else $fatal(1, "Long bank capacity differs");
      end
      if (i_capacity_phase >= 3'd4) begin
        assert (i_admission_fits == (i_admission_words <= 64'(i_bank_depth)))
          else $fatal(1, "Admission bank capacity differs");
      end
    end
  end
endmodule

bind npu_task_configuration npu_capacity_observer #(
  .p_shared_ram_enabled(p_shared_ram_enabled),
  .p_physical_banks(p_shared_physical_banks),
  .p_frame_word_limit(64'(4 * p_ia_reuse_num_max * p_size))
) u_capacity_comparison (
  .i_clk(clk),
  .i_rst_n(rst_n),
  .i_stage2_valid(o_cfg_valid_q[2]),
  .i_capacity_phase(cfg_capacity_phase),
  .i_bank_count(o_active_ps_bank_count),
  .i_bank_depth(o_active_ps_bank_depth),
  .i_frames(64'(ps_frames_bounded)),
  .i_raw_frame_words(ps_raw_frame_bank_words),
  .i_long_frame_words(ps_long_frame_bank_words),
  .i_raw_total(64'(ps_raw_bank_total)),
  .i_long_total(64'(ps_long_bank_total)),
  .i_admission_words(ps_admission_bank_words),
  .i_raw_fits(ps_raw_bank_capacity_fits),
  .i_long_fits(ps_long_bank_capacity_fits),
  .i_admission_fits(ps_admission_bank_capacity_fits)
);

`default_nettype wire
