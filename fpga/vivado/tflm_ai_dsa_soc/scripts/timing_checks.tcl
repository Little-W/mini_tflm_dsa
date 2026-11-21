# 布线完成后检查内部时序覆盖；完整端点统计以 Vivado 时序摘要为准。
namespace eval timing_checks {
    variable results_helper [file normalize [file join [file dirname [info script]] .. .. .. .. scripts fpga vivado_soc_results.py]]
    variable required_checks {
        no_clock unconstrained_internal_endpoints generated_clocks loops latch_loops
    }
}

proc timing_checks::write_text {path text} {
    set stream [open $path w]
    puts $stream $text
    close $stream
}

proc timing_checks::finite_number {value label} {
    set value [string trim $value]
    if {![regexp {^[+-]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eE][+-]?[0-9]+)?$} $value]} {
        error "Expected a finite numeric $label, received '$value'"
    }
    set number [expr {double($value)}]
    if {[string match -nocase *inf* $number]} {
        error "Expected a finite numeric $label, received '$value'"
    }
    return $number
}

proc timing_checks::internal_check_counts {report} {
    variable required_checks
    set counts [dict create]
    set current ""
    foreach line [split $report \n] {
        if {[regexp -nocase {^[ \t]*([0-9]+[.][ \t]*)?checking[ \t]+([a-z0-9_]+)([ \t]*\([0-9]+\))?[.]?[ \t]*$} $line -> number name]} {
            set current [string tolower $name]
            continue
        }
        # 同一检查可按根时钟或端点类别输出多项数量；目录标题不参与求和。
        if {$current in $required_checks &&
            [regexp -nocase {There (are|is)[ \t]+([0-9]+)[ \t]} $line -> verb count]} {
            dict incr counts $current $count
        }
    }
    foreach name $required_checks {
        if {![dict exists $counts $name]} {
            error "No numeric result was found for required check_timing check '$name'"
        }
    }
    return $counts
}

