# Run a minimal post-implementation functional simulation for an exported project.
#
# Usage:
#   vivado -mode batch -source fpga/vivado/tflm_ai_dsa_soc/scripts/run_post_impl_smoke.tcl \
#       -tclargs vivado_export/<export_name>/project/tflm_ai_dsa_soc.xpr

if {[llength $argv] < 1} {
    error "Usage: run_post_impl_smoke.tcl <project.xpr> ?MAX_SYS_CYCLES? ?FAST_UART_WAIT_BYPASS?"
}

set script_dir [file dirname [file normalize [info script]]]
set project_xpr [file normalize [lindex $argv 0]]
set repo_tb_file [file normalize [file join $script_dir .. sim fpga_top_post_impl_tb.sv]]

if {![file exists $project_xpr]} {
    error "Vivado project not found: $project_xpr"
}
if {![file exists $repo_tb_file]} {
    error "Post-impl smoke testbench not found: $repo_tb_file"
}

set project_root [file dirname [file dirname $project_xpr]]
set tb_file [file normalize [file join $project_root src sim fpga_top_post_impl_tb.sv]]
if {[file exists [file dirname $tb_file]]} {
    file copy -force $repo_tb_file $tb_file
} else {
    set tb_file [file normalize [file join $project_root sim fpga_top_post_impl_tb.sv]]
    if {[file exists [file dirname $tb_file]]} {
        file copy -force $repo_tb_file $tb_file
    } else {
        set tb_file $repo_tb_file
    }
}

open_project $project_xpr

if {[llength [get_files -quiet -of_objects [get_filesets sim_1] $tb_file]] == 0} {
    add_files -norecurse -fileset sim_1 $tb_file
}

set_property top fpga_top_post_impl_tb [get_filesets sim_1]
if {[llength $argv] >= 2} {
    set_property generic [list MAX_SYS_CYCLES=[lindex $argv 1]] [get_filesets sim_1]
}
set fast_uart_wait_bypass 0
if {[llength $argv] >= 3} {
    set fast_uart_wait_bypass [lindex $argv 2]
}
# Keep launch_simulation from starting the long run before optional testbench
# forces are applied; this script issues the final run command explicitly.
set_property xsim.simulate.runtime 0ns [get_filesets sim_1]
update_compile_order -fileset sim_1

launch_simulation -mode post-implementation -type functional
if {$fast_uart_wait_bypass != 0} {
    set bitcnt_objs {}
    foreach pattern {*send_bitcnt_reg_n_0_* *send_bitcnt_reg* *send_bitcnt} {
        foreach obj [get_objects -r -quiet $pattern] {
            if {[string first "u_soc_uart/u_simpleuart" $obj] >= 0} {
                lappend bitcnt_objs $obj
            }
        }
    }
    set dummy_objs {}
    foreach pattern {*send_dummy_reg_n_0* *send_dummy_reg_0 *send_dummy} {
        foreach obj [get_objects -r -quiet $pattern] {
            if {[string first "u_soc_uart/u_simpleuart" $obj] >= 0} {
                lappend dummy_objs $obj
            }
        }
    }
    if {[llength $bitcnt_objs] == 0 || [llength $dummy_objs] == 0} {
        error "Unable to locate UART wait signals in post-implementation simulation"
    }
    foreach obj [lsort -unique $bitcnt_objs] {
        add_force $obj 0 -radix unsigned
    }
    foreach obj [lsort -unique $dummy_objs] {
        add_force $obj 0 -radix unsigned
    }
    puts "POST_IMPL_SMOKE INFO: forced UART busy counters low for post-implementation runtime reduction"
}
run all
close_sim
close_project
