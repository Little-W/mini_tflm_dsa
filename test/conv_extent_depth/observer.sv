`timescale 1ns/1ps

// 在实际配置消费周期核对张量大小、地址范围和配置错误状态。
module conv_extent_observer;
    logic [63:0] expected_rhs;
    logic [47:0] expected_input, expected_kernel;
    logic [32:0] expected_range[4];
    logic expected_input_invalid, expected_rhs_invalid, expected_parameter_invalid;
    logic expected_dimension_invalid, expected_validation_invalid;
    wire [32:0] expected_rhs_end = {1'b0, 32'(npu_top.rhs_base)} + {1'b0, expected_rhs[31:0]};
    wire [32:0] expected_input_end = {1'b0, npu_top.conv_cfg_q.input_base} + {1'b0, expected_input[31:0]};
    wire [31:0] expected_parameter_bytes = {30'(npu_top.m),2'b00};
    wire [32:0] expected_bias_end = {1'b0,32'(npu_top.bias_base)} + {1'b0,expected_parameter_bytes};
    wire [32:0] expected_mult_end = {1'b0,32'(npu_top.q_mult_pt)} + {1'b0,expected_parameter_bytes};
    wire [32:0] expected_shift_end = {1'b0,32'(npu_top.q_shift_pt)} + {1'b0,expected_parameter_bytes};
    integer checked_cycles=0, dma_initializations=0;

    always @(posedge npu_top.clk) begin
        if (npu_top.core_rst_n && npu_top.cfg_stage2_valid) begin
            case (npu_top.cfg_capacity_phase)
                3'd0: begin
                    expected_rhs <= (npu_top.rhs_product_diagonal +
                        (64'(npu_top.rhs_product_cross) << 16)) <<
                        (npu_top.run_rhs_tile_packed ? (2*npu_top.SIZE_SHIFT) : 0);
                    expected_input <= 48'(npu_top.conv_input_low) + (48'(npu_top.conv_input_high) << 16);
                    expected_kernel <= 48'(npu_top.conv_kernel_low) + (48'(npu_top.conv_kernel_high) << 16);
                end
                3'd1: begin
                    expected_range[0] <= expected_rhs_end ^ {expected_rhs[32],32'd0};
                    expected_range[1] <= expected_bias_end ^ {npu_top.m[30],32'd0};
                    expected_range[2] <= expected_mult_end ^ {npu_top.m[30],32'd0};
                    expected_range[3] <= expected_shift_end ^ {npu_top.m[30],32'd0};
                    expected_input_invalid <= (|expected_input[47:32]) || expected_input_end[32];
                    expected_rhs_invalid <= (|expected_rhs[63:32]) || expected_rhs_end[32];
                    expected_parameter_invalid <= (|(32'(npu_top.m) >> 30)) ||
                        expected_bias_end[32] || (npu_top.use_per_channel &&
                        (expected_mult_end[32] || expected_shift_end[32]));
                    expected_dimension_invalid <= 64'(npu_top.conv_output_area)!=64'(npu_top.k) ||
                        64'(expected_kernel)!=64'(npu_top.n);
                end
                3'd2: expected_validation_invalid <= npu_top.conv_syntax_invalid ||
                    expected_input_invalid || expected_rhs_invalid || expected_parameter_invalid ||
                    expected_dimension_invalid;
                default: ;
            endcase
            if (npu_top.cfg_capacity_phase>=3'd5) begin
                checked_cycles++;
                assert({npu_top.rhs_allocation_bytes,npu_top.conv_input_bytes,npu_top.conv_kernel_elements} ==
                       {expected_rhs,expected_input,expected_kernel})
                    else $fatal(1,"Tensor extent differs during configuration consumption");
                assert({npu_top.conv_input_range_invalid,npu_top.conv_rhs_range_invalid,
                        npu_top.conv_parameter_range_invalid,npu_top.conv_dimension_invalid,
                        npu_top.conv_validation_invalid} ==
                       {expected_input_invalid,expected_rhs_invalid,expected_parameter_invalid,
                        expected_dimension_invalid,expected_validation_invalid})
                    else $fatal(1,"Tensor validation differs during configuration consumption");
                for (integer index=0;index<4;index++)
                    assert(npu_top.conv_range_end[index]==expected_range[index])
                        else $fatal(1,"Tensor range differs during configuration consumption");
            end
        end
        if (npu_top.core_rst_n && npu_top.exec_dma_job_init && !npu_top.run_vector) begin
            dma_initializations++;
            for (integer index=0;index<4;index++)
                assert(npu_top.conv_range_end[index]==expected_range[index])
                    else $fatal(1,"Tensor range differs at DMA initialization");
        end
    end
    final begin
        if (checked_cycles>0)
            $display("CONV_EXTENT_PASS checked_cycles=%0d dma_initializations=%0d",checked_cycles,dma_initializations);
    end
endmodule

bind npu_top conv_extent_observer u_extent_observer();
