// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 保存地址与范围端点并行比较，末级响应控制接收完整的大小关系。
(* keep_hierarchy = "yes" *)
module conv_cache_snapshot_range (
  input wire logic [31:0] i_address /* 输入字节地址 */, i_bound /* 比较范围端点 */ , // 输入字节地址；比较范围端点
  output logic o_below // 输入地址小于端点
);
  logic below_parallel, unused_equal;
  parallel_unsigned_compare #(.p_width(32), .p_preserve_groups(1'b1)) u_range (
    .i_a(i_address), .i_b(i_bound), .o_less(below_parallel), .o_equal(unused_equal)
  );
`ifdef SYNTHESIS
  assign o_below = below_parallel;
`else
  logic below_reference, unused_reference_equal;
  unsigned_compare #(.p_width(32)) u_reference (
    .i_a(i_address), .i_b(i_bound),
    .o_less(below_reference), .o_equal(unused_reference_equal)
  );
  // 含未知位时沿用字节分组比较的传播规则。
  always_comb begin
    case (^{i_address, i_bound})
      1'b0, 1'b1: o_below = below_parallel;
      default: o_below = below_reference;
    endcase
  end
`endif
endmodule

`default_nettype wire
