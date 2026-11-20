# 使用完整 Xilinx 原语网表执行目标器件布局布线与时序检查。
# 调用参数依次为 mapped.v、独立 soc_top 的封装引脚 XDC、输出目录。

set script_dir [file dirname [file normalize [info script]]]
source [file join $script_dir .. .. fpga vivado tflm_ai_dsa_soc scripts timing_checks.tcl]

if {[llength $argv] != 3} {
    error "Usage: vivado -mode batch -source scripts/fpga/vivado_implement_mapped_soc.tcl -tclargs mapped.v soc_measurement.xdc output_directory"
}
set mapped_file [file normalize [lindex $argv 0]]
set pin_xdc [file normalize [lindex $argv 1]]
set out_dir [file normalize [lindex $argv 2]]
foreach input_file [list $mapped_file $pin_xdc] {
    if {![file isfile $input_file]} { error "Input file does not exist: $input_file" }
}
file mkdir $out_dir

set part_name xc7a200tfbg484-3
set top_name soc_top
set clock_period_ns 6.667
set_param general.maxThreads 2
create_project -in_memory -part $part_name
read_verilog $mapped_file
read_xdc $pin_xdc
link_design -top $top_name -part $part_name

# 结构网表已经包含 IBUF、OBUF 和全局时钟缓冲器。
# 目标时钟直接来自 soc_top.clk，芯片内部时钟门控保留在网表中。
set clock_port [get_ports clk]
if {[llength $clock_port] != 1} { error "Expected one soc_top clk port" }
set main_clock [get_clocks -quiet -of_objects $clock_port]
if {[llength $main_clock] == 0} {
    create_clock -name soc_clk -period $clock_period_ns $clock_port
    set main_clock [get_clocks -of_objects $clock_port]
}
if {[llength $main_clock] != 1} { error "Expected one clock on soc_top.clk" }
set actual_period_ns [timing_checks::finite_number \
    [get_property PERIOD $main_clock] "SoC clock period"]
if {$actual_period_ns <= 0 || $actual_period_ns > $clock_period_ns + 0.000001} {
    error "The SoC clock period exceeds the 6.667 ns requirement"
}
# 保留输入 XDC 中更严格的时钟约束，并记录实际使用的周期。
set clock_period_ns $actual_period_ns

set metadata [open [file join $out_dir inputs.txt] w]
puts $metadata "Vivado: [version -short]"
puts $metadata "Part: $part_name"
puts $metadata "Top: $top_name"
puts $metadata "Clock period ns: $clock_period_ns"
puts $metadata "Mapped netlist: $mapped_file"
puts $metadata "Pin constraints: $pin_xdc"
close $metadata
write_checkpoint -force [file join $out_dir linked.dcp]
report_utilization -file [file join $out_dir linked_utilization.rpt]
report_timing_summary -delay_type min_max -report_unconstrained -check_timing_verbose \
    -file [file join $out_dir linked_timing.rpt]

opt_design
place_design
phys_opt_design
write_checkpoint -force [file join $out_dir placed.dcp]
report_utilization -file [file join $out_dir placed_utilization.rpt]
report_timing_summary -delay_type min_max -report_unconstrained -check_timing_verbose \
    -file [file join $out_dir placed_timing.rpt]

route_design
write_checkpoint -force [file join $out_dir routed.dcp]
report_route_status -file [file join $out_dir route_status.rpt]
report_drc -file [file join $out_dir routed_drc.rpt]
report_utilization -file [file join $out_dir routed_utilization.rpt]
report_timing_summary -delay_type min_max -report_unconstrained -check_timing_verbose \
    -file [file join $out_dir routed_timing.rpt]
report_timing -delay_type max -sort_by group -max_paths 200 -nworst 1 \
    -file [file join $out_dir routed_setup_paths.rpt]
report_timing -delay_type min -sort_by group -max_paths 200 -nworst 1 \
    -file [file join $out_dir routed_hold_paths.rpt]
timing_checks::check_implementation $out_dir
