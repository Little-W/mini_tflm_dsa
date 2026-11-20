// SPDX-License-Identifier: Apache-2.0
module frame_address_npu_observer #(parameter int p_size = 16);
    localparam int p_shift = $clog2(p_size);
    logic pending = 0;
    integer age = 0;
    logic [31:0] expected_ia, expected_weight, expected_dst;
    longint unsigned accepted = 0, started = 0, cancelled = 0;
    longint unsigned ws_frames = 0, is_frames = 0, packed_frames = 0, wide_frames = 0;
    longint unsigned prepare_cycles = 0;

    function automatic logic [31:0] operand_address(
        input logic [31:0] base, row0, depth0, stride, total_depth,
        input logic tile_packed, element_s16
    );
        logic [31:0] depth_tiles, element_offset, offset;
        depth_tiles = (total_depth + 32'(p_size-1)) >> p_shift;
        element_offset = (((row0 >> p_shift)*depth_tiles + (depth0 >> p_shift)) << (2*p_shift)) +
                         ((row0 & 32'(p_size-1)) << p_shift);
        offset = tile_packed ? (element_offset << element_s16) : row0*stride + (depth0 << element_s16);
        return base + offset;
    endfunction

    always @(posedge npu_top.clk) begin
        if (!npu_top.core_rst_n || npu_top.abort_pending || npu_top.task_fault || npu_top.cfg_start_event) begin
            if (pending) cancelled <= cancelled + 1;
            pending <= 0;
            age <= 0;
        end else begin
            if (npu_top.frame_command_start) begin
                assert(!pending && !npu_top.frame_execution_started)
                    else $fatal(1,"Frame preparation accepted overlapping work");
                pending <= 1;
                age <= 1;
                accepted <= accepted + 1;
                expected_ia <= operand_address(npu_top.ia_base_eff,npu_top.frame_command_p0,npu_top.frame_command_q0,
                    npu_top.ia_stride_eff,npu_top.run_n,npu_top.is_mode ? npu_top.run_rhs_tile_packed : npu_top.run_lhs_tile_packed,
                    npu_top.ia_use_16bits_eff);
                expected_weight <= operand_address(npu_top.weight_base_eff,npu_top.frame_command_column,npu_top.frame_command_q0,
                    npu_top.weight_stride_eff,npu_top.run_n,npu_top.is_mode ? npu_top.run_lhs_tile_packed : npu_top.run_rhs_tile_packed,
                    npu_top.weight_use_16bits_eff);
                expected_dst <= npu_top.dst_base +
                    (npu_top.is_mode ? npu_top.frame_command_column : npu_top.frame_command_p0)*npu_top.dst_row_stride_b +
                    ((npu_top.is_mode ? npu_top.frame_command_p0 : npu_top.frame_command_column) << npu_top.run_16x8);
                if (npu_top.is_mode) is_frames <= is_frames + 1; else ws_frames <= ws_frames + 1;
                if (npu_top.run_lhs_tile_packed || npu_top.run_rhs_tile_packed) packed_frames <= packed_frames + 1;
                if (npu_top.run_use_16bits) wide_frames <= wide_frames + 1;
            end else if (pending) begin
                age <= age + 1;
                prepare_cycles <= prepare_cycles + 1;
            end
            if (npu_top.frame_execute_start) begin
                assert(pending && age == 11 && npu_top.frame_command_active)
                    else $fatal(1,"Frame execution timing differs age=%0d",age);
                assert(npu_top.exec_ia_base == expected_ia && npu_top.exec_weight_base == expected_weight &&
                       npu_top.exec_dst_base == expected_dst)
                    else $fatal(1,"Frame execution address differs");
                pending <= 0;
                started <= started + 1;
            end
            if (pending && !npu_top.frame_execute_start) begin
                assert(!npu_top.ctrl_calc_start && !npu_top.exec_oa_complete && !npu_top.weight_prefetch_valid)
                    else $fatal(1,"Frame execution began during address preparation");
            end
        end
    end
    final $display("FRAME_ADDRESS_NPU_PASS accepted=%0d started=%0d cancelled=%0d prepare_cycles=%0d ws_frames=%0d is_frames=%0d packed_frames=%0d wide_frames=%0d",
        accepted,started,cancelled,prepare_cycles,ws_frames,is_frames,packed_frames,wide_frames);
endmodule

bind npu_top frame_address_npu_observer #(.p_size(SIZE)) u_frame_address_observer();
