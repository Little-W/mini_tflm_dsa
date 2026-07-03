set flow_dir [file dirname [file normalize [info script]]]
set project_export_dir [file normalize [file join $flow_dir ..]]
set dsa_root [file normalize [file join $project_export_dir .. .. ..]]

if {[info exists ::env(AIENGINE_ROOT)] && $::env(AIENGINE_ROOT) ne ""} {
    set ai_root [file normalize $::env(AIENGINE_ROOT)]
} else {
    set ai_root [file normalize "/media/proj_tmp/aiEngine_integrated"]
}

set soc_root [file join $ai_root rtl axi_accelerator]
set pico_root [file join $ai_root picorv32]

set include_dirs [list \
    [file join $dsa_root inc] \
]

set design_sources [list \
    [file join $project_export_dir rtl fpga_top.sv] \
    [file join $project_export_dir rtl clk_wiz_0_sim_stub.sv] \
    [file join $pico_root picorv32.v] \
    [file join $pico_root picosoc simpleuart.v] \
    [file join $soc_root axil_reg_if_wr.v] \
    [file join $soc_root axil_reg_if_rd.v] \
    [file join $soc_root axil_reg_if.v] \
    [file join $soc_root csr_unit.v] \
    [file join $soc_root wb_pingpong_buf.v] \
    [file join $soc_root wbu.v] \
    [file join $soc_root axi_top mma_axil_top.sv] \
    [file join $dsa_root sub_modules accumulator_array.sv] \
    [file join $dsa_root sub_modules axi_block_dma_arbiter.sv] \
    [file join $dsa_root sub_modules axi_dual_block_dma.sv] \
    [file join $dsa_root sub_modules bias_loader.sv] \
    [file join $dsa_root sub_modules bias_loader_buffer.sv] \
    [file join $dsa_root sub_modules bias_loader_ctrl.sv] \
    [file join $dsa_root sub_modules bias_mux.sv] \
    [file join $dsa_root sub_modules compute_core.sv] \
    [file join $dsa_root sub_modules data_setup.sv] \
    [file join $dsa_root sub_modules de_diagonalizer.sv] \
    [file join $dsa_root sub_modules ia_buffer_wrapper.sv] \
    [file join $dsa_root sub_modules ia_loader.sv] \
    [file join $dsa_root sub_modules ia_loader_cache_mgr.sv] \
    [file join $dsa_root sub_modules ia_loader_ctrl.sv] \
    [file join $dsa_root sub_modules kernel_loader.sv] \
    [file join $dsa_root sub_modules kernel_loader_buffer.sv] \
    [file join $dsa_root sub_modules kernel_loader_ctrl.sv] \
    [file join $dsa_root sub_modules mma_controller.sv] \
    [file join $dsa_root top mma_top.sv] \
    [file join $dsa_root sub_modules oa_writer.sv] \
    [file join $dsa_root sub_modules ps_buffer.sv] \
    [file join $dsa_root sub_modules ps_buffer_fifo.sv] \
    [file join $dsa_root basic pseudo_dual_port_ram.v] \
    [file join $dsa_root basic shift_accumulator.sv] \
    [file join $dsa_root sub_modules vec_requant.sv] \
    [file join $dsa_root sub_modules vec_s8_to_fifo.sv] \
    [file join $dsa_root sub_modules ws_systolic_array.sv] \
    [file join $dsa_root basic ws_systolic_cell.sv] \
    [file join $soc_root soc pico_native_to_axi.sv] \
    [file join $soc_root soc soc_axi_interconnect.sv] \
    [file join $soc_root soc soc_axi_pingpong_buffer.sv] \
    [file join $soc_root soc soc_axi_ram.sv] \
    [file join $soc_root soc soc_axil_ctrl.sv] \
    [file join $soc_root soc soc_axil_simpleuart.sv] \
    [file join $soc_root soc_top.sv] \
]

set timing_constraint_files [list \
    [file join $project_export_dir constraints fpga_top_timing.xdc] \
]

set implementation_constraint_files [list \
    [file join $project_export_dir constraints alkaid_soc_fpga_top.xdc] \
]

set constraint_files [concat $timing_constraint_files $implementation_constraint_files]

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
