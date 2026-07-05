# Run a minimal behavioral simulation for an exported FPGA project.
#
# Usage:
#   vivado -mode batch -source fpga/vivado/tflm_ai_dsa_soc/scripts/run_behav_smoke.tcl \
#       -tclargs vivado_export/<export_name>/project/tflm_ai_dsa_soc.xpr \
#       vivado_export/<export_name>/mem/cpu.mem

if {[llength $argv] < 1} {
    error "Usage: run_behav_smoke.tcl <project.xpr> ?cpu.mem? ?SIZE? ?IA_CACHE_BLOCKS? ?CPU_MEM_DP? ?MAX_SYS_CYCLES? ?WEIGHT_WIDTH? ?DATA_WIDTH? ?NPU_ENABLE_IS_MODE? ?NPU_ENABLE_PER_CHANNEL? ?NPU_ADDR_WIDTH? ?NPU_ENABLE_CLOCK_GATING?"
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

proc get_generic_value {generic_items name fallback} {
    foreach item $generic_items {
        set eq_pos [string first "=" $item]
        if {$eq_pos <= 0} {
            continue
        }
        set key [string range $item 0 [expr {$eq_pos - 1}]]
        if {$key eq $name} {
            return [string trim [string range $item [expr {$eq_pos + 1}] end] "\""]
        }
    }
    return $fallback
}

proc find_latest_sim_log {project_xpr} {
    set project_dir [file dirname $project_xpr]
    set project_name [file rootname [file tail $project_xpr]]
    set sim_root [file join $project_dir "${project_name}.sim" sim_1]
    set logs [list]
    foreach pattern [list \
        [file join $sim_root * xsim simulate.log] \
        [file join $sim_root * * xsim simulate.log] \
        [file join $sim_root * * * xsim simulate.log] \
    ] {
        foreach log [glob -nocomplain $pattern] {
            lappend logs $log
        }
    }
    if {[llength $logs] == 0} {
        error "Simulation log not found under $sim_root"
    }

    set latest [lindex $logs 0]
    foreach log $logs {
        if {[file mtime $log] > [file mtime $latest]} {
            set latest $log
        }
    }
    return $latest
}

proc check_smoke_log {project_xpr pass_tag fail_prefix} {
    set log [find_latest_sim_log $project_xpr]
    set f [open $log r]
    set text [read $f]
    close $f

    if {[string first "\[$fail_prefix\] FAIL" $text] >= 0 ||
        [string first "\[$fail_prefix\] TIMEOUT" $text] >= 0 ||
        [string first "Fatal:" $text] >= 0} {
        error [format {Simulation failed; see %s} $log]
    }
    if {[string first $pass_tag $text] < 0} {
        error [format {Simulation PASS tag not found (%s); see %s} $pass_tag $log]
    }
    puts [format {SMOKE PASS: found "%s" in %s} $pass_tag $log]
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
set max_sys_cycles_value 10000000
set weight_width_value 16
set data_width_value 16
set cpu_enable_icache_value 1
set cpu_axi_write_timing_buffer_value 1
set bypass_ram_pingpong_value 0
set ram_write_timing_buffer_value 1
set npu_enable_is_mode_value 1
set npu_enable_per_channel_value 1
set npu_addr_width_value 32
set npu_enable_clock_gating_value 1
if {[llength $argv] >= 3} { set size_value [lindex $argv 2] }
if {[llength $argv] >= 4} { set ia_cache_blocks_value [lindex $argv 3] }
if {[llength $argv] >= 5} { set cpu_mem_dp_value [lindex $argv 4] }
if {[llength $argv] >= 6} { set max_sys_cycles_value [lindex $argv 5] }
if {[llength $argv] >= 7} { set weight_width_value [lindex $argv 6] }
if {[llength $argv] >= 8} { set data_width_value [lindex $argv 7] }
if {[llength $argv] >= 9} { set npu_enable_is_mode_value [lindex $argv 8] }
if {[llength $argv] >= 10} { set npu_enable_per_channel_value [lindex $argv 9] }
if {[llength $argv] >= 11} { set npu_addr_width_value [lindex $argv 10] }
if {[llength $argv] >= 12} { set npu_enable_clock_gating_value [lindex $argv 11] }
open_project $project_xpr

set source_generics [get_property generic [get_filesets sources_1]]
set sim_generics [get_property generic [get_filesets sim_1]]
if {[llength $argv] < 3} { set size_value [get_generic_value $source_generics SIZE $size_value] }
if {[llength $argv] < 4} { set ia_cache_blocks_value [get_generic_value $source_generics IA_CACHE_BLOCKS $ia_cache_blocks_value] }
if {[llength $argv] < 5} { set cpu_mem_dp_value [get_generic_value $source_generics CPU_MEM_DP $cpu_mem_dp_value] }
if {[llength $argv] < 6} { set max_sys_cycles_value [get_generic_value $sim_generics MAX_SYS_CYCLES $max_sys_cycles_value] }
if {[llength $argv] < 7} { set weight_width_value [get_generic_value $source_generics WEIGHT_WIDTH $weight_width_value] }
if {[llength $argv] < 8} { set data_width_value [get_generic_value $source_generics DATA_WIDTH $data_width_value] }
if {[llength $argv] < 9} { set npu_enable_is_mode_value [get_generic_value $source_generics NPU_ENABLE_IS_MODE $npu_enable_is_mode_value] }
if {[llength $argv] < 10} { set npu_enable_per_channel_value [get_generic_value $source_generics NPU_ENABLE_PER_CHANNEL $npu_enable_per_channel_value] }
if {[llength $argv] < 11} { set npu_addr_width_value [get_generic_value $source_generics NPU_ADDR_WIDTH $npu_addr_width_value] }
if {[llength $argv] < 12} { set npu_enable_clock_gating_value [get_generic_value $source_generics NPU_ENABLE_CLOCK_GATING $npu_enable_clock_gating_value] }
set cpu_enable_icache_value [get_generic_value $source_generics CPU_ENABLE_ICACHE $cpu_enable_icache_value]
set cpu_axi_write_timing_buffer_value [get_generic_value $source_generics CPU_AXI_WRITE_TIMING_BUFFER $cpu_axi_write_timing_buffer_value]
set bypass_ram_pingpong_value [get_generic_value $source_generics BYPASS_RAM_PINGPONG $bypass_ram_pingpong_value]
set ram_write_timing_buffer_value [get_generic_value $source_generics RAM_WRITE_TIMING_BUFFER $ram_write_timing_buffer_value]

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
    CPU_ENABLE_ICACHE=$cpu_enable_icache_value \
    CPU_AXI_WRITE_TIMING_BUFFER=$cpu_axi_write_timing_buffer_value \
    BYPASS_RAM_PINGPONG=$bypass_ram_pingpong_value \
    RAM_WRITE_TIMING_BUFFER=$ram_write_timing_buffer_value \
    NPU_ADDR_WIDTH=$npu_addr_width_value \
    NPU_ENABLE_IS_MODE=$npu_enable_is_mode_value \
    NPU_ENABLE_PER_CHANNEL=$npu_enable_per_channel_value \
    NPU_ENABLE_CLOCK_GATING=$npu_enable_clock_gating_value \
    MAX_SYS_CYCLES=$max_sys_cycles_value \
]
lappend tb_generics "CPU_MEM_PATH=\"$mem_path_escaped\""

set_property top fpga_top_behav_smoke_tb [get_filesets sim_1]
set_property generic $tb_generics [get_filesets sim_1]
# Keep launch_simulation from starting the run before the script can manage
# the final PASS/FAIL check.
set_property xsim.simulate.runtime 0ns [get_filesets sim_1]
update_compile_order -fileset sim_1

set sim_failed 0
set sim_error_msg ""

if {[catch {
    launch_simulation -mode behavioral
    run all
} run_msg]} {
    set sim_failed 1
    set sim_error_msg $run_msg
}

catch {close_sim}

catch {
    set post_tb_file [file normalize [file join $project_root src sim fpga_top_post_impl_tb.sv]]
    if {![file exists $post_tb_file]} {
        set post_tb_file [file normalize [file join $project_root sim fpga_top_post_impl_tb.sv]]
    }
    if {[file exists $post_tb_file]} {
        if {[llength [get_files -quiet -of_objects [get_filesets sim_1] $post_tb_file]] == 0} {
            add_files -norecurse -fileset sim_1 $post_tb_file
        }
        set_property top fpga_top_post_impl_tb [get_filesets sim_1]
        update_compile_order -fileset sim_1
    }
}

if {!$sim_failed} {
    if {[catch {
        check_smoke_log $project_xpr {[BEHAV_SMOKE] PASS:} {BEHAV_SMOKE}
    } check_msg]} {
        set sim_failed 1
        set sim_error_msg $check_msg
    }
}

catch {close_project}

if {$sim_failed} {
    error $sim_error_msg
}
