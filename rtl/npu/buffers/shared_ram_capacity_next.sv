// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 提前准备共享存储错误状态，四个读取请求按两个通道分组汇总。
(* keep_hierarchy = "yes" *)
module shared_ram_capacity_next (
    input wire logic i_access_enable, // 顶层允许当前任务访问共享存储。
    input wire logic i_cfg_valid, // 当前周期接收存储分配配置。
    input wire logic i_configuration_valid, // 新的输入与部分和空间分配合法。
    input wire logic i_current_fault, // 已经保存的容量或访问错误状态。
    input wire logic i_other_fault, // 输入访问或部分和写入存在错误。
    input wire logic [3:0] i_read_request, // 四个部分和通道的读取请求。
    input wire logic [3:0] i_read_fault_ready, // 对应读取请求将触发许可、地址或冲突错误。
    output logic o_next_fault // 下一时钟沿保存的容量或访问错误状态。
);
    (* keep = 1 *) logic [1:0] read_group_fault;
    (* keep = 1 *) logic prepared_fault;

    // 配置、原有错误和其他访问错误先独立归并。
    assign prepared_fault = (!i_cfg_valid && i_current_fault) ||
        (i_cfg_valid && !i_configuration_valid) ||
        (i_access_enable && i_other_fault);
    for (genvar group = 0; group < 2; group++) begin : g_read_group
        assign read_group_fault[group] =
            (i_read_request[2*group] && i_read_fault_ready[2*group]) ||
            (i_read_request[2*group+1] && i_read_fault_ready[2*group+1]);
    end
    assign o_next_fault = prepared_fault || (i_access_enable && (|read_group_fault));
endmodule

`default_nettype wire
