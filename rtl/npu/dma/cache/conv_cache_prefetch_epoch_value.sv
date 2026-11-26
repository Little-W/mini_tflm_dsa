// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 预取代次分别完成相等比较，请求接收仅选择当前槽位应保存的一位结果。
module conv_cache_prefetch_epoch_value (
  input wire logic i_push /* 本周期压入预取候选 */, i_fire /* 本周期消费工作请求 */, i_offer_work /* 预取候选与工作请求代次相同 */, i_offer_demand /* 预取候选与缺失请求代次相同 */, i_slot_work /* 当前槽位与工作请求代次相同 */ , // 本周期压入预取候选；本周期消费工作请求；预取候选与工作请求代次相同；预取候选与缺失请求代次相同；当前槽位与工作请求代次相同
  output logic o_value // 更新后的槽位代次匹配结果
);
  always_comb begin
    o_value = i_slot_work;
    if (i_push) o_value = i_fire ? i_offer_work : i_offer_demand;
  end
endmodule

`default_nettype wire
