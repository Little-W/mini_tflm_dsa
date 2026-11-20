# 记录板级 fpga_top 的实际综合输入、资源与时序。
# 参数沿用 create_project.tcl；VIVADO_RUN_IMPL=1 时继续执行布线。

set measurement_flow_dir [file dirname [file normalize [info script]]]
set measurement_entry [file normalize [info script]]
source [file join $measurement_flow_dir .. .. fpga vivado tflm_ai_dsa_soc scripts create_project.tcl]
source [file join $measurement_flow_dir vivado_soc_reports.tcl]
set measurement_helper [file join $measurement_flow_dir vivado_soc_results.py]
set report_dir [file join $project_dir reports]
file mkdir $report_dir
npu_config::write_snapshot [file join $report_dir hardware_config.mk] $npu_hardware_config

set measured_sources [concat $design_sources $constraint_files [soc_reports::dependency_sources] [list $measurement_entry \
    $measurement_helper [file join $measurement_flow_dir vivado_soc_reports.tcl] \
    [file join $report_dir hardware_config.mk]]]
foreach path [glob -directory $script_dir *.tcl] { lappend measured_sources $path }
if {$cpu_mem_path_value ne ""} { lappend measured_sources $cpu_mem_path_value }
set source_manifest [soc_reports::snapshot $report_dir $measurement_helper \
    [dict create repository $dsa_root vivado_version [version -short] part $part_name \
        top fpga_top clock_period_ns [expr {1000.0 / $core_clk_mhz_value}] \
        board_clock_mhz 50.0 core_clock_mhz $core_clk_mhz_value \
        generics [join $top_generics " "] defines [join $rtl_defines " "] \
        synthesis_strategy $synth_strategy_value synthesis_directive $synth_directive_value] \
    $measured_sources $include_dirs]

launch_runs synth_1 -jobs $vivado_jobs_value
wait_on_run synth_1
if {![string match "*Complete*" [get_property STATUS [get_runs synth_1]]]} {
    error "Synthesis did not complete successfully"
}
open_run synth_1 -name synth_1
soc_reports::write $report_dir fpga_top
write_checkpoint -force [file join $report_dir fpga_top_synth.dcp]
puts [exec python3 $measurement_helper summarize --manifest $source_manifest \
    --directory $report_dir --stage synthesized --prefix fpga_top]
soc_reports::check_array $report_dir $size_value

if {[info exists ::env(VIVADO_RUN_IMPL)] && $::env(VIVADO_RUN_IMPL) eq "1"} {
    if {$core_clk_mhz_value < 150.0} { error "Implementation requires a core clock of at least 150 MHz" }
    launch_runs impl_1 -to_step route_design -jobs $vivado_jobs_value
    wait_on_run impl_1
    if {![string match "*Complete*" [get_property STATUS [get_runs impl_1]]]} {
        error "Implementation did not complete successfully"
    }
    open_run impl_1 -name impl_1
    set routed_dir [file join $report_dir routed]
    soc_reports::write $routed_dir fpga_top
    write_checkpoint -force [file join $routed_dir fpga_top_routed.dcp]
    report_route_status -file [file join $routed_dir fpga_top_route_status.rpt]
    set check_status [catch {timing_checks::check_implementation $routed_dir} check_message check_options]
    if {[file isfile [file join $routed_dir implementation_checks.tsv]]} {
        puts [exec python3 $measurement_helper summarize --manifest $source_manifest \
            --directory $routed_dir --stage routed --prefix fpga_top]
    }
    if {$check_status} { return -options $check_options $check_message }
    soc_reports::check_array $routed_dir $size_value
}
