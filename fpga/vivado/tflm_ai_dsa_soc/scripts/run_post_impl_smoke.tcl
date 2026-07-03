# Run a minimal post-implementation functional simulation for an exported project.
#
# Usage:
#   vivado -mode batch -source fpga/vivado/tflm_ai_dsa_soc/scripts/run_post_impl_smoke.tcl \
#       -tclargs vivado_export/<export_name>/project/tflm_ai_dsa_soc.xpr

if {[llength $argv] < 1} {
    error "Usage: run_post_impl_smoke.tcl <project.xpr>"
}

set script_dir [file dirname [file normalize [info script]]]
set project_xpr [file normalize [lindex $argv 0]]
set tb_file [file normalize [file join $script_dir .. sim fpga_top_post_impl_tb.sv]]

if {![file exists $project_xpr]} {
    error "Vivado project not found: $project_xpr"
}
if {![file exists $tb_file]} {
    error "Post-impl smoke testbench not found: $tb_file"
}

open_project $project_xpr

if {[llength [get_files -quiet -of_objects [get_filesets sim_1] $tb_file]] == 0} {
    add_files -norecurse -fileset sim_1 $tb_file
}

set_property top fpga_top_post_impl_tb [get_filesets sim_1]
set_property xsim.simulate.runtime all [get_filesets sim_1]
update_compile_order -fileset sim_1

launch_simulation -mode post-implementation -type functional
run all
close_sim
close_project
