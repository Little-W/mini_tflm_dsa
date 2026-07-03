# Non-project Vivado synthesis entry for quick CI-style checks.
#
# Usage:
#   vivado -mode batch -source fpga/vivado/tflm_ai_dsa_soc/scripts/run_batch_synth.tcl
#   vivado -mode batch -source fpga/vivado/tflm_ai_dsa_soc/scripts/run_batch_synth.tcl \
#       -tclargs build/vivado/tflm_ai_dsa_soc_batch xc7a200tfbg484-3 16 4

set script_dir [file dirname [file normalize [info script]]]
set export_dir [file normalize [file join $script_dir ..]]
set dsa_root [file normalize [file join $export_dir .. .. ..]]

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

if {[llength $argv] >= 1} {
    set out_dir [file normalize [lindex $argv 0]]
} else {
    set out_dir [file join $dsa_root build vivado tflm_ai_dsa_soc_batch]
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
if {[llength $argv] >= 12} { set synth_strategy_value [lindex $argv 11] }
if {[info exists ::env(VIVADO_SYNTH_STRATEGY)] && $::env(VIVADO_SYNTH_STRATEGY) ne ""} {
    set synth_strategy_value $::env(VIVADO_SYNTH_STRATEGY)
}

source [file join $script_dir sources.tcl]
source [file join $script_dir clk_wiz_ip.tcl]

set top_generics [list \
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

file mkdir $out_dir

set batch_project_dir [file join $out_dir ip_work]
create_project -force tflm_ai_dsa_soc_batch $batch_project_dir -part $part_name
set_property target_language Verilog [current_project]
set_property simulator_language Mixed [current_project]

set vivado_jobs_value 1
if {[info exists ::env(VIVADO_JOBS)] && $::env(VIVADO_JOBS) ne ""} {
    set vivado_jobs_value $::env(VIVADO_JOBS)
}
set_param general.maxThreads $vivado_jobs_value

create_tflm_soc_clk_wiz $core_clk_mhz_value

add_files -norecurse -fileset sources_1 $design_sources
add_files -norecurse -fileset constrs_1 $timing_constraint_files
add_files -norecurse -fileset constrs_1 $implementation_constraint_files
foreach xdc_file $implementation_constraint_files {
    set_property used_in_synthesis false [get_files $xdc_file]
}

set_property include_dirs $include_dirs [get_filesets sources_1]
set_property verilog_define {SYNTHESIS=1 XILINX_CLK_WIZ_IP=1} [get_filesets sources_1]
set_property top fpga_top [get_filesets sources_1]
set_property generic $top_generics [get_filesets sources_1]
update_compile_order -fileset sources_1

set synth_run [get_runs synth_1]
set_property strategy $synth_strategy_value $synth_run
set_property STEPS.SYNTH_DESIGN.ARGS.FLATTEN_HIERARCHY rebuilt $synth_run

launch_runs $synth_run -jobs $vivado_jobs_value
wait_on_run $synth_run
set synth_status [get_property STATUS $synth_run]
if {![string match "*Complete*" $synth_status]} {
    error "Synthesis run did not complete successfully: $synth_status"
}
open_run $synth_run -name synth_1

report_utilization -file [file join $out_dir fpga_top_utilization.rpt]
report_utilization -hierarchical -file [file join $out_dir fpga_top_utilization_hier.rpt]
report_timing_summary -delay_type max -report_unconstrained -check_timing_verbose \
    -file [file join $out_dir fpga_top_timing_summary.rpt]
report_timing -delay_type max -sort_by group -max_paths 200 -nworst 1 \
    -file [file join $out_dir fpga_top_timing_paths.rpt]
report_high_fanout_nets -fanout_greater_than 100 -max_nets 200 \
    -file [file join $out_dir fpga_top_high_fanout.rpt]

write_checkpoint -force [file join $out_dir fpga_top_synth.dcp]

puts "Batch synthesis completed."
puts "Reports written to $out_dir"
puts "Board clock: 50.000 MHz"
puts "Core clock: $core_clk_mhz_value MHz"
puts "SIZE=$size_value IA_CACHE_BLOCKS=$ia_cache_blocks_value CPU_MEM_DP=$cpu_mem_dp_value CPU_AXI_WRITE_TIMING_BUFFER=$cpu_axi_write_timing_buffer_value BYPASS_RAM_PINGPONG=$bypass_ram_pingpong_value RAM_WRITE_TIMING_BUFFER=$ram_write_timing_buffer_value"
puts "SYNTH_STRATEGY=$synth_strategy_value"
