`timescale 1ns / 1ps

module fpga_top #(
    parameter int unsigned WEIGHT_WIDTH = 16,
    parameter int unsigned DATA_WIDTH = 16,
    parameter int unsigned SIZE = 16,
    parameter int unsigned BUS_WIDTH = 32,
    parameter int unsigned REG_WIDTH = 32,
    parameter int unsigned AXIL_DATA_WIDTH = 32,
    parameter int unsigned AXIL_ADDR_WIDTH = 16,
    parameter int unsigned AXI_ADDR_WIDTH = 32,
    parameter int unsigned NPU_ADDR_WIDTH = AXI_ADDR_WIDTH,
    parameter int unsigned IA_CACHE_BLOCKS = 4,
    parameter int unsigned ENABLE_DW_POOL = 1,
    parameter int unsigned DW_PE_COUNT = (SIZE < 8) ? SIZE : 8,
    parameter int unsigned ENABLE_VECTOR_ENGINE = ENABLE_DW_POOL,
    parameter int unsigned VECTOR_PE_COUNT = DW_PE_COUNT,
    parameter int unsigned DW_MAX_TAPS = 49,
    parameter int unsigned POOL_MAX_TAPS = 256,
    parameter int unsigned AXI_READ_OUTSTANDING = 4,
    parameter int unsigned AXI_WRITE_OUTSTANDING = AXI_READ_OUTSTANDING,
    parameter int unsigned CPU_MEM_DP = 65536,
    parameter string CPU_MEM_PATH = "",
    parameter int unsigned CPU_MEM_INIT_EN = 0,
    parameter int unsigned CPU_ENABLE_ICACHE = 0,
    parameter int unsigned NPU_AXI_TIMING_BUFFER = 1,
    parameter int unsigned CPU_AXI_WRITE_TIMING_BUFFER = 1,
    parameter int unsigned BYPASS_RAM_PINGPONG = 0,
    parameter int unsigned RAM_WRITE_TIMING_BUFFER = 1,
    parameter int unsigned NPU_ENABLE_IS_MODE = 1,
    parameter int unsigned NPU_ENABLE_PER_CHANNEL = 1,
    parameter int unsigned NPU_ENABLE_CLOCK_GATING = 1
) (
    input  wire       sys_clk,
    input  wire       sys_rst_n,
    input  wire       UART_0_rxd,
    output wire       UART_0_txd,
    output wire [3:0] user_led_tri_o
);

    wire        npu_busy;
    wire        npu_irq;
    wire        soc_finish;
    wire [31:0] soc_status;
    wire        cpu_trap;
    wire        soc_pass;
    wire        soc_fail;
    wire        soc_clk;
    wire        clk_wiz_locked;
    logic [2:0] soc_rst_n_sync = 3'b000;

    clk_wiz_0 u_clk_wiz_0 (
        .clk_out1(soc_clk),
        .reset(~sys_rst_n),
        .locked(clk_wiz_locked),
        .clk_in1(sys_clk)
    );

    always_ff @(posedge soc_clk) begin
        if (!sys_rst_n || !clk_wiz_locked) begin
            soc_rst_n_sync <= 3'b000;
        end else begin
            soc_rst_n_sync <= {soc_rst_n_sync[1:0], 1'b1};
        end
    end

    soc_top #(
        .AXIL_DATA_WIDTH(AXIL_DATA_WIDTH),
        .AXIL_ADDR_WIDTH(AXIL_ADDR_WIDTH),
        .WEIGHT_WIDTH(WEIGHT_WIDTH),
        .DATA_WIDTH(DATA_WIDTH),
        .SIZE(SIZE),
        .BUS_WIDTH(BUS_WIDTH),
        .REG_WIDTH(REG_WIDTH),
        .AXI_ADDR_WIDTH(AXI_ADDR_WIDTH),
        .NPU_ADDR_WIDTH(NPU_ADDR_WIDTH),
        .IA_CACHE_BLOCKS(IA_CACHE_BLOCKS),
        .ENABLE_VECTOR_ENGINE(ENABLE_VECTOR_ENGINE), .VECTOR_PE_COUNT(VECTOR_PE_COUNT), .DW_MAX_TAPS(DW_MAX_TAPS), .POOL_MAX_TAPS(POOL_MAX_TAPS),
        .PS_FRAME_COUNT(SIZE),
        .AXI_READ_OUTSTANDING(AXI_READ_OUTSTANDING),
        .AXI_WRITE_OUTSTANDING(AXI_WRITE_OUTSTANDING),
        .CPU_MEM_DP(CPU_MEM_DP),
        .CPU_MEM_PATH(CPU_MEM_PATH),
        .CPU_MEM_INIT_EN(CPU_MEM_INIT_EN),
        .CPU_ENABLE_ICACHE(CPU_ENABLE_ICACHE),
        .NPU_AXI_TIMING_BUFFER(NPU_AXI_TIMING_BUFFER),
        .CPU_AXI_WRITE_TIMING_BUFFER(CPU_AXI_WRITE_TIMING_BUFFER),
        .BYPASS_RAM_PINGPONG(BYPASS_RAM_PINGPONG),
        .RAM_WRITE_TIMING_BUFFER(RAM_WRITE_TIMING_BUFFER),
        .NPU_ENABLE_IS_MODE(NPU_ENABLE_IS_MODE),
        .NPU_ENABLE_PER_CHANNEL(NPU_ENABLE_PER_CHANNEL),
        .NPU_ENABLE_CLOCK_GATING(NPU_ENABLE_CLOCK_GATING)
    ) u_soc_top (
        .clk(soc_clk),
        .rst_n(soc_rst_n_sync[2]),
        .mem_reload_req(1'b0),
        .npu_busy(npu_busy),
        .npu_irq(npu_irq),
        .uart_tx(UART_0_txd),
        .uart_rx(UART_0_rxd),
        .soc_finish(soc_finish),
        .soc_status(soc_status),
        .cpu_trap(cpu_trap)
    );

    assign soc_pass = soc_finish && (soc_status == 32'h0000_0001);
    assign soc_fail = soc_finish && (soc_status != 32'h0000_0001);

    assign user_led_tri_o[0] = npu_busy;
    assign user_led_tri_o[1] = soc_pass;
    assign user_led_tri_o[2] = cpu_trap || soc_fail;
    assign user_led_tri_o[3] = ^soc_status ^ npu_irq;

endmodule
