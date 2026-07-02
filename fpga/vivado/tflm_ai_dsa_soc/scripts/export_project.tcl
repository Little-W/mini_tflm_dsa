# Export a self-contained Vivado project for FPGA GUI synthesis/implementation.
#
# Usage:
#   vivado -mode batch -source fpga/vivado/tflm_ai_dsa_soc/scripts/export_project.tcl
#   vivado -mode batch -source fpga/vivado/tflm_ai_dsa_soc/scripts/export_project.tcl \
#       -tclargs vivado_export/tflm_ai_dsa_soc xc7a200tfbg484-3 16 4 65536 \
#       /media/proj_tmp/aiEngine_integrated/veri/tb/axi_soc_runtime_build_S16_C4_P16/cpu.mem \
#       150.000 1 0 1 1 Flow_AreaOptimized_high Performance_Explore
#
# Tcl arguments:
#   <export_root> <part> <SIZE> <IA_CACHE_BLOCKS> <CPU_MEM_DP> <CPU_MEM_PATH>
#   <CORE_CLK_MHZ> <CPU_AXI_WRITE_TIMING_BUFFER> <BYPASS_RAM_PINGPONG>
#   <RAM_WRITE_TIMING_BUFFER> <RUN_IMPL> <SYNTH_STRATEGY> <IMPL_STRATEGY>

set script_dir [file dirname [file normalize [info script]]]
set flow_root [file normalize [file join $script_dir ..]]
set dsa_root [file normalize [file join $flow_root .. .. ..]]

set project_name tflm_ai_dsa_soc
set part_name xc7a200tfbg484-3
set size_value 16
set ia_cache_blocks_value 4
set cpu_mem_dp_value 65536
set cpu_mem_path_value ""
set core_clk_mhz_value 150.000
set cpu_axi_write_timing_buffer_value 1
set bypass_ram_pingpong_value 0
set ram_write_timing_buffer_value 1
set run_impl_value 0
set synth_strategy_value Flow_PerfOptimized_high
set impl_strategy_value Performance_Explore

if {[llength $argv] >= 1} {
    set export_root [file normalize [lindex $argv 0]]
} else {
    set export_root [file join $dsa_root vivado_export $project_name]
}
if {[llength $argv] >= 2} { set part_name [lindex $argv 1] }
if {[llength $argv] >= 3} { set size_value [lindex $argv 2] }
if {[llength $argv] >= 4} { set ia_cache_blocks_value [lindex $argv 3] }
if {[llength $argv] >= 5} { set cpu_mem_dp_value [lindex $argv 4] }
if {[llength $argv] >= 6} { set cpu_mem_path_value [lindex $argv 5] }
if {[llength $argv] >= 7} { set core_clk_mhz_value [lindex $argv 6] }
if {[llength $argv] >= 8} { set cpu_axi_write_timing_buffer_value [lindex $argv 7] }
if {[llength $argv] >= 9} { set bypass_ram_pingpong_value [lindex $argv 8] }
if {[llength $argv] >= 10} { set ram_write_timing_buffer_value [lindex $argv 9] }
if {[llength $argv] >= 11} { set run_impl_value [lindex $argv 10] }
if {[llength $argv] >= 12} { set synth_strategy_value [lindex $argv 11] }
if {[llength $argv] >= 13} { set impl_strategy_value [lindex $argv 12] }
if {[info exists ::env(VIVADO_SYNTH_STRATEGY)] && $::env(VIVADO_SYNTH_STRATEGY) ne ""} {
    set synth_strategy_value $::env(VIVADO_SYNTH_STRATEGY)
}
if {[info exists ::env(VIVADO_IMPL_STRATEGY)] && $::env(VIVADO_IMPL_STRATEGY) ne ""} {
    set impl_strategy_value $::env(VIVADO_IMPL_STRATEGY)
}
if {[info exists ::env(VIVADO_RUN_IMPL)] && $::env(VIVADO_RUN_IMPL) ne ""} {
    set run_impl_value $::env(VIVADO_RUN_IMPL)
}

source [file join $script_dir sources.tcl]
source [file join $script_dir clk_wiz_ip.tcl]

proc ceil_log2 {value} {
    set n [expr {int($value)}]
    if {$n <= 1} {
        return 1
    }
    set width 0
    set limit 1
    while {$limit < $n} {
        set limit [expr {$limit << 1}]
        incr width
    }
    return $width
}

proc starts_with_path {path prefix} {
    set p [file normalize $path]
    set q [file normalize $prefix]
    if {$p eq $q} {
        return 1
    }
    return [string equal -length [string length "$q/"] "$q/" "$p"]
}

