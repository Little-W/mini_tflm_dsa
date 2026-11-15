module tb_requant_rne (
    input logic clk, rst_n, init_cfg, in_valid,
    input logic signed [31:0] multiplier, shift, offset,
    input logic signed [31:0] input_s32[4],
    input logic signed [63:0] input_s64[4],
    output logic valid_full, valid_tensor, valid_s16,
    output logic signed [7:0] output_full[4], output_tensor[4],
    output logic signed [15:0] output_s16[4]
);
    logic signed [31:0] multipliers[4], shifts[4];
    for (genvar i=0;i<4;i++) begin
        assign multipliers[i]=multiplier;
        assign shifts[i]=(shift > 32'sd15) ? 32'sd15 : shift;
    end
    for (genvar variant=0;variant<2;variant++) begin : g_variant
        wire valid;
        wire signed [7:0] result[4];
        vec_requant #(.VLEN(4), .MAX_IA_REUSE(1),
            .ENABLE_PER_CHANNEL(variant), .ENABLE_IS_MODE(variant)) u_quant (
            .clk, .rst_n, .init_cfg, .cfg_per_channel(1'b0), .cfg_dataflow_mode(1'b0),
            .activation_min_in(-32'sd128), .activation_max_in(32'sd127),
            .dst_offset_in(offset), .multiplier_in(multiplier), .shift_in(shift),
            .k(32'd1), .m(32'd4), .ia_reuse_num_in(32'd1),
            .load_quant_req(), .load_quant_granted(1'b1), .quant_params_valid(),
            .dma_start(), .dma_is_write(), .dma_linear_read_mode(),
            .dma_base_addr(), .dma_row_stride(), .dma_rows_to_read(),
            .dma_burst_len_m1(), .dma_slot_id(), .dma_use_16bits(), .dma_lhs_zp(),
            .dma_raw_data(32'd0), .dma_raw_valid(1'b0),
            .in_valid, .in_tile_done(in_valid), .in_vec_s32(input_s32),
            .out_valid(valid), .out_tile_done(), .out_vec_s8(result),
            .quant_multiplier_lane(), .quant_shift_lane());
        if (variant==0) begin
            assign valid_tensor=valid;
            assign output_tensor=result;
        end else begin
            assign valid_full=valid;
            assign output_full=result;
        end
    end
    vec_requant_s64 #(.VLEN(4)) u_s16 (
        .clk,.rst_n,.init_cfg,.activation_min_in(-32'sd32768),
        .activation_max_in(32'sd32767),.multiplier_in(multipliers),.shift_in(shifts),
        .in_valid,.in_tile_done(in_valid),.in_vec_s64(input_s64),
        .out_valid(valid_s16),.out_tile_done(),.out_vec_s16(output_s16));
endmodule
