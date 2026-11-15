set flow_dir [file dirname [file normalize [info script]]]
set project_export_dir [file normalize [file join $flow_dir ..]]
set dsa_root [file normalize [file join $project_export_dir .. .. ..]]

set ai_root $dsa_root
set soc_root [file join $dsa_root rtl]
set pico_root [file join $dsa_root picorv32]
set rtl_root [file join $dsa_root rtl]
set common_root [file join $rtl_root common]
set npu_root [file join $rtl_root npu]
set npu_top_root [file join $npu_root top]
set npu_control_root [file join $npu_root control]
set npu_dma_root [file join $npu_root dma]
set npu_loaders_root [file join $npu_root loaders]
set npu_compute_root [file join $npu_root compute]
set npu_buffers_root [file join $npu_root buffers]
set npu_writeback_root [file join $npu_root writeback]

set include_dirs [list \
    [file join $dsa_root include] \
    [file join $npu_root gempact] \
]

set design_sources [list \
    [file join $npu_root conv 00_conv_im2col_pkg.sv] \
    [file join $npu_root conv 01_vector_engine_pkg.sv] \
    [file join $npu_root conv vector_pe.sv] \
    [file join $npu_root conv vector_engine.sv] \
    [file join $npu_root conv conv_axi_read_guard.sv] \
    [file join $npu_root conv conv_axi_read_mux.sv] \
    [file join $npu_root conv conv_axi_span_reader.sv] \
    [file join $npu_root conv conv_ia_tile_path.sv] \
    [file join $npu_root conv conv_ia_write_adapter.sv] \
    [file join $npu_root conv conv_im2col_frontend.sv] \
    [file join $npu_root conv conv_next_use_predictor.sv] \
    [file join $npu_root conv conv_read_cache.sv] \
    [file join $npu_root conv conv_sdp_ram.sv] \
    [file join $npu_root conv conv_udiv32.sv] \
    [file join $project_export_dir rtl fpga_top.sv] \
    [file join $project_export_dir rtl clk_wiz_0_sim_stub.sv] \
    [file join $pico_root picorv32.v] \
    [file join $pico_root picosoc simpleuart.v] \
    [file join $soc_root axi_top npu_axil_reg_if.sv] \
    [file join $soc_root axi_top npu_axil_top.sv] \
    [file join $npu_compute_root accumulator_array.sv] \
    [file join $npu_dma_root axi_block_dma_arbiter.sv] \
    [file join $npu_dma_root axi_write_page_guard.sv] \
    [file join $npu_dma_root axi_dual_block_dma.sv] \
    [file join $npu_dma_root axi_linear_block_dma.sv] \
    [file join $npu_loaders_root bias_loader.sv] \
    [file join $npu_loaders_root bias_loader_buffer.sv] \
    [file join $npu_loaders_root bias_loader_ctrl.sv] \
    [file join $npu_compute_root bias_mux.sv] \
    [file join $npu_compute_root compute_core.sv] \
    [file join $npu_compute_root data_setup.sv] \
    [file join $npu_compute_root de_diagonalizer.sv] \
    [file join $npu_loaders_root ia_buffer_wrapper.sv] \
    [file join $npu_loaders_root ia_loader.sv] \
    [file join $npu_loaders_root ia_loader_cache_mgr.sv] \
    [file join $npu_loaders_root ia_loader_ctrl.sv] \
    [file join $npu_loaders_root kernel_loader.sv] \
    [file join $npu_loaders_root kernel_loader_buffer.sv] \
    [file join $npu_loaders_root kernel_loader_ctrl.sv] \
    [file join $npu_control_root npu_controller.sv] \
    [file join $npu_root gempact gempact_c_pack.sv] \
    [file join $npu_root gempact gempact_frame_array.sv] \
    [file join $npu_root gempact gempact_paged_ps.sv] \
    [file join $npu_root gempact gempact_panel_cache.sv] \
    [file join $npu_root gempact gempact_panel_engine.sv] \
    [file join $npu_root gempact gempact_ps_bank.sv] \
    [file join $npu_root gempact gempact_resident_engine.sv] \
    [file join $npu_root gempact gempact_stream_ps.sv] \
    [file join $npu_root gempact gempact_stream_ps_pcr.sv] \
    [file join $npu_root gempact gempact_tagged_array.sv] \
    [file join $npu_root gempact gempact_tile_core.sv] \
    [file join $npu_root gempact operand_read_cache.sv] \
    [file join $npu_root gempact ps_capacity_schedule.sv] \
    [file join $npu_root gempact ps_codec_measure.sv] \
    [file join $npu_root gempact ps_sector_store.sv] \
    [file join $npu_top_root npu_top.sv] \
    [file join $npu_writeback_root oa_writer.sv] \
    [file join $npu_buffers_root ps_buffer.sv] \
    [file join $npu_buffers_root ps_buffer_fifo.sv] \
    [file join $common_root pseudo_dual_port_ram.v] \
    [file join $npu_compute_root shift_accumulator.sv] \
    [file join $npu_writeback_root vec_requant.sv] \
    [file join $npu_writeback_root vec_requant_s64.sv] \
    [file join $npu_writeback_root vec_s16_to_fifo.sv] \
    [file join $npu_writeback_root vec_s8_to_fifo.sv] \
    [file join $npu_compute_root ws_systolic_array.sv] \
    [file join $npu_compute_root ws_systolic_cell.sv] \
    [file join $soc_root soc pico_native_to_axi.sv] \
    [file join $soc_root soc soc_axi_interconnect.sv] \
    [file join $soc_root soc soc_axi_pingpong_buffer.sv] \
    [file join $soc_root soc soc_axi_ram.sv] \
    [file join $soc_root soc soc_axil_ctrl.sv] \
    [file join $soc_root soc soc_axil_simpleuart.sv] \
    [file join $soc_root soc_top.sv] \
]

set constraint_files [list \
    [file join $project_export_dir constraints tflm_ai_dsa_soc.xdc] \
]

proc require_files {files label} {
    set missing [list]
    foreach f $files {
        if {![file exists $f]} {
            lappend missing $f
        }
    }
    if {[llength $missing] != 0} {
        puts "Missing $label files:"
        foreach f $missing {
            puts "  $f"
        }
        error "Cannot continue because $label files are missing."
    }
}

require_files $design_sources "RTL"
require_files $constraint_files "constraint"