proc rel_under_root {path root} {
    set p [file normalize $path]
    set q [file normalize $root]
    if {$p eq $q} {
        return ""
    }
    if {![starts_with_path $p $q]} {
        error "$p is not under $q"
    }
    return [string range $p [expr {[string length $q] + 1}] end]
}

proc copy_one_file {src dst} {
    file mkdir [file dirname $dst]
    file copy -force $src $dst
}

proc localize_path {src export_root dsa_root ai_root} {
    set abs_src [file normalize $src]
    if {[starts_with_path $abs_src $dsa_root]} {
        return [file join $export_root src tflm_ai_dsa [rel_under_root $abs_src $dsa_root]]
    }
    if {[starts_with_path $abs_src $ai_root]} {
        return [file join $export_root src aiEngine_integrated [rel_under_root $abs_src $ai_root]]
    }
    set drive_safe [string map [list ":" "_" "\\" "/" " " "_"] [file dirname $abs_src]]
    set drive_safe [string trimleft $drive_safe "/"]
    return [file join $export_root src external $drive_safe [file tail $abs_src]]
}

proc copy_path_list {paths export_root dsa_root ai_root label} {
    set local_paths [list]
    foreach src $paths {
        set dst [localize_path $src $export_root $dsa_root $ai_root]
        if {![file exists $src]} {
            error "$label source does not exist: $src"
        }
        copy_one_file $src $dst
        lappend local_paths $dst
    }
    return $local_paths
}

proc copy_dir_contents {src_dir dst_dir} {
    if {![file isdirectory $src_dir]} {
        error "Include directory does not exist: $src_dir"
    }
    file mkdir $dst_dir
    foreach entry [glob -nocomplain -directory $src_dir *] {
        file copy -force $entry $dst_dir
    }
}

proc write_export_readme {path project_xpr bit_path mem_path size_value ia_cache_blocks_value core_clk_mhz_value} {
    set f [open $path w]
    puts $f "# Self-contained TFLM AI DSA Vivado Project"
    puts $f ""
    puts $f "Open this project in Vivado:"
    puts $f ""
    puts $f "```text"
    puts $f "$project_xpr"
    puts $f "```"
    puts $f ""
    puts $f "The RTL, constraints, and CPU memory image were copied into this directory."
    puts $f "The top generic CPU_MEM_PATH uses this absolute mem path:"
    puts $f ""
    puts $f "```text"
    puts $f "$mem_path"
    puts $f "```"
    puts $f ""
    puts $f "SIZE=$size_value IA_CACHE_BLOCKS=$ia_cache_blocks_value CORE_CLK_MHZ=$core_clk_mhz_value"
    if {$bit_path ne ""} {
        puts $f ""
        puts $f "Latest generated bitstream:"
        puts $f ""
        puts $f "```text"
        puts $f "$bit_path"
        puts $f "```"
    }
    close $f
}

if {$cpu_mem_path_value eq ""} {
    set cpu_mem_path_value [file join $ai_root veri tb "axi_soc_runtime_build_S${size_value}_C${ia_cache_blocks_value}_P${size_value}" cpu.mem]
}
set cpu_mem_path_value [file normalize $cpu_mem_path_value]
if {![file exists $cpu_mem_path_value]} {
    error "CPU memory image not found: $cpu_mem_path_value"
}

set export_parent [file dirname $export_root]
file mkdir $export_parent
if {$export_root eq $dsa_root || $export_root eq $ai_root || $export_root eq "/"} {
    error "Refusing to export into unsafe directory: $export_root"
}

file delete -force [file join $export_root project]
file delete -force [file join $export_root src]
file delete -force [file join $export_root constraints]
file delete -force [file join $export_root mem]
file mkdir $export_root
file mkdir [file join $export_root project]
file mkdir [file join $export_root mem]

set local_design_sources [copy_path_list $design_sources $export_root $dsa_root $ai_root RTL]
set local_timing_constraint_files [copy_path_list $timing_constraint_files $export_root $dsa_root $ai_root timing_constraint]
set local_implementation_constraint_files [copy_path_list $implementation_constraint_files $export_root $dsa_root $ai_root implementation_constraint]
set local_constraint_files [concat $local_timing_constraint_files $local_implementation_constraint_files]

set local_include_dirs [list]
foreach inc_dir $include_dirs {
    set dst_dir [localize_path $inc_dir $export_root $dsa_root $ai_root]
    copy_dir_contents $inc_dir $dst_dir
    lappend local_include_dirs $dst_dir
}

set local_mem_path [file join $export_root mem cpu.mem]
copy_one_file $cpu_mem_path_value $local_mem_path
set local_mem_path [file normalize $local_mem_path]

