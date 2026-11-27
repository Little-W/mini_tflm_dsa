// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 保存各存储体的完成行数，并行比较合并输出的行上限，再选择当前存储体的行结束结果。
// 计数与原行数存储同拍写入；外部有效位管理复位和释放，固定四选一树保持选择深度。
(* keep_hierarchy = "yes" *)
module vec_s8_fifo_row_match #(
  parameter int p_banks = 32,
  parameter int p_count_width = 5,
  parameter int p_bank_width = (p_banks <= 1) ? 1 : $clog2(p_banks)
) (
  input logic i_clk, // 行数写入的工作时钟
  input logic i_write_enable, // 当前存储体已完成写入并提交有效行数
  input logic [p_bank_width-1:0] i_write_bank, // 本拍完成写入的存储体编号
  input logic [p_count_width-1:0] i_write_count, // 本拍完成写入的有效行数
  input logic [p_banks-1:0] i_bank_ready, // 各存储体当前保存完整结果的有效位
  input logic [p_count_width-1:0] i_row_limit, // 合并输出当前行的比较上限
  input logic [p_bank_width-1:0] i_read_bank, // 当前合并输出使用的存储体编号
  output logic o_row_last // 当前行已达到所选存储体的有效行数
);
  //! 0. 并行行数与比较结果
  //! ------------------------

  localparam int p_levels = (p_bank_width + 1) / 2;
  logic [p_count_width-1:0] count_q [p_banks];
  (* keep = 1 *) logic [p_banks-1:0] bank_row_last;
  wire [p_banks-1:0] result_level [0:p_levels];

  for (genvar bank = 0; bank < p_banks; bank++) begin : g_bank
    always_ff @(posedge i_clk) begin
      if (i_write_enable && i_write_bank == p_bank_width'(bank)) begin
        count_q[bank] <= i_write_count;
      end
    end
    // 有效位在比较后选择结果；未知有效位保留完整计数的逐位条件合并。
    always_comb begin
      case (i_bank_ready[bank])
        1'b0: bank_row_last[bank] = i_row_limit >= p_count_width'(0);
        1'b1: bank_row_last[bank] = i_row_limit >= count_q[bank];
        default: bank_row_last[bank] = i_row_limit >= (i_bank_ready[bank] ? count_q[bank] : '0);
      endcase
    end
  end

  //! 1. 分组选择当前存储体
  //! ------------------------

  assign result_level[0] = bank_row_last;
  for (genvar level = 0; level < p_levels; level++) begin : g_level
    localparam int p_inputs = p_banks >> (2 * level);
    localparam int p_outputs = (p_inputs + 3) / 4;
    (* keep = 1 *) logic [p_outputs-1:0] group_result;
    for (genvar group_index = 0; group_index < p_outputs; group_index++) begin : g_group
      if (p_inputs >= 4) begin : g_four
        wire [3:0] candidates = result_level[level][group_index*4+:4];
        assign group_result[group_index] = candidates[i_read_bank[level*2+:2]];
      end else begin : g_two
        wire [1:0] candidates = result_level[level][1:0];
        assign group_result[group_index] = candidates[i_read_bank[level*2]];
      end
    end
    assign result_level[level+1] = p_banks'(group_result);
  end
  assign o_row_last = result_level[p_levels][0];
endmodule

`default_nettype wire
