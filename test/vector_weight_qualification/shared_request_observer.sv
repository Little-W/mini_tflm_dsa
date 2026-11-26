// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 在生产向量和矩阵混合任务中检查共享存储的有效写请求及 IA 端口地址关系。
module vector_weight_request_observer #(
    parameter bit p_nonempty = 1'b0
);
    always @(posedge vector_shared_store.clk) begin
        if (vector_shared_store.rst_n && p_nonempty && vector_shared_store.i_weight_write_en) begin
            assert (|vector_shared_store.i_weight_write_mask)
                else $fatal(1, "Valid vector weight write requires an enabled byte");
        end
    end
endmodule

module paired_ia_request_observer #(
    parameter bit p_paired = 1'b0
);
    always @(posedge ia_ps_channel_ram.clk) begin
        if (ia_ps_channel_ram.rst_n && p_paired && ia_ps_channel_ram.memory_access_enabled) begin
            if (ia_ps_channel_ram.i_ia_read_en[1]) begin
                assert (ia_ps_channel_ram.ia_banks_q == 2 && ia_ps_channel_ram.i_ia_read_addr[1][0])
                    else $fatal(1, "Paired IA read port requires physical bank 1");
            end
            if (ia_ps_channel_ram.i_ia_write_en[1]) begin
                assert (ia_ps_channel_ram.ia_banks_q == 2 && ia_ps_channel_ram.i_ia_write_addr[1][0])
                    else $fatal(1, "Paired IA write port requires physical bank 1");
            end
        end
    end
endmodule

bind vector_shared_store vector_weight_request_observer #(
    .p_nonempty(p_weight_nonempty_writes)
) u_weight_request_observer();
bind ia_ps_channel_ram paired_ia_request_observer #(
    .p_paired(p_paired_ia_ports && p_max_ia_banks == 2)
) u_paired_request_observer();

`default_nettype wire
