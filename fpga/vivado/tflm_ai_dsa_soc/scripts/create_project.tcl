# Create an openable Vivado project for the board-level TFLM AI DSA SoC.
#
# Usage:
#   vivado -mode batch -source fpga/vivado/tflm_ai_dsa_soc/scripts/create_project.tcl
#   vivado -mode batch -source fpga/vivado/tflm_ai_dsa_soc/scripts/create_project.tcl \
#       -tclargs build/vivado/tflm_ai_dsa_soc_custom xc7a200tfbg484-3 16 4
#
# Optional environment:
#   VIVADO_JOBS=8

set script_dir [file dirname [file normalize [info script]]]
source [file join $script_dir npu_config.tcl]
source [file join $script_dir cpu_memory.tcl]
set export_dir [file normalize [file join $script_dir ..]]
set dsa_root [npu_config::repository_root $script_dir]
set npu_hardware_config [npu_config::read $dsa_root]

set project_name tflm_ai_dsa_soc
set part_name xc7a200tfbg484-3
set size_value 16
set ia_cache_blocks_value 4
set cpu_mem_dp_value 65536
set cpu_mem_init_en_value 0
set cpu_mem_path_value ""
set core_clk_mhz_value 150.000
set cpu_axi_write_timing_buffer_value 1
set bypass_ram_pingpong_value 0
set ram_write_timing_buffer_value 1
set synth_strategy_value Flow_PerfOptimized_high
set synth_directive_value PerformanceOptimized
set impl_strategy_value Performance_Explore

if {[llength $argv] >= 1} {
    set project_dir [file normalize [lindex $argv 0]]
} else {
    set project_dir [file join $dsa_root build vivado $project_name]
}
if {[llength $argv] >= 2} { set part_name [lindex $argv 1] }
if {[llength $argv] >= 3} { set size_value [lindex $argv 2] }
if {[llength $argv] >= 4} { set ia_cache_blocks_value [lindex $argv 3] }
if {[llength $argv] >= 5} { set cpu_mem_dp_value [lindex $argv 4] }
if {[llength $argv] >= 6} { set cpu_mem_init_en_value [lindex $argv 5] }
if {[llength $argv] >= 7} { set cpu_mem_path_value [file normalize [lindex $argv 6]] }
if {[llength $argv] >= 8} { set core_clk_mhz_value [lindex $argv 7] }
if {[llength $argv] >= 9} { set cpu_axi_write_timing_buffer_value [lindex $argv 8] }
if {[llength $argv] >= 10} { set bypass_ram_pingpong_value [lindex $argv 9] }
if {[llength $argv] >= 11} { set ram_write_timing_buffer_value [lindex $argv 10] }
if {[info exists ::env(VIVADO_SYNTH_STRATEGY)] && $::env(VIVADO_SYNTH_STRATEGY) ne ""} {
    set synth_strategy_value $::env(VIVADO_SYNTH_STRATEGY)
}
if {[info exists ::env(VIVADO_SYNTH_DIRECTIVE)] && $::env(VIVADO_SYNTH_DIRECTIVE) ne ""} {
    set synth_directive_value $::env(VIVADO_SYNTH_DIRECTIVE)
}
if {[info exists ::env(VIVADO_IMPL_STRATEGY)] && $::env(VIVADO_IMPL_STRATEGY) ne ""} {
    set impl_strategy_value $::env(VIVADO_IMPL_STRATEGY)
}

source [file join $script_dir sources.tcl]
source [file join $script_dir clk_wiz_ip.tcl]

if {$cpu_mem_path_value ne ""} {
    set memory_images [cpu_memory::write_images $cpu_mem_path_value \
        [file join $project_dir mem cpu32.mem] [file join $project_dir mem cpu.mem] \
        $cpu_mem_dp_value [dict get $npu_hardware_config NPU_AXI_DATA_WIDTH]]
    set cpu_mem_path_value [dict get $memory_images native_path]
}

set top_generics [list \
    {*}[npu_config::generics $npu_hardware_config] \
    SIZE=$size_value \
    IA_CACHE_BLOCKS=$ia_cache_blocks_value \
    CPU_MEM_DP=$cpu_mem_dp_value \
    CPU_MEM_INIT_EN=$cpu_mem_init_en_value \
    CPU_AXI_WRITE_TIMING_BUFFER=$cpu_axi_write_timing_buffer_value \
    BYPASS_RAM_PINGPONG=$bypass_ram_pingpong_value \
    RAM_WRITE_TIMING_BUFFER=$ram_write_timing_buffer_value \
]
if {$cpu_mem_path_value ne ""} {
    set cpu_mem_path_escaped [string map [list "\\" "\\\\" "\"" "\\\""] $cpu_mem_path_value]
    lappend top_generics "CPU_MEM_PATH=\"$cpu_mem_path_escaped\""
}

