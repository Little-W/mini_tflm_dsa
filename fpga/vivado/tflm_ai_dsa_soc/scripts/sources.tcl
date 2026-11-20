set flow_dir [file dirname [file normalize [info script]]]
source [file join $flow_dir npu_config.tcl]
if {[file isfile [file join $flow_dir export_sources.tcl]]} {
    source [file join $flow_dir export_sources.tcl]
} else {
    set project_export_dir [file normalize [file join $flow_dir ..]]
    set dsa_root [file normalize [file join $project_export_dir .. .. ..]]

    set ai_root $dsa_root
    set soc_root [file join $dsa_root rtl]
    set pico_root [file join $dsa_root picorv32]
    if {[info exists ::env(PICORV32_ROOT)] && $::env(PICORV32_ROOT) ne ""} {
        set pico_root [file normalize $::env(PICORV32_ROOT)]
    }
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
        [file join $npu_root ps_compact] \
    ]

    set design_sources [list \
        [file join $npu_root conv conv_im2col_pkg.sv] \
        [file join $npu_root conv vector_engine_pkg.sv] \
        [file join $npu_root conv vector_pe.sv] \
        [file join $npu_root conv vector_softmax.sv] \
        [file join $npu_root conv vector_config_check.sv] \
        [file join $npu_root conv vector_writeback.sv] \
        [file join $npu_root conv vector_round_shift.sv] \
        [file join $npu_root conv vector_scalar_multiplier.sv] \
        [file join $npu_root conv vector_quant_params.sv] \
        [file join $npu_root conv vector_engine.sv] \
        [file join $npu_root conv conv_axi_read_guard.sv] \
        [file join $npu_root conv conv_axi_read_mux.sv] \
        [file join $npu_root conv conv_axi_span_reader.sv] \
        [file join $npu_root conv conv_ia_tile_path.sv] \
        [file join $npu_root conv conv_ia_write_adapter.sv] \
        [file join $npu_root dma conv_window_queue.sv] \
        [file join $npu_root conv conv_im2col_frontend.sv] \
        [file join $npu_root dma cache conv_next_use_predictor.sv] \
        [file join $npu_root dma cache conv_read_cache.sv] \
        [file join $npu_root dma cache conv_sdp_ram.sv] \
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
        [file join $npu_compute_root select_add.sv] \
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
        [file join $npu_control_root ps_window_scheduler.sv] \
        [file join $npu_control_root ps_capacity_limits.sv] \
        [file join $npu_top_root frame_address_prepare.sv] \
        [file join $npu_top_root npu_top.sv] \
        [file join $npu_writeback_root oa_writer.sv] \
        [file join $npu_root ps_compact ps_adaptive_codec.sv] \
        [file join $npu_root ps_compact ps_frame_store.sv] \
        [file join $npu_root dma operand_read_cache.sv] \
        [file join $npu_buffers_root ia_ps_shared_ram.sv] \
        [file join $npu_buffers_root ps_buffer.sv] \
        [file join $npu_buffers_root ps_buffer_fifo.sv] \
        [file join $common_root pseudo_dual_port_ram.v] \
        [file join $common_root regfile.v] \
        [file join $common_root add_equal.sv] \
        [file join $common_root add3_equal.sv] \
        [file join $common_root onehot_check.sv] \
        [file join $npu_compute_root shift_accumulator.sv] \
        [file join $npu_writeback_root requant_compute_lane.sv] \
        [file join $npu_writeback_root requant_group_buffer.sv] \
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

}

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

# 公共存储封装沿用 .v 文件名，并显式采用 SystemVerilog 解析。
proc set_common_systemverilog {files} {
    foreach source $files {
        if {[file tail $source] in {regfile.v pseudo_dual_port_ram.v}} {
            set_property file_type SystemVerilog [get_files $source]
        }
    }
}

require_files $design_sources "RTL"
require_files $constraint_files "constraint"
