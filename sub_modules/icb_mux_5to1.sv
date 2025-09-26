// filepath: /home/etc/FPGA/tflm_ai_dsa/sub_modules/icb_mux_5to1.sv
`ifndef ICB_MUX_5TO1_SV
`define ICB_MUX_5TO1_SV

`include "icb_types.sv"

// 5选1 ICB 多路器（主设备 -> 5 个从设备，响应由被选中的从设备返回主设备）
module icb_mux_5to1 (
    input  logic                      clk,
    input  logic                      rst_n,

    // Master (initiator) interfaces（方向化封装）
    input  icb_cmd_m_t                 m_cmd,       // master -> mux: cmd payload
    output icb_cmd_s_t                 m_cmd_rsp,   // mux -> master: cmd ready

    output icb_rsp_s_t                 m_rsp,       // mux -> master: rsp payload
    input  icb_rsp_m_t                 m_rsp_ready, // master -> mux: rsp ready

    // Slave 0
    // 使用方向化封装的从设备端口
    output icb_cmd_m_t                 s0_cmd,      // mux -> slave: cmd payload
    input  icb_cmd_s_t                 s0_cmd_ready, // slave -> mux: cmd ready
    input  icb_rsp_s_t                 s0_rsp,      // slave -> mux: rsp payload
    output icb_rsp_m_t                 s0_rsp_ready, // mux -> slave: rsp ready

    // Slave 1
    output icb_cmd_m_t                 s1_cmd,
    input  icb_cmd_s_t                 s1_cmd_ready,
    input  icb_rsp_s_t                 s1_rsp,
    output icb_rsp_m_t                 s1_rsp_ready,

    // Slave 2
    output icb_cmd_m_t                 s2_cmd,
    input  icb_cmd_s_t                 s2_cmd_ready,
    input  icb_rsp_s_t                 s2_rsp,
    output icb_rsp_m_t                 s2_rsp_ready,

    // Slave 3
    output icb_cmd_m_t                 s3_cmd,
    input  icb_cmd_s_t                 s3_cmd_ready,
    input  icb_rsp_s_t                 s3_rsp,
    output icb_rsp_m_t                 s3_rsp_ready,

    // Slave 4
    output icb_cmd_m_t                 s4_cmd,
    input  icb_cmd_s_t                 s4_cmd_ready,
    input  icb_rsp_s_t                 s4_rsp,
    output icb_rsp_m_t                 s4_rsp_ready,

    // select signal: value 0..4 chooses which slave is active
    input  logic [2:0]                sel
);

    // Default: drive slave command structs (only valid asserted for selected slave)
    assign s0_cmd.valid  = (sel == 3'd0) ? m_cmd.valid : 1'b0;
    assign s1_cmd.valid  = (sel == 3'd1) ? m_cmd.valid : 1'b0;
    assign s2_cmd.valid  = (sel == 3'd2) ? m_cmd.valid : 1'b0;
    assign s3_cmd.valid  = (sel == 3'd3) ? m_cmd.valid : 1'b0;
    assign s4_cmd.valid  = (sel == 3'd4) ? m_cmd.valid : 1'b0;

    // Forward command payload to all slaves (only valid asserted for selected slave)
    assign s0_cmd.addr   = m_cmd.addr;
    assign s1_cmd.addr   = m_cmd.addr;
    assign s2_cmd.addr   = m_cmd.addr;
    assign s3_cmd.addr   = m_cmd.addr;
    assign s4_cmd.addr   = m_cmd.addr;

    assign s0_cmd.read   = m_cmd.read;
    assign s1_cmd.read   = m_cmd.read;
    assign s2_cmd.read   = m_cmd.read;
    assign s3_cmd.read   = m_cmd.read;
    assign s4_cmd.read   = m_cmd.read;

    assign s0_cmd.wdata  = m_cmd.wdata;
    assign s1_cmd.wdata  = m_cmd.wdata;
    assign s2_cmd.wdata  = m_cmd.wdata;
    assign s3_cmd.wdata  = m_cmd.wdata;
    assign s4_cmd.wdata  = m_cmd.wdata;

    assign s0_cmd.wmask  = m_cmd.wmask;
    assign s1_cmd.wmask  = m_cmd.wmask;
    assign s2_cmd.wmask  = m_cmd.wmask;
    assign s3_cmd.wmask  = m_cmd.wmask;
    assign s4_cmd.wmask  = m_cmd.wmask;

    assign s0_cmd.size   = m_cmd.size;
    assign s1_cmd.size   = m_cmd.size;
    assign s2_cmd.size   = m_cmd.size;
    assign s3_cmd.size   = m_cmd.size;
    assign s4_cmd.size   = m_cmd.size;

    // Master cmd ready is driven by the selected slave's ready
    assign m_cmd_rsp.ready = (sel == 3'd0) ? s0_cmd_ready.ready :
                            (sel == 3'd1) ? s1_cmd_ready.ready :
                            (sel == 3'd2) ? s2_cmd_ready.ready :
                            (sel == 3'd3) ? s3_cmd_ready.ready :
                            (sel == 3'd4) ? s4_cmd_ready.ready : 1'b0;

    // Responses: only the selected slave's response is forwarded to master
    assign m_rsp.rsp_valid = (sel == 3'd0) ? s0_rsp.rsp_valid :
                            (sel == 3'd1) ? s1_rsp.rsp_valid :
                            (sel == 3'd2) ? s2_rsp.rsp_valid :
                            (sel == 3'd3) ? s3_rsp.rsp_valid :
                            (sel == 3'd4) ? s4_rsp.rsp_valid : 1'b0;

    assign m_rsp.rsp_rdata = (sel == 3'd0) ? s0_rsp.rsp_rdata :
                            (sel == 3'd1) ? s1_rsp.rsp_rdata :
                            (sel == 3'd2) ? s2_rsp.rsp_rdata :
                            (sel == 3'd3) ? s3_rsp.rsp_rdata :
                            (sel == 3'd4) ? s4_rsp.rsp_rdata : '0;

    assign m_rsp.rsp_err   = (sel == 3'd0) ? s0_rsp.rsp_err :
                            (sel == 3'd1) ? s1_rsp.rsp_err :
                            (sel == 3'd2) ? s2_rsp.rsp_err :
                            (sel == 3'd3) ? s3_rsp.rsp_err :
                            (sel == 3'd4) ? s4_rsp.rsp_err : 1'b0;

    // Forward master's response-ready to the selected slave, others deassert ready
    assign s0_rsp_ready.rsp_ready = (sel == 3'd0) ? m_rsp_ready.rsp_ready : 1'b0;
    assign s1_rsp_ready.rsp_ready = (sel == 3'd1) ? m_rsp_ready.rsp_ready : 1'b0;
    assign s2_rsp_ready.rsp_ready = (sel == 3'd2) ? m_rsp_ready.rsp_ready : 1'b0;
    assign s3_rsp_ready.rsp_ready = (sel == 3'd3) ? m_rsp_ready.rsp_ready : 1'b0;
    assign s4_rsp_ready.rsp_ready = (sel == 3'd4) ? m_rsp_ready.rsp_ready : 1'b0;

endmodule

`endif // ICB_MUX_5TO1_SV