set icb_len_w_value [ceil_log2 $size_value]
set top_generics [list \
    SIZE=$size_value \
    ICB_LEN_W=$icb_len_w_value \
    IA_CACHE_BLOCKS=$ia_cache_blocks_value \
    CPU_MEM_DP=$cpu_mem_dp_value \
    CPU_MEM_INIT_EN=1 \
    CPU_AXI_WRITE_TIMING_BUFFER=$cpu_axi_write_timing_buffer_value \
    BYPASS_RAM_PINGPONG=$bypass_ram_pingpong_value \
    RAM_WRITE_TIMING_BUFFER=$ram_write_timing_buffer_value \
]
set cpu_mem_path_escaped [string map [list "\\" "\\\\" "\"" "\\\""] $local_mem_path]
lappend top_generics "CPU_MEM_PATH=\"$cpu_mem_path_escaped\""

set project_dir [file join $export_root project]
create_project -force $project_name $project_dir -part $part_name
set_property target_language Verilog [current_project]
set_property simulator_language Mixed [current_project]

set vivado_jobs_value 1
if {[info exists ::env(VIVADO_JOBS)] && $::env(VIVADO_JOBS) ne ""} {
    set vivado_jobs_value $::env(VIVADO_JOBS)
}
set_param general.maxThreads $vivado_jobs_value

create_tflm_soc_clk_wiz $core_clk_mhz_value

add_files -norecurse -fileset sources_1 $local_design_sources
add_files -norecurse -fileset constrs_1 $local_timing_constraint_files
add_files -norecurse -fileset constrs_1 $local_implementation_constraint_files
foreach xdc_file $local_implementation_constraint_files {
    set_property used_in_synthesis false [get_files $xdc_file]
}

set_property include_dirs $local_include_dirs [get_filesets sources_1]
set_property verilog_define {SYNTHESIS=1 XILINX_CLK_WIZ_IP=1} [get_filesets sources_1]
set_property top fpga_top [get_filesets sources_1]
set_property generic $top_generics [get_filesets sources_1]
update_compile_order -fileset sources_1

set synth_run [get_runs synth_1]
set_property strategy $synth_strategy_value $synth_run
set_property STEPS.SYNTH_DESIGN.ARGS.FLATTEN_HIERARCHY rebuilt $synth_run

set impl_run [get_runs impl_1]
set_property strategy $impl_strategy_value $impl_run

set project_xpr [file normalize [file join $project_dir ${project_name}.xpr]]
set bit_path ""

if {$run_impl_value} {
    launch_runs $impl_run -to_step write_bitstream -jobs $vivado_jobs_value
    wait_on_run $impl_run
    set impl_status [get_property STATUS $impl_run]
    if {![string match "*Complete*" $impl_status]} {
        error "Implementation run did not complete successfully: $impl_status"
    }
    open_run $impl_run -name impl_1

    set report_dir [file join $export_root reports]
    file mkdir $report_dir
    report_utilization -file [file join $report_dir fpga_top_utilization_routed.rpt]
    report_utilization -hierarchical -file [file join $report_dir fpga_top_utilization_hier_routed.rpt]
    report_route_status -file [file join $report_dir fpga_top_route_status.rpt]
    report_drc -file [file join $report_dir fpga_top_drc.rpt]
    report_timing_summary -delay_type max -report_unconstrained -check_timing_verbose \
        -file [file join $report_dir fpga_top_timing_summary_routed.rpt]
    report_timing -delay_type max -sort_by group -max_paths 400 -nworst 1 \
        -file [file join $report_dir fpga_top_timing_paths_routed.rpt]
    report_high_fanout_nets -fanout_greater_than 100 -max_nets 200 \
        -file [file join $report_dir fpga_top_high_fanout_routed.rpt]

    write_checkpoint -force [file join $report_dir fpga_top_routed.dcp]
    set bit_path [file normalize [file join $export_root fpga_top.bit]]
    write_bitstream -force $bit_path
}

write_export_readme [file join $export_root README.md] $project_xpr $bit_path \
    $local_mem_path $size_value $ia_cache_blocks_value $core_clk_mhz_value

puts "Self-contained Vivado project exported."
puts "Project: $project_xpr"
puts "CPU mem: $local_mem_path"
puts "Board clock: 50.000 MHz"
puts "Core clock: $core_clk_mhz_value MHz"
puts "SIZE=$size_value ICB_LEN_W=$icb_len_w_value IA_CACHE_BLOCKS=$ia_cache_blocks_value CPU_MEM_DP=$cpu_mem_dp_value"
puts "SYNTH_STRATEGY=$synth_strategy_value IMPL_STRATEGY=$impl_strategy_value RUN_IMPL=$run_impl_value"
if {$bit_path ne ""} {
    puts "Bitstream: $bit_path"
}
