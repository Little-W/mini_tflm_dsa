// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 同周期请求参与空闲判断，开始事件和后台空闲条件并行计算。
module kernel_request_idle (
    input  wire logic i_request,
    input  wire logic i_granted,
    input  wire logic i_quiescent,
    output logic o_start,
    output logic o_idle
);
    assign o_start = i_request && i_granted;
    assign o_idle = i_quiescent && !(i_request && i_granted);
endmodule

`default_nettype wire
