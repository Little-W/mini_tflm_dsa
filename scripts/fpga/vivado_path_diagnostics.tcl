# 在已打开并加载时钟约束的设计中导出资源、全设计与指定范围的时序样本。
# source scripts/fpga/vivado_path_diagnostics.tcl
# path_diagnostics::write build/path_diagnostics
source [file join [file dirname [file normalize [info script]]] vivado_soc_reports.tcl]

namespace eval path_diagnostics {}

proc path_diagnostics::positive_count {count label} {
    if {![string is integer -strict $count] || $count < 1 || $count > 10000} {
        error "$label must be an integer from 1 through 10000"
    }
    return $count
}

proc path_diagnostics::field {value} {
    if {[regexp {[\t\r\n]} $value]} {
        error "Timing table fields must not contain tabs or newlines"
    }
    return $value
}

proc path_diagnostics::select_cells {pattern} {
    return [get_cells -hierarchical -quiet -filter "IS_SEQUENTIAL == 1 && NAME =~ $pattern"]
}

proc path_diagnostics::sample {directory scope count selection matched_cells table queries} {
    set report [open [file join $directory ${scope}_paths.rpt] w]
    try {
        puts $report "Vivado timing samples: $scope"
        puts $report "One worst path per endpoint and path group; query limit $count per delay type."
        puts $report "Complete timing statistics are recorded in timing_summary.rpt."
        foreach delay_type {max min} {
            set paths [get_timing_paths -delay_type $delay_type -nworst 1 \
                -max_paths $count -no_report_unconstrained {*}$selection]
            set ranked {}
            foreach path $paths {
                set slack [timing_checks::finite_number [get_property SLACK $path] "path slack"]
                lappend ranked [list $slack $path]
            }
            puts $queries [join [list $scope $delay_type $matched_cells 1 $count \
                [llength $paths] [expr {[llength $paths] >= $count}]] \t]
            foreach entry [lsort -real -index 0 $ranked] {
                set path [lindex $entry 1]
                set clock [get_property ENDPOINT_CLOCK $path]
                set row [list $scope $delay_type [get_property NAME $clock] \
                    [get_property PERIOD $clock] [get_property STARTPOINT_PIN $path] \
                    [get_property ENDPOINT_PIN $path] [lindex $entry 0] \
                    [get_property LOGIC_LEVELS $path]]
                foreach value $row { field $value }
                puts $table [join $row \t]
                puts $report "\n[unique_timing_paths::detail [report_timing -of_objects $path -return_string]]"
            }
        }
    } finally {
        close $report
    }
}

proc path_diagnostics::write {directory {endpoint_count 5000} {module_count 40} {critical_count 100}} {
    positive_count $endpoint_count endpoint_count
    positive_count $module_count module_count
    positive_count $critical_count critical_count
    file mkdir $directory

    # 面积和全部设计的时序统计由原生报告提供，路径样本保存具体电路位置。
    report_utilization -file [file join $directory utilization.rpt]
    report_utilization -hierarchical -file [file join $directory utilization_hier.rpt]
    report_timing_summary -delay_type min_max -report_unconstrained -check_timing_verbose \
        -file [file join $directory timing_summary.rpt]
    report_high_fanout_nets -fanout_greater_than 100 -max_nets 200 \
        -file [file join $directory high_fanout.rpt]
    soc_reports::write_module_paths $directory design $module_count

    set table [open [file join $directory endpoints.tsv] w]
    set queries [open [file join $directory queries.tsv] w]
    try {
        puts $table "scope\tdelay_type\tclock\tclock_period_ns\tstartpoint\tendpoint\tslack_ns\tlogic_levels"
        puts $queries "scope\tdelay_type\tmatched_cells\tscope_available\tquery_limit\treturned_paths\tlimit_reached"
        sample $directory global $endpoint_count {} all $table $queries

        # 保留实际反馈路径的起点与终点视图；相同范围同时检查建立和保持时间。
        foreach {scope direction pattern} {
            im2col_group_range -to {*g_im2col.u_frontend/group_range_q_reg*}
            im2col_past_active -from {*g_im2col.u_frontend/past_active_q_reg*}
            im2col_channel -from {*g_im2col.u_frontend/ch_q_reg*}
        } {
            set cells [select_cells $pattern]
            if {[llength $cells] == 0} {
                file delete -force [file join $directory ${scope}_paths.rpt]
                foreach delay_type {max min} {
                    puts $queries [join [list $scope $delay_type 0 0 $critical_count 0 0] \t]
                }
                continue
            }
            sample $directory $scope $critical_count [list $direction $cells] \
                [llength $cells] $table $queries
        }
    } finally {
        close $table
        close $queries
    }
    return [dict create directory [file normalize $directory] endpoint_count $endpoint_count \
        module_count $module_count critical_count $critical_count]
}
