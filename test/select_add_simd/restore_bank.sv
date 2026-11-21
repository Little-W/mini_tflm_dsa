// SPDX-License-Identifier: Apache-2.0
// 按生产调用恢复十六个有符号字节，各通道共享九位偏移。
module restore_bank(
    input logic signed [15:0][7:0] bytes,
    input logic signed [8:0] offset,
    output logic signed [15:0][15:0] values
);
    for(genvar group_index=0;group_index<4;group_index++) begin:g_group
        logic[47:0] lhs,rhs,sum;
        for(genvar lane=0;lane<4;lane++) begin:g_lane
            assign lhs[lane*12+:12]=12'($signed(bytes[4*group_index+lane]));
            assign rhs[lane*12+:12]=12'($signed(offset));
            assign values[4*group_index+lane]=16'($signed(sum[lane*12+:10]));
        end
        select_add #(.p_width(48),.p_use_dsp(1'b1),.p_split_12bit(1'b1)) u_add(
            .i_lhs(lhs),.i_rhs0(rhs),.i_rhs1(rhs),.i_rhs_select(1'b0),.i_add_enable(1'b1),.o_sum(sum)
        );
    end
endmodule
