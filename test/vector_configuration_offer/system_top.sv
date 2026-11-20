// SPDX-License-Identifier: Apache-2.0
// 通过生产 NPU 接口运行矩阵和向量任务，观察配置期间的客户端请求。
module vector_offer_system_top (
    input logic clk,rst_n,start,done_ready,is_vector,offer_enable,
    input logic [31:0] config_words[40],
    output logic ready,done_valid,
    output logic [1:0] error,
    output logic [31:0] configuration_cycles,configuration_wait_cycles,
    output logic [31:0] ordinary_request_cycles,vector_request_cycles,
    output logic [3:0] ordinary_clients_seen,
    output logic m_axi_arvalid,input logic m_axi_arready,
    output logic [31:0] m_axi_araddr,output logic [7:0] m_axi_arlen,
    output logic [2:0] m_axi_arsize,output logic [1:0] m_axi_arburst,
    input logic m_axi_rvalid,output logic m_axi_rready,input logic [63:0] m_axi_rdata,
    input logic [1:0] m_axi_rresp,input logic m_axi_rlast,
    output logic m_axi_awvalid,input logic m_axi_awready,
    output logic [31:0] m_axi_awaddr,output logic [7:0] m_axi_awlen,
    output logic [2:0] m_axi_awsize,output logic [1:0] m_axi_awburst,
    output logic m_axi_wvalid,input logic m_axi_wready,output logic [63:0] m_axi_wdata,
    output logic [7:0] m_axi_wstrb,output logic m_axi_wlast,
    input logic m_axi_bvalid,output logic m_axi_bready,input logic [1:0] m_axi_bresp
);
    vector_engine_pkg::vector_engine_cfg_t cfg;
    always_comb begin
        cfg='0;
        cfg.op=4'(config_words[0]);cfg.vector_s16=config_words[0][8];cfg.length=config_words[1];
        cfg.input_base=config_words[2];cfg.rhs_base=config_words[3];cfg.output_base=config_words[4];
        cfg.bias_base=config_words[5];cfg.multiplier_base=config_words[6];cfg.shift_base=config_words[7];
        cfg.output_offset=$signed(config_words[8]);cfg.activation_min=$signed(config_words[9]);
        cfg.activation_max=$signed(config_words[10]);
        cfg.image.input_base=config_words[2];
        cfg.image.input_h=16'(config_words[11]);cfg.image.input_w=16'(config_words[12]);
        cfg.image.input_c=16'(config_words[13]);cfg.image.group_c=16'(config_words[13]);
        cfg.image.kernel_h=16'(config_words[14]);cfg.image.kernel_w=16'(config_words[15]);
        cfg.image.output_h=16'(config_words[16]);cfg.image.output_w=16'(config_words[17]);
        cfg.image.stride_h=16'(config_words[18]);cfg.image.stride_w=16'(config_words[19]);
        cfg.image.dilation_h=16'(config_words[20]);cfg.image.dilation_w=16'(config_words[21]);
        cfg.image.pad_top=16'(config_words[22]);cfg.image.pad_left=16'(config_words[23]);
        cfg.image.input_offset=16'(config_words[24]);cfg.image.bypass_cache=config_words[25][0];
        cfg.add.input1_offset=$signed(config_words[26]);cfg.add.input2_offset=$signed(config_words[27]);
        cfg.add.input1_multiplier=$signed(config_words[28]);cfg.add.input1_shift=$signed(config_words[29]);
        cfg.add.input2_multiplier=$signed(config_words[30]);cfg.add.input2_shift=$signed(config_words[31]);
        cfg.add.left_shift=$signed(config_words[32]);cfg.add.output_multiplier=$signed(config_words[33]);
        cfg.add.output_shift=$signed(config_words[34]);
    end
    npu_top #(.SIZE(16),.BUS_WIDTH(64),.SHARED_BANK_BYTES(8192),.SHARED_BANK_COUNT(7),
        .IA_CACHE_BLOCKS(4),.PS_FRAME_COUNT(16),.IM2COL_CACHE_BYTES(4096),.VECTOR_PE_COUNT(8),
        .AXI_READ_OUTSTANDING(4),.AXI_WRITE_OUTSTANDING(4),.p_fixed_ps_channels(1)) dut (
        .clk,.rst_n,.proof_offer_enable(offer_enable),.calc_start(start),.sa_ready(ready),
        .done_valid,.done_ready,.err_code(error),
        .cfg_operand_fetch64(1'b0),.cfg_lhs_tile_packed(1'b0),.cfg_rhs_tile_packed(1'b0),
        .cfg_conv_enable(1'b0),.cfg_conv('0),.cfg_vector_enable(is_vector),.cfg_vector(cfg),
        .cfg_16bits_ia(1'b0),.cfg_16x8(1'b0),.cfg_dataflow_mode(config_words[0][9]),
        .cfg_ia_reuse_num(config_words[36]),.cfg_w_reuse_num(config_words[37]),
        .cfg_row_groups({16'b0,config_words[38][15:0]}),
        .cfg_col_groups({16'b0,config_words[38][31:16]}),
        .cfg_row_tail_tiles({16'b0,config_words[39][15:0]}),
        .cfg_col_tail_tiles({16'b0,config_words[39][31:16]}),
        .cfg_ps_control(32'd1),.cfg_shared_ia_banks(32'd1),
        .lhs_base(config_words[2]),.rhs_base(config_words[3]),.dst_base(config_words[4]),
        .bias_base(config_words[5]),.lhs_zp(32'd0),.rhs_zp(32'd0),.dst_zp(config_words[8]),
        .q_mult_pt(config_words[6]),.q_shift_pt(config_words[7]),.use_per_channel(config_words[35][0]),
        .k(config_words[11]),.n(config_words[12]),.m(config_words[13]),
        .lhs_row_stride_b(config_words[12]),.rhs_col_stride_b(config_words[12]),
        .dst_row_stride_b(config_words[13]),.act_min(config_words[9]),.act_max(config_words[10]),
        .m_axi_arvalid,.m_axi_arready,.m_axi_araddr,.m_axi_arlen,.m_axi_arsize,.m_axi_arburst,
        .m_axi_rvalid,.m_axi_rready,.m_axi_rdata,.m_axi_rresp,.m_axi_rlast,
        .m_axi_awvalid,.m_axi_awready,.m_axi_awaddr,.m_axi_awlen,.m_axi_awsize,.m_axi_awburst,
        .m_axi_wvalid,.m_axi_wready,.m_axi_wdata,.m_axi_wstrb,.m_axi_wlast,
        .m_axi_bvalid,.m_axi_bready,.m_axi_bresp
    );
    wire configuring=dut.g_vector_engine.u_engine.state==6'd2;
    wire ordinary_request=dut.load_ia_req || dut.load_weight_req || dut.load_bias_req || dut.load_quant_req;
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            configuration_cycles<=0;configuration_wait_cycles<=0;
            ordinary_request_cycles<=0;vector_request_cycles<=0;
            ordinary_clients_seen<=0;
        end else begin
            ordinary_clients_seen<=ordinary_clients_seen |
                {dut.load_quant_req,dut.load_bias_req,dut.load_weight_req,dut.load_ia_req};
            if (ordinary_request) ordinary_request_cycles<=ordinary_request_cycles+1;
            if (dut.dw_rd_req || dut.win_req_valid) vector_request_cycles<=vector_request_cycles+1;
            if (dut.run_vector && dut.core_rst_n) assert(!ordinary_request);
            if (configuring && dut.core_rst_n) begin
                configuration_cycles<=configuration_cycles+1;
                if (!dut.conv_cfg_ready) configuration_wait_cycles<=configuration_wait_cycles+1;
                assert(dut.run_vector);
                assert(!ordinary_request);
                assert(!dut.dw_rd_req && !dut.dw_rd_start && !dut.win_req_valid);
                assert(!dut.ctrl_calc_start && !dut.exec_dma_job_init);
            end
        end
    end
endmodule
