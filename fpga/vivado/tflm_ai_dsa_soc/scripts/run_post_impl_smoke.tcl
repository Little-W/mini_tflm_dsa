# Run a minimal post-implementation functional simulation for an exported project.
#
# Usage:
#   vivado -mode batch -source fpga/vivado/tflm_ai_dsa_soc/scripts/run_post_impl_smoke.tcl \
#       -tclargs vivado_export/<export_name>/project/tflm_ai_dsa_soc.xpr

if {[llength $argv] < 1} {
    error "Usage: run_post_impl_smoke.tcl <project.xpr> ?MAX_SYS_CYCLES? ?FAST_UART_WAIT_BYPASS?"
}

set script_dir [file dirname [file normalize [info script]]]
source [file join $script_dir npu_config.tcl]
set project_xpr [file normalize [lindex $argv 0]]
set repo_tb_file [file normalize [file join $script_dir .. sim fpga_top_post_impl_tb.sv]]
if {![file exists $repo_tb_file]} {
    set repo_tb_file [file normalize [file join $script_dir .. src sim fpga_top_post_impl_tb.sv]]
}

if {![file exists $project_xpr]} {
    error "Vivado project not found: $project_xpr"
}
if {![file exists $repo_tb_file]} {
    error "Post-impl smoke testbench not found: $repo_tb_file"
}

proc upsert_generic_value {generic_items name value} {
    set out [list]
    set replaced 0
    foreach item $generic_items {
        set eq_pos [string first "=" $item]
        if {$eq_pos <= 0} {
            lappend out $item
            continue
        }
        set key [string range $item 0 [expr {$eq_pos - 1}]]
        if {$key eq $name} {
            lappend out "$name=$value"
            set replaced 1
        } else {
            lappend out $item
        }
    }
    if {!$replaced} {
        lappend out "$name=$value"
    }
    return $out
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
set tb_file [file normalize [file join $project_root src sim fpga_top_post_impl_tb.sv]]
if {[file exists [file dirname $tb_file]]} {
    if {$repo_tb_file ne $tb_file} { file copy -force $repo_tb_file $tb_file }
} else {
    set tb_file [file normalize [file join $project_root sim fpga_top_post_impl_tb.sv]]
    if {[file exists [file dirname $tb_file]]} {
        if {$repo_tb_file ne $tb_file} { file copy -force $repo_tb_file $tb_file }
    } else {
        set tb_file $repo_tb_file
    }
}

open_project $project_xpr
set project_hardware_config [npu_config::project_values [get_property generic [get_filesets sources_1]]]

if {[llength [get_files -quiet -of_objects [get_filesets sim_1] $tb_file]] == 0} {
    add_files -norecurse -fileset sim_1 $tb_file
}

set_property top fpga_top_post_impl_tb [get_filesets sim_1]
set tb_generics [get_property generic [get_filesets sim_1]]
foreach item [npu_config::generics $project_hardware_config] {
    set equal [string first = $item]
    set tb_generics [upsert_generic_value $tb_generics \
        [string range $item 0 [expr {$equal - 1}]] \
        [string range $item [expr {$equal + 1}] end]]
}
if {[llength $argv] >= 2} {
    set tb_generics [upsert_generic_value $tb_generics MAX_SYS_CYCLES [lindex $argv 1]]
}
if {[llength $tb_generics] != 0} {
    set_property generic $tb_generics [get_filesets sim_1]
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

set sim_failed 0
set sim_error_msg ""

if {[catch {
    run all
} run_msg]} {
    set sim_failed 1
    set sim_error_msg $run_msg
}

catch {close_sim}

if {!$sim_failed} {
    if {[catch {
        check_smoke_log $project_xpr {[POST_IMPL_SMOKE] PASS:} {POST_IMPL_SMOKE}
    } check_msg]} {
        set sim_failed 1
        set sim_error_msg $check_msg
    }
}

catch {close_project}

if {$sim_failed} {
    error $sim_error_msg
}
