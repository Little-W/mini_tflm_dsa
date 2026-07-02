# Create the Vivado project and run synthesis.
#
# Usage:
#   vivado -mode batch -source fpga/vivado/tflm_ai_dsa_soc/scripts/run_synth.tcl
#   vivado -mode batch -source fpga/vivado/tflm_ai_dsa_soc/scripts/run_synth.tcl \
#       -tclargs build/vivado/tflm_ai_dsa_soc_s16_c4 xc7a200tfbg484-3 16 4

set script_dir [file dirname [file normalize [info script]]]
source [file join $script_dir create_project.tcl]

if {[info exists ::env(VIVADO_JOBS)] && $::env(VIVADO_JOBS) ne ""} {
    set jobs $::env(VIVADO_JOBS)
} else {
    set jobs 8
}

launch_runs synth_1 -jobs $jobs
wait_on_run synth_1

open_run synth_1 -name synth_1

set report_dir [file join $project_dir reports]
file mkdir $report_dir

report_utilization -file [file join $report_dir fpga_top_utilization.rpt]
report_utilization -hierarchical -file [file join $report_dir fpga_top_utilization_hier.rpt]
report_timing_summary -delay_type max -report_unconstrained -check_timing_verbose \
    -file [file join $report_dir fpga_top_timing_summary.rpt]
report_timing -delay_type max -sort_by group -max_paths 200 -nworst 1 \
    -file [file join $report_dir fpga_top_timing_paths.rpt]
report_high_fanout_nets -fanout_greater_than 100 -max_nets 200 \
    -file [file join $report_dir fpga_top_high_fanout.rpt]

write_checkpoint -force [file join $report_dir fpga_top_synth.dcp]
puts "Synthesis reports written to $report_dir"
