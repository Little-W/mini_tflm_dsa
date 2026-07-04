# Run a minimal behavioral simulation for an exported FPGA project.
#
# Usage:
#   vivado -mode batch -source fpga/vivado/tflm_ai_dsa_soc/scripts/run_behav_smoke.tcl \
#       -tclargs vivado_export/<export_name>/project/tflm_ai_dsa_soc.xpr \
#       vivado_export/<export_name>/mem/cpu.mem

if {[llength $argv] < 1} {
    error "Usage: run_behav_smoke.tcl <project.xpr> ?cpu.mem? ?SIZE? ?IA_CACHE_BLOCKS? ?CPU_MEM_DP? ?MAX_SYS_CYCLES? ?WEIGHT_WIDTH? ?DATA_WIDTH? ?NPU_ENABLE_IS_MODE? ?NPU_ENABLE_PER_CHANNEL? ?NPU_ADDR_WIDTH?"
}

set script_dir [file dirname [file normalize [info script]]]
set project_xpr [file normalize [lindex $argv 0]]
set repo_tb_file [file normalize [file join $script_dir .. sim fpga_top_behav_smoke_tb.sv]]

if {![file exists $project_xpr]} {
    error "Vivado project not found: $project_xpr"
}
if {![file exists $repo_tb_file]} {
    error "Behavioral smoke testbench not found: $repo_tb_file"
}

set project_root [file dirname [file dirname $project_xpr]]
set tb_file [file normalize [file join $project_root src sim fpga_top_behav_smoke_tb.sv]]
if {[file exists [file dirname $tb_file]]} {
    file copy -force $repo_tb_file $tb_file
} else {
    set tb_file [file normalize [file join $project_root sim fpga_top_behav_smoke_tb.sv]]
    if {[file exists [file dirname $tb_file]]} {
        file copy -force $repo_tb_file $tb_file
    } else {
        set tb_file $repo_tb_file
    }
}
set mem_path [file normalize [file join $project_root mem cpu.mem]]
if {[llength $argv] >= 2} {
    set mem_path [file normalize [lindex $argv 1]]
}
if {![file exists $mem_path]} {
    error "CPU memory image not found: $mem_path"
}

set size_value 16
set ia_cache_blocks_value 4
set cpu_mem_dp_value 65536
set max_sys_cycles_value 2000000
set weight_width_value 16
set data_width_value 16
set npu_enable_is_mode_value 1
set npu_enable_per_channel_value 1
set npu_addr_width_value 32
if {[llength $argv] >= 3} { set size_value [lindex $argv 2] }
if {[llength $argv] >= 4} { set ia_cache_blocks_value [lindex $argv 3] }
if {[llength $argv] >= 5} { set cpu_mem_dp_value [lindex $argv 4] }
if {[llength $argv] >= 6} { set max_sys_cycles_value [lindex $argv 5] }
if {[llength $argv] >= 7} { set weight_width_value [lindex $argv 6] }
if {[llength $argv] >= 8} { set data_width_value [lindex $argv 7] }
if {[llength $argv] >= 9} { set npu_enable_is_mode_value [lindex $argv 8] }
if {[llength $argv] >= 10} { set npu_enable_per_channel_value [lindex $argv 9] }
if {[llength $argv] >= 11} { set npu_addr_width_value [lindex $argv 10] }
open_project $project_xpr

if {[llength [get_files -quiet -of_objects [get_filesets sim_1] $tb_file]] == 0} {
    add_files -norecurse -fileset sim_1 $tb_file
}

set mem_path_escaped [string map [list "\\" "\\\\" "\"" "\\\""] $mem_path]
set tb_generics [list \
    WEIGHT_WIDTH=$weight_width_value \
    DATA_WIDTH=$data_width_value \
    SIZE=$size_value \
    IA_CACHE_BLOCKS=$ia_cache_blocks_value \
    CPU_MEM_DP=$cpu_mem_dp_value \
    CPU_ENABLE_ICACHE=1 \
    CPU_AXI_WRITE_TIMING_BUFFER=1 \
    BYPASS_RAM_PINGPONG=0 \
    RAM_WRITE_TIMING_BUFFER=1 \
    NPU_ADDR_WIDTH=$npu_addr_width_value \
    NPU_ENABLE_IS_MODE=$npu_enable_is_mode_value \
    NPU_ENABLE_PER_CHANNEL=$npu_enable_per_channel_value \
    MAX_SYS_CYCLES=$max_sys_cycles_value \
]
lappend tb_generics "CPU_MEM_PATH=\"$mem_path_escaped\""

set_property top fpga_top_behav_smoke_tb [get_filesets sim_1]
set_property generic $tb_generics [get_filesets sim_1]
set_property xsim.simulate.runtime all [get_filesets sim_1]
update_compile_order -fileset sim_1

launch_simulation -mode behavioral
run all
close_sim
close_project