proc timing_checks::check_implementation {out_dir} {
    variable required_checks
    variable results_helper
    file mkdir $out_dir
    set failures [list]
    # 任何中途缺失数据或 Tcl 错误都保留明确的未通过状态。
    write_text [file join $out_dir implementation_checks.tsv] "check\tvalue\ncompleted\t0\npassed\t0"

    set fully_routed [report_route_status -boolean_check ROUTED_FULLY]
    set route_errors [report_route_status -boolean_check ERRORS_IN_ROUTES]
    if {$fully_routed ne "1" || $route_errors ne "0"} {
        lappend failures "The design contains incomplete or erroneous routing"
    }

    # 根据检查规则自身的严重性选择必须通过的 DRC，再读取该命名报告的结果。
    set severe_checks [get_drc_checks -ruledecks default \
        -filter {SEVERITY == Fatal || SEVERITY == Error || SEVERITY == "Critical Warning"}]
    if {[llength $severe_checks] == 0} { error "No required post-route DRC checks were selected" }
    report_drc -name required_post_route -checks $severe_checks \
        -file [file join $out_dir required_post_route_drc.rpt]
    set severe_violations [get_drc_violations -name required_post_route]
    if {[llength $severe_violations] != 0} {
        lappend failures "Required post-route DRC checks failed: $severe_violations"
    }

    write_text [file join $out_dir clock_checks.rpt] [check_timing -verbose -return_string]
    set required_report [check_timing -verbose -override_defaults $required_checks -return_string]
    write_text [file join $out_dir required_clock_checks.rpt] $required_report
    set check_counts [internal_check_counts $required_report]
    set check_lines [list "check\tcount"]
    dict for {name count} $check_counts {
        lappend check_lines "$name\t$count"
        if {$count != 0} { lappend failures "Internal timing check '$name' found $count issue(s)" }
    }
    write_text [file join $out_dir internal_timing_checks.tsv] [join $check_lines \n]

    # 保存当前设计中的有效约束及例外，供时序摘要审阅。
    set effective_xdc [file join $out_dir effective_timing.xdc]
    write_xdc -force -constraints valid -type timing $effective_xdc
    report_exceptions -summary -file [file join $out_dir timing_exceptions.rpt]
    # 汇总数字不可从有界路径样本推导；完整统计见调用方的 routed timing summary。
    set header {clock clock_period_ns setup_wns_ns setup_tns_ns setup_endpoints setup_failing_endpoints hold_wns_ns hold_tns_ns hold_endpoints hold_failing_endpoints single_cycle_setup_fmax_estimate_mhz fmax_status}
    set lines [list [join $header \t]]
    set clocks [get_clocks -quiet]
    set setup_count 0
    set hold_count 0
    foreach clock $clocks {
        set name [get_property NAME $clock]
        set period [finite_number [get_property PERIOD $clock] "clock period"]
        if {$period <= 0} { error "The period of clock '$name' must be positive" }
        set setup_paths [get_timing_paths -delay_type max -to $clock \
            -nworst 1 -max_paths 1 -no_report_unconstrained]
        set hold_paths [get_timing_paths -delay_type min -to $clock \
            -nworst 1 -max_paths 1 -no_report_unconstrained]
        incr setup_count [expr {[llength $setup_paths] != 0}]
        incr hold_count [expr {[llength $hold_paths] != 0}]
        if {([llength $setup_paths] == 0) != ([llength $hold_paths] == 0)} {
            lappend failures "Clock '$name' is missing either setup or hold paths"
        }
        set row [list $name $period]
        foreach {kind paths} [list setup $setup_paths hold $hold_paths] {
            set worst ""
            if {[llength $paths] != 0} {
                set worst [finite_number [get_property SLACK [lindex $paths 0]] "$kind slack"]
            }
            if {$worst ne "" && $worst < 0} {
                lappend failures "Clock '$name' has negative $kind slack ($worst ns)"
            }
            lappend row $worst unavailable unavailable unavailable
        }
        # 一个路径样本不能证明所有路径均为单周期同钟路径。
        lappend row unavailable unavailable_bounded_path_sampling
        lappend lines [join $row \t]
    }
    write_text [file join $out_dir synchronous_timing.tsv] [join $lines \n]
    if {$setup_count == 0 || $hold_count == 0} {
        lappend failures "No complete set of timed setup and hold paths was found"
    }
    # 独立的全设计查询同时检查具有外部延迟约束的端口路径。
    foreach delay_type {max min} {
        foreach path [get_timing_paths -delay_type $delay_type -max_paths 1 -nworst 1 -no_report_unconstrained] {
            set slack [finite_number [get_property SLACK $path] "global timing slack"]
            if {$slack < 0} { lappend failures "The design has negative $delay_type timing slack ($slack ns)" }
        }
    }
    # 完整设计统计同时覆盖建立、保持及脉宽，任一统计缺失均不能确认时序。
    set global_report [file join $out_dir global_timing_summary.rpt]
    report_timing_summary -delay_type min_max -report_unconstrained -check_timing_verbose -file $global_report
    report_pulse_width -all_violators -file [file join $out_dir pulse_width_violations.rpt]
    set global_status [catch {exec python3 $results_helper check-timing --report $global_report \
        --out [file join $out_dir global_timing_checks.json]} global_message]
    if {$global_status} {
        lappend failures "Complete setup, hold or pulse-width statistics are missing or do not satisfy timing: $global_message"
    }
    set status_lines [list "check\tvalue" "fully_routed\t$fully_routed" \
        "routing_errors\t$route_errors" "severe_drc_violations\t[llength $severe_violations]" \
        "clocks\t[llength $clocks]" "setup_endpoints\tunavailable" "hold_endpoints\tunavailable" \
        "clocks_with_setup_paths\t$setup_count" "clocks_with_hold_paths\t$hold_count" \
        "complete_global_timing\t[expr {!$global_status}]" "completed\t1" \
        "passed\t[expr {[llength $failures] == 0}]"]
    write_text [file join $out_dir implementation_checks.tsv] [join $status_lines \n]
    if {[llength $failures] != 0} { error [join $failures \n] }
}