create_project -force $project_name $project_dir -part $part_name

set_property target_language Verilog [current_project]
set_property simulator_language Mixed [current_project]

set vivado_jobs_value 1
if {[info exists ::env(VIVADO_JOBS)] && $::env(VIVADO_JOBS) ne ""} {
    set vivado_jobs_value $::env(VIVADO_JOBS)
}
set_param general.maxThreads $vivado_jobs_value

add_files -norecurse -fileset sources_1 $design_sources
add_files -norecurse -fileset constrs_1 $constraint_files

create_tflm_soc_clk_wiz $core_clk_mhz_value

set_property include_dirs $include_dirs [get_filesets sources_1]
set rtl_defines {SYNTHESIS=1 XILINX_CLK_WIZ_IP=1 XILINX_FPGA=1}
set ps_compress [dict get $npu_hardware_config PCR_ENGINE]
if {[info exists ::env(GEMPACT_PCR_ENGINE)] && $::env(GEMPACT_PCR_ENGINE) ne ""} {
    set ps_compress $::env(GEMPACT_PCR_ENGINE)
}
if {[info exists ::env(GEMPACT_PS_COMPRESS)] && $::env(GEMPACT_PS_COMPRESS) ne ""} {
    set ps_compress $::env(GEMPACT_PS_COMPRESS)
}
if {$ps_compress ni {0 1}} { error "GEMPACT_PS_COMPRESS must be 0 or 1" }
if {$ps_compress eq "1"} {
    if {$size_value != 16} { error "Shared PS compression requires SIZE=16" }
    lappend rtl_defines GEMPACT_PS_COMPRESS
    set pool_bytes [dict get $npu_hardware_config PS_POOL_BYTES]
    if {[info exists ::env(GEMPACT_PS_POOL_BYTES)] && $::env(GEMPACT_PS_POOL_BYTES) ne ""} {
        set pool_bytes $::env(GEMPACT_PS_POOL_BYTES)
    }
    if {![string is integer -strict $pool_bytes] || $pool_bytes < 64 || $pool_bytes % 64 != 0} {
        error "GEMPACT_PS_POOL_BYTES must be a positive multiple of 64"
    }
    lappend rtl_defines GEMMORA_PS_POOL_BYTES=$pool_bytes
    set ps_force_raw [dict get $npu_hardware_config PS_FORCE_RAW]
    if {[info exists ::env(GEMPACT_PS_FORCE_RAW)] && $::env(GEMPACT_PS_FORCE_RAW) ne ""} {
        set ps_force_raw $::env(GEMPACT_PS_FORCE_RAW)
    }
    if {$ps_force_raw ni {0 1}} { error "GEMPACT_PS_FORCE_RAW must be 0 or 1" }
    if {$ps_force_raw eq "1"} { lappend rtl_defines GEMMORA_PS_FORCE_RAW }
}
set_property verilog_define $rtl_defines [get_filesets sources_1]
set_property top fpga_top [get_filesets sources_1]
set_property generic $top_generics [get_filesets sources_1]

update_compile_order -fileset sources_1

set synth_run [get_runs synth_1]
set_property strategy $synth_strategy_value $synth_run
set_property STEPS.SYNTH_DESIGN.ARGS.DIRECTIVE $synth_directive_value $synth_run
set_property STEPS.SYNTH_DESIGN.ARGS.FLATTEN_HIERARCHY rebuilt $synth_run

set impl_run [get_runs impl_1]
set_property strategy $impl_strategy_value $impl_run

puts "Created project: [file join $project_dir ${project_name}.xpr]"
puts "Top: fpga_top"
puts "Part: $part_name"
puts "Board clock: 50.000 MHz"
puts "Core clock: $core_clk_mhz_value MHz"
puts "SIZE=$size_value IA_CACHE_BLOCKS=$ia_cache_blocks_value CPU_MEM_DP=$cpu_mem_dp_value CPU_AXI_WRITE_TIMING_BUFFER=$cpu_axi_write_timing_buffer_value BYPASS_RAM_PINGPONG=$bypass_ram_pingpong_value RAM_WRITE_TIMING_BUFFER=$ram_write_timing_buffer_value"
puts "SYNTH_STRATEGY=$synth_strategy_value SYNTH_DIRECTIVE=$synth_directive_value IMPL_STRATEGY=$impl_strategy_value"
puts "PROJECT_ROOT=$dsa_root"

puts "NPU_AXI_DATA_WIDTH=[dict get $npu_hardware_config NPU_AXI_DATA_WIDTH] SHARED_BANK_BYTES=[dict get $npu_hardware_config SHARED_BANK_BYTES] SHARED_BANK_COUNT=[dict get $npu_hardware_config SHARED_BANK_COUNT] IM2COL_CACHE_BYTES=[dict get $npu_hardware_config IM2COL_CACHE_BYTES]"
