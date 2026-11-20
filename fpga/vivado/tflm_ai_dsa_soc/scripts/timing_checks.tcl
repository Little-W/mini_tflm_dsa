# 布线完成后检查内部时序覆盖，并按实际捕获时钟保存完整端点统计。
namespace eval timing_checks {
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

proc timing_checks::all_endpoint_paths {delay_type clock} {
    # 扩大查询范围直到结果未达到上限，避免以固定数量的最长路径计算 TNS。
    set limit 1024
    while {1} {
        set paths [get_timing_paths -delay_type $delay_type -to $clock \
            -nworst 1 -max_paths $limit -no_report_unconstrained]
        if {[llength $paths] < $limit} { return $paths }
        if {$limit >= 16777216} {
            error "Timing endpoint enumeration reached its supported limit for $clock"
        }
        set limit [expr {$limit * 2}]
    }
}

proc timing_checks::endpoint_statistics {paths} {
    set endpoints [dict create]
    foreach path $paths {
        set endpoint [get_property ENDPOINT_PIN $path]
        if {$endpoint eq ""} { error "A timed path has no ENDPOINT_PIN" }
        set slack [finite_number [get_property SLACK $path] "path slack"]
        if {![dict exists $endpoints $endpoint] || $slack < [dict get $endpoints $endpoint]} {
            dict set endpoints $endpoint $slack
        }
    }
    set worst ""
    set total 0.0
    set failing 0
    dict for {endpoint slack} $endpoints {
        if {$worst eq "" || $slack < $worst} { set worst $slack }
        if {$slack < 0} {
            set total [expr {$total + $slack}]
            incr failing
        }
    }
    return [dict create wns $worst tns $total endpoints [dict size $endpoints] failing $failing]
}

proc timing_checks::clock_fmax {clock period setup_paths special_exceptions} {
    if {$special_exceptions} {
        return [list "" special_timing_exceptions_present]
    }
    if {[llength $setup_paths] == 0} { return [list "" no_setup_paths] }
    set name [get_property NAME $clock]
    set worst ""
    foreach path $setup_paths {
        if {[get_property STARTPOINT_CLOCK $path] ne $name ||
            [get_property ENDPOINT_CLOCK $path] ne $name} {
            return [list "" paths_from_other_clock_or_input]
        }
        if {[string trim [get_property EXCEPTION $path]] ne ""} {
            return [list "" timing_exception_on_path]
        }
        set requirement [finite_number [get_property REQUIREMENT $path] "setup requirement"]
        if {abs($requirement - $period) > max(0.000001, $period * 0.000001)} {
            return [list "" non_single_cycle_requirement]
        }
        set slack [finite_number [get_property SLACK $path] "setup slack"]
        if {$worst eq "" || $slack < $worst} { set worst $slack }
    }
    # 每端点的最差路径可能遮住其他起点，跨时钟关系须分别检查两个方向。
    foreach other_clock [get_clocks -quiet] {
        if {[get_property NAME $other_clock] eq $name} { continue }
        foreach {launch capture} [list $other_clock $clock $clock $other_clock] {
            set paths [get_timing_paths -delay_type max -from $launch -to $capture \
                -nworst 1 -max_paths 1 -no_report_unconstrained]
            if {[llength $paths] != 0} { return [list "" inter_clock_paths_present] }
        }
    }
    # 外部输入和输出包含接口延迟要求，不用于内部单周期最高频率估算。
    set inputs [get_ports -quiet -filter {DIRECTION == IN || DIRECTION == INOUT}]
    set outputs [get_ports -quiet -filter {DIRECTION == OUT || DIRECTION == INOUT}]
    foreach {launch capture} [list $inputs $clock $clock $outputs] {
        if {[llength $launch] == 0 || [llength $capture] == 0} { continue }
        set paths [get_timing_paths -delay_type max -from $launch -to $capture \
            -nworst 1 -max_paths 1 -no_report_unconstrained]
        if {[llength $paths] != 0} { return [list "" external_port_paths_present] }
    }
    # 半周期路径可能与同一端点的其他路径共存，须单独查询两种跨边沿方向。
    foreach {from_option to_option} {-rise_from -fall_to -fall_from -rise_to} {
        set paths [get_timing_paths -delay_type max $from_option $clock $to_option $clock \
            -nworst 1 -max_paths 1 -no_report_unconstrained]
        if {[llength $paths] != 0} { return [list "" opposite_clock_edges] }
    }
    set minimum_period [expr {$period - $worst}]
    if {$minimum_period <= 0} { return [list "" nonpositive_estimated_period] }
    return [list [expr {1000.0 / $minimum_period}] single_cycle_setup_estimate]
}

proc timing_checks::check_implementation {out_dir} {
    variable required_checks
    file mkdir $out_dir
    set failures [list]

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

    # 保存当前设计中的有效约束，特殊周期或独立延迟例外仅限制 Fmax 估算范围。
    set effective_xdc [file join $out_dir effective_timing.xdc]
    write_xdc -force -constraints valid -type timing $effective_xdc
    report_exceptions -summary -file [file join $out_dir timing_exceptions.rpt]
    set stream [open $effective_xdc r]
    set constraints [read $stream]
    close $stream
    set special_exceptions [regexp -line {^[ \t]*(set_multicycle_path|set_max_delay)[ \t]} $constraints]

    set header {clock clock_period_ns setup_wns_ns setup_tns_ns setup_endpoints setup_failing_endpoints hold_wns_ns hold_tns_ns hold_endpoints hold_failing_endpoints single_cycle_setup_fmax_estimate_mhz fmax_status}
    set lines [list [join $header \t]]
    set clocks [get_clocks -quiet]
    set setup_count 0
    set hold_count 0
    foreach clock $clocks {
        set name [get_property NAME $clock]
        set period [finite_number [get_property PERIOD $clock] "clock period"]
        if {$period <= 0} { error "The period of clock '$name' must be positive" }
        set setup_paths [all_endpoint_paths max $clock]
        set hold_paths [all_endpoint_paths min $clock]
        set setup [endpoint_statistics $setup_paths]
        set hold [endpoint_statistics $hold_paths]
        incr setup_count [dict get $setup endpoints]
        incr hold_count [dict get $hold endpoints]
        if {([dict get $setup endpoints] == 0) != ([dict get $hold endpoints] == 0)} {
            lappend failures "Clock '$name' is missing either setup or hold paths"
        }
        foreach {kind statistics} [list setup $setup hold $hold] {
            set worst [dict get $statistics wns]
            if {$worst ne "" && $worst < 0} {
                lappend failures "Clock '$name' has negative $kind slack ($worst ns)"
            }
        }
        lassign [clock_fmax $clock $period $setup_paths $special_exceptions] frequency status
        set row [list $name $period]
        foreach statistics [list $setup $hold] {
            foreach key {wns tns endpoints failing} { lappend row [dict get $statistics $key] }
        }
        lappend row $frequency $status
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
    set status_lines [list "check\tvalue" "fully_routed\t$fully_routed" \
        "routing_errors\t$route_errors" "severe_drc_violations\t[llength $severe_violations]" \
        "clocks\t[llength $clocks]" "setup_endpoints\t$setup_count" "hold_endpoints\t$hold_count" \
        "passed\t[expr {[llength $failures] == 0}]"]
    write_text [file join $out_dir implementation_checks.tsv] [join $status_lines \n]
    if {[llength $failures] != 0} { error [join $failures \n] }
}
