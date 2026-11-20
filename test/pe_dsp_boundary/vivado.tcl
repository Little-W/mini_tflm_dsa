# 对生产 16×16 阵列执行 Vivado 综合、DSP 端口检查和时序报告。
set here [file dirname [file normalize [info script]]]
set root [file normalize [file join $here ../..]]
if {[llength $argv] != 1} { error "Usage: vivado -mode batch -source test/pe_dsp_boundary/vivado.tcl -tclargs output_directory" }
set out [file normalize [lindex $argv 0]]
file mkdir $out
set sources [list [file join $root rtl npu compute ws_systolic_cell.sv] \
    [file join $root rtl npu compute ws_systolic_array.sv] [file join $here measure.sv]]
set manifest [open [file join $out source_sha256.txt] w]
foreach path $sources { puts $manifest [exec sha256sum $path] }
close $manifest
create_project -in_memory -part xc7a200tfbg484-3
set_param general.maxThreads 2
set_property verilog_define {SYNTHESIS=1 XILINX_FPGA=1} [current_fileset]
read_verilog -sv $sources
set clock_file [file join $out clock.xdc]
set stream [open $clock_file w]
puts $stream {create_clock -name clk -period 6.667 [get_ports clk]}
close $stream
read_xdc $clock_file
synth_design -top pe_dsp_boundary_measure -part xc7a200tfbg484-3 -flatten_hierarchy rebuilt
report_utilization -file [file join $out utilization.rpt]
report_utilization -hierarchical -file [file join $out utilization_hierarchical.rpt]
report_timing_summary -delay_type max -report_unconstrained -check_timing_verbose \
    -file [file join $out timing_summary.rpt]
report_timing -delay_type max -sort_by group -max_paths 200 -nworst 1 \
    -file [file join $out timing_paths.rpt]
write_checkpoint -force [file join $out synthesized.dcp]
source [file join $here check_vivado.tcl]
pe_dsp_boundary::check [file join $out dsp_connections] {u_array/*} 16 0
