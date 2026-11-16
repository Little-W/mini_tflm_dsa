// SPDX-License-Identifier: Apache-2.0
// RV32 AXI-Lite command transport for the pinned Gemmini accelerator.
// Each submit completes after RoCC accepts the command. Fence waits for both
// the accelerator and all physical AXI transactions to finish.
module gemmini_mmio #(
    parameter int AXIL_ADDR_WIDTH=16,
    parameter int BUS_WIDTH=64,
    parameter int DMA_MAX_BYTES=256*(BUS_WIDTH/8),
    parameter bit IDLE_CLOCK_GATING=1'b1
) (
    input logic clk, rst_n,
    input logic [AXIL_ADDR_WIDTH-1:0] s_axil_awaddr,
    input logic [2:0] s_axil_awprot,
    input logic s_axil_awvalid,
    output logic s_axil_awready,
    input logic [31:0] s_axil_wdata,
    input logic [3:0] s_axil_wstrb,
    input logic s_axil_wvalid,
    output logic s_axil_wready,
    output logic [1:0] s_axil_bresp,
    output logic s_axil_bvalid,
    input logic s_axil_bready,
    input logic [AXIL_ADDR_WIDTH-1:0] s_axil_araddr,
    input logic [2:0] s_axil_arprot,
    input logic s_axil_arvalid,
    output logic s_axil_arready,
    output logic [31:0] s_axil_rdata,
    output logic [1:0] s_axil_rresp,
    output logic s_axil_rvalid,
    input logic s_axil_rready,
    output logic m_axi_arvalid,
    input logic m_axi_arready,
    output logic [31:0] m_axi_araddr,
    output logic [3:0] m_axi_arcache,
    output logic [2:0] m_axi_arprot,
    output logic [1:0] m_axi_arlock,
    output logic [1:0] m_axi_arburst,
    output logic [7:0] m_axi_arlen,
    output logic [2:0] m_axi_arsize,
    input logic m_axi_rvalid,
    output logic m_axi_rready,
    input logic [BUS_WIDTH-1:0] m_axi_rdata,
    input logic [1:0] m_axi_rresp,
    input logic m_axi_rlast,
    output logic m_axi_awvalid,
    input logic m_axi_awready,
    output logic [31:0] m_axi_awaddr,
    output logic [3:0] m_axi_awcache,
    output logic [2:0] m_axi_awprot,
    output logic [1:0] m_axi_awlock,
    output logic [1:0] m_axi_awburst,
    output logic [7:0] m_axi_awlen,
    output logic [2:0] m_axi_awsize,
    output logic m_axi_wvalid,
    input logic m_axi_wready,
    output logic [BUS_WIDTH-1:0] m_axi_wdata,
    output logic [BUS_WIDTH/8-1:0] m_axi_wstrb,
    output logic m_axi_wlast,
    input logic m_axi_bvalid,
    output logic m_axi_bready,
    input logic [1:0] m_axi_bresp,
    output logic irq, npu_busy
);
    logic aw_pending,w_pending,read_pending;
    logic [AXIL_ADDR_WIDTH-1:0] aw_address,read_address;
    logic [31:0] write_data;
    logic [3:0] write_strobes;
    logic [63:0] rs1,rs2;
    logic command_valid,command_ready,core_busy;
    logic [6:0] command_funct;
    logic load_busy,execute_busy,store_busy,dwconv_active,loop_dwconv_busy;
    logic im2col_active,im2col_request_valid,im2col_request_ready;
    logic im2col_response_valid,im2col_response_ready;
    logic core_arvalid,core_arready,core_awvalid,core_awready,core_rready,core_bready;
    logic [2:0] core_arid,core_awid;
    logic [2:0] read_ids[32],write_ids[32];
    logic [4:0] read_head,read_tail,write_head,write_tail;
    logic [5:0] read_count,write_count;
    logic [3:0] reset_cycles;
    logic core_clock_enable;
    wire core_clock=clk && (!IDLE_CLOCK_GATING || core_clock_enable);
    wire read_push=m_axi_arvalid && m_axi_arready;
    wire read_pop=m_axi_rvalid && m_axi_rready && m_axi_rlast;
    wire write_push=m_axi_awvalid && m_axi_awready;
    wire write_pop=m_axi_bvalid && m_axi_bready;
    wire submit=aw_pending && w_pending && aw_address[7:0]==8'h14;
    wire reset_write=aw_pending && w_pending && aw_address[7:0]==8'h28 && write_data[0];
    wire write_commit=aw_pending && w_pending && !s_axil_bvalid &&
                      (!submit || command_ready) && (!reset_write || reset_cycles==1);
    wire drained=!core_busy && read_count==0 && write_count==0 && !command_valid && reset_cycles==0;
    assign command_valid=submit && !s_axil_bvalid;
    assign command_funct=write_data[6:0];
    assign s_axil_awready=!aw_pending && !s_axil_bvalid;
    assign s_axil_wready=!w_pending && !s_axil_bvalid;
    assign s_axil_arready=!read_pending && !s_axil_rvalid;
    assign npu_busy=!drained;
    assign irq=1'b0;
    assign s_axil_bresp=2'b00;
    assign s_axil_rresp=2'b00;
    assign m_axi_arvalid=core_arvalid && read_count<32;
    assign core_arready=m_axi_arready && read_count<32;
    assign m_axi_awvalid=core_awvalid && write_count<32;
    assign core_awready=m_axi_awready && write_count<32;
    assign m_axi_rready=core_rready && read_count!=0;
    assign m_axi_bready=core_bready && write_count!=0;
    assign m_axi_arlock=2'b00;
    assign m_axi_awlock=2'b00;
    initial if (BUS_WIDTH!=64 || DMA_MAX_BYTES!=256*(BUS_WIDTH/8))
        $fatal(1,"Gemmini requires AXI64 with the AXI4 burst length limit");
    // Sample the enable while the source clock is low. A newly captured
    // command enables the following rising edge, before its ready handshake.
    always_ff @(negedge clk or negedge rst_n) begin
        if (!rst_n) core_clock_enable<=1'b1;
        else core_clock_enable<=core_busy || load_busy || execute_busy || store_busy ||
                                loop_dwconv_busy || command_valid || read_count!=0 ||
                                write_count!=0 || reset_cycles!=0;
    end
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            aw_pending<=0;w_pending<=0;read_pending<=0;
            aw_address<=0;read_address<=0;write_data<=0;write_strobes<=0;
            rs1<=0;rs2<=0;s_axil_bvalid<=0;s_axil_rvalid<=0;s_axil_rdata<=0;
            read_head<=0;read_tail<=0;write_head<=0;write_tail<=0;
            read_count<=0;write_count<=0;reset_cycles<=0;
        end else begin
            if (reset_cycles!=0) reset_cycles<=reset_cycles-1'b1;
            else if (reset_write && drained) reset_cycles<=8;
            if (s_axil_awvalid && s_axil_awready) begin
                aw_pending<=1;aw_address<=s_axil_awaddr;
            end
            if (s_axil_wvalid && s_axil_wready) begin
                w_pending<=1;write_data<=s_axil_wdata;write_strobes<=s_axil_wstrb;
            end
            if (s_axil_bvalid && s_axil_bready) s_axil_bvalid<=0;
            if (write_commit) begin
                aw_pending<=0;w_pending<=0;s_axil_bvalid<=1;
                for (int i=0;i<4;i++) if (write_strobes[i]) begin
                    case (aw_address[7:0])
                        8'h04:rs1[i*8+:8]<=write_data[i*8+:8];
                        8'h08:rs1[32+i*8+:8]<=write_data[i*8+:8];
                        8'h0c:rs2[i*8+:8]<=write_data[i*8+:8];
                        8'h10:rs2[32+i*8+:8]<=write_data[i*8+:8];
                        default:begin end
                    endcase
                end
            end
            if (s_axil_arvalid && s_axil_arready) begin
                read_pending<=1;read_address<=s_axil_araddr;
            end
            if (s_axil_rvalid && s_axil_rready) s_axil_rvalid<=0;
            if (read_pending && !s_axil_rvalid && (read_address[7:0]!=8'h18 || drained)) begin
                read_pending<=0;s_axil_rvalid<=1;
                case (read_address[7:0])
                    8'h00:s_axil_rdata<={30'd0,npu_busy,command_ready};
                    8'h04:s_axil_rdata<=rs1[31:0];
                    8'h08:s_axil_rdata<=rs1[63:32];
                    8'h0c:s_axil_rdata<=rs2[31:0];
                    8'h10:s_axil_rdata<=rs2[63:32];
                    8'h20:s_axil_rdata<=32'h474d0003;
                    8'h24:s_axil_rdata<=DMA_MAX_BYTES;
                    default:s_axil_rdata<=0;
                endcase
            end
            case ({read_push,read_pop})
                2'b10:read_count<=read_count+1'b1;
                2'b01:read_count<=read_count-1'b1;
                default:begin end
            endcase
            case ({write_push,write_pop})
                2'b10:write_count<=write_count+1'b1;
                2'b01:write_count<=write_count-1'b1;
                default:begin end
            endcase
            if (read_push) begin
                read_ids[read_tail]<=core_arid;read_tail<=read_tail+1'b1;
                assert(((32'(m_axi_arlen)+1)<<m_axi_arsize)<=DMA_MAX_BYTES)
                    else $fatal(1,"Gemmini read exceeds the AXI burst length limit");
            end
            if (read_pop) read_head<=read_head+1'b1;
            if (write_push) begin
                write_ids[write_tail]<=core_awid;write_tail<=write_tail+1'b1;
                assert(((32'(m_axi_awlen)+1)<<m_axi_awsize)<=DMA_MAX_BYTES)
                    else $fatal(1,"Gemmini write exceeds the AXI burst length limit");
            end
            if (write_pop) write_head<=write_head+1'b1;
        end
    end
    GemminiCompare u_gemmini (
        .clock(core_clock),.reset(!rst_n || reset_cycles!=0),.command_valid,.command_ready,.command_funct,
        .command_rs1(rs1),.command_rs2(rs2),.busy(core_busy),
        .load_busy,.execute_busy,.store_busy,.dwconv_active,.loop_dwconv_busy,
        .im2col_active,.im2col_request_valid,.im2col_request_ready,
        .im2col_response_valid,.im2col_response_ready,
        .mem_ar_valid(core_arvalid),.mem_ar_ready(core_arready),.mem_ar_bits_id(core_arid),
        .mem_ar_bits_addr(m_axi_araddr),.mem_ar_bits_len(m_axi_arlen),
        .mem_ar_bits_size(m_axi_arsize),.mem_ar_bits_burst(m_axi_arburst),
        .mem_ar_bits_cache(m_axi_arcache),.mem_ar_bits_prot(m_axi_arprot),
        .mem_ar_bits_lock(),.mem_ar_bits_qos(),
        .mem_r_valid(m_axi_rvalid && read_count!=0),.mem_r_ready(core_rready),
        .mem_r_bits_id(read_ids[read_head]),.mem_r_bits_data(m_axi_rdata),
        .mem_r_bits_resp(m_axi_rresp),.mem_r_bits_last(m_axi_rlast),
        .mem_aw_valid(core_awvalid),.mem_aw_ready(core_awready),.mem_aw_bits_id(core_awid),
        .mem_aw_bits_addr(m_axi_awaddr),.mem_aw_bits_len(m_axi_awlen),
        .mem_aw_bits_size(m_axi_awsize),.mem_aw_bits_burst(m_axi_awburst),
        .mem_aw_bits_cache(m_axi_awcache),.mem_aw_bits_prot(m_axi_awprot),
        .mem_aw_bits_lock(),.mem_aw_bits_qos(),
        .mem_w_valid(m_axi_wvalid),.mem_w_ready(m_axi_wready),.mem_w_bits_data(m_axi_wdata),
        .mem_w_bits_strb(m_axi_wstrb),.mem_w_bits_last(m_axi_wlast),
        .mem_b_valid(m_axi_bvalid && write_count!=0),.mem_b_ready(core_bready),
        .mem_b_bits_id(write_ids[write_head]),.mem_b_bits_resp(m_axi_bresp)
    );
endmodule
