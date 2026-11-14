# Vivado batch synthesis for the AXI SoC top.
#
# Usage:
#   vivado -mode batch -source scripts/fpga/vivado_synth_soc.tcl
#   vivado -mode batch -source scripts/fpga/vivado_synth_soc.tcl -tclargs build/my_synth

set script_dir [file dirname [file normalize [info script]]]
set repo_root  [file normalize [file join $script_dir ../..]]

if {[llength $argv] >= 1} {
    set out_dir [file normalize [lindex $argv 0]]
} else {
    set out_dir [file join $repo_root build vivado_soc_synth_150mhz]
}
file mkdir $out_dir

set part_name xc7a200tfbg484-3
set top_name  soc_top
set clock_period_ns 6.667
set_param general.maxThreads 2
set synth_generics {CPU_MEM_DP=65536 CPU_MEM_INIT_EN=0}

source [file join $repo_root fpga vivado tflm_ai_dsa_soc scripts sources.tcl]
set incdirs $include_dirs
set rtl_files [lrange $design_sources 2 end]

set xdc_file [file join $out_dir soc_top_150mhz.xdc]
set xdc_fh [open $xdc_file w]
puts $xdc_fh "create_clock -name clk -period $clock_period_ns \[get_ports clk\]"
close $xdc_fh

set_property include_dirs $incdirs [current_fileset]
set_property verilog_define {SYNTHESIS=1 XILINX_FPGA=1} [current_fileset]

read_verilog -sv $rtl_files
read_xdc $xdc_file

synth_design -top $top_name -part $part_name -generic $synth_generics -flatten_hierarchy rebuilt

report_utilization -file [file join $out_dir soc_top_utilization.rpt]
report_utilization -hierarchical -file [file join $out_dir soc_top_utilization_hier.rpt]
report_timing_summary -delay_type max -report_unconstrained -check_timing_verbose \
    -file [file join $out_dir soc_top_timing_summary.rpt]
report_timing -delay_type max -sort_by group -max_paths 200 -nworst 1 \
    -file [file join $out_dir soc_top_timing_paths.rpt]
report_high_fanout_nets -fanout_greater_than 100 -max_nets 200 \
    -file [file join $out_dir soc_top_high_fanout.rpt]
write_checkpoint -force [file join $out_dir soc_top_synth.dcp]
