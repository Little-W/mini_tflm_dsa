# 仅供脚本测试使用的 Vivado 命令模型；所有时序值均为人工构造数据。
# 此文件不执行综合、布局或布线，也不产生可用于器件频率判断的结果。
namespace eval vivado_timing_mock {
    variable events [list]
    variable clocks [dict create]
    variable paths [dict create]
    variable selected_checks [list]
    variable options [dict create]
}

proc vivado_timing_mock::record {command args} {
    variable events
    lappend events [list $command {*}$args]
}

proc vivado_timing_mock::set_option {name value} {
    variable options
    dict set options $name $value
}

proc vivado_timing_mock::set_clock {name period} {
    variable clocks
    dict set clocks $name $period
}

proc vivado_timing_mock::clear_paths {} {
    variable paths
    set paths [dict create]
}

proc vivado_timing_mock::add_path {name delay_type endpoint slack start_clock end_clock requirement {exception ""}} {
    variable paths
    dict set paths $name [dict create DELAY_TYPE $delay_type ENDPOINT_PIN $endpoint \
        SLACK $slack STARTPOINT_CLOCK $start_clock ENDPOINT_CLOCK $end_clock \
        STARTPOINT_PIN source_$name/Q REQUIREMENT $requirement EXCEPTION $exception]
}

proc vivado_timing_mock::default_report {} {
    set names {no_clock unconstrained_internal_endpoints generated_clocks loops latch_loops}
    set report "check_timing report\n\nTable of Contents\n\n"
    set index 0
    foreach name $names {
        append report "[incr index]. checking $name (0)\n"
    }
    set index 0
    foreach name $names {
        append report "\n[incr index]. checking $name (0)\n--------------------\n"
        append report "There are 0 timing items in this check.\n"
    }
    return $report
}

proc vivado_timing_mock::default_timing_summary {} {
    set headers {WNS(ns) TNS(ns) {TNS Failing Endpoints} {TNS Total Endpoints} \
        WHS(ns) THS(ns) {THS Failing Endpoints} {THS Total Endpoints} \
        WPWS(ns) TPWS(ns) {TPWS Failing Endpoints} {TPWS Total Endpoints}}
    set labels ""
    set rules ""
    set values ""
    foreach header $headers value {0.667 0.000 0 200 0.125 0.000 0 200 0.250 0.000 0 400} {
        append labels [format "%24s  " $header]
        append rules [format "%24s  " ------------------------]
        append values [format "%24s  " $value]
    }
    return " | Design Timing Summary\n$labels\n$rules\n$values\n"
}

proc vivado_timing_mock::reset {} {
    variable events
    variable clocks
    variable paths
    variable selected_checks
    variable options
    set events [list]
    set clocks [dict create soc_clk [expr {1000.0/150.0}]]
    set paths [dict create]
    set selected_checks [list]
    set options [dict create fully_routed 1 routing_errors 0 \
        input_clocks [list soc_clk] clock_ports [list clk] \
        input_ports [list clk] output_ports [list] \
        half_rise_fall [list] half_fall_rise [list] \
        drc_failures [list] no_drc_checks 0 max_path_query_limit 0 \
        check_report [default_report] timing_summary [default_timing_summary] \
        xdc "create_clock -name soc_clk -period 6.667 \[get_ports clk\]\n"]
    add_path setup_default max endpoint_default/D 0.667 soc_clk soc_clk 6.667
    add_path hold_default min endpoint_default/D 0.125 soc_clk soc_clk 0.0
}

proc vivado_timing_mock::option {arguments name {fallback ""}} {
    set index [lsearch -exact $arguments $name]
    if {$index < 0} { return $fallback }
    if {$index + 1 >= [llength $arguments]} { error "Missing argument for $name" }
    return [lindex $arguments [expr {$index + 1}]]
}

proc vivado_timing_mock::validate_options {arguments valued flags} {
    set index 0
    while {$index < [llength $arguments]} {
        set key [lindex $arguments $index]
        if {$key in $flags} {
            incr index
        } elseif {$key in $valued} {
            incr index 2
            if {$index > [llength $arguments]} { error "Missing argument for $key" }
        } else {
            error "Unsupported modeled Vivado option: $key"
        }
    }
}

proc vivado_timing_mock::report_file {arguments} {
    set path [option $arguments -file]
    if {$path ne ""} {
        file mkdir [file dirname $path]
        set stream [open $path w]
        puts $stream "VIVADO COMMAND SIMULATION: synthetic report, no device implementation."
        close $stream
    }
}

proc report_timing_summary {args} {
    vivado_timing_mock::record report_timing_summary {*}$args
    set text [dict get $::vivado_timing_mock::options timing_summary]
    set path [vivado_timing_mock::option $args -file]
    if {$path ne ""} {
        set stream [open $path w]
        puts $stream $text
        close $stream
    }
    return $text
}

proc report_pulse_width {args} {
    vivado_timing_mock::record report_pulse_width {*}$args
    vivado_timing_mock::validate_options $args {-file} {-all_violators}
    vivado_timing_mock::report_file $args
}

proc vivado_timing_mock::save_events {path} {
    variable events
    set stream [open $path w]
    foreach event $events { puts $stream $event }
    close $stream
}

# 配置参数测试已有属性读取实现，非时序属性继续交给该实现处理。
if {[llength [info commands ::get_property]] != 0 &&
    [llength [info commands ::vivado_timing_mock::prior_get_property]] == 0} {
    rename ::get_property ::vivado_timing_mock::prior_get_property
}

proc get_property {property object} {
    if {[dict exists $::vivado_timing_mock::paths $object $property]} {
        return [dict get $::vivado_timing_mock::paths $object $property]
    }
    if {[dict exists $::vivado_timing_mock::clocks $object]} {
        switch -- $property {
            NAME { return $object }
            PERIOD { return [dict get $::vivado_timing_mock::clocks $object] }
        }
    }
    if {[llength [info commands ::vivado_timing_mock::prior_get_property]] != 0} {
        return [::vivado_timing_mock::prior_get_property $property $object]
    }
    error "Unknown modeled property $property of $object"
}

proc get_clocks {args} {
    vivado_timing_mock::record get_clocks {*}$args
    vivado_timing_mock::validate_options $args {-of_objects} {-quiet}
    if {[lsearch -exact $args -of_objects] >= 0} {
        return [dict get $::vivado_timing_mock::options input_clocks]
    }
    return [dict keys $::vivado_timing_mock::clocks]
}

proc get_ports {args} {
    vivado_timing_mock::record get_ports {*}$args
    if {$args eq "clk"} { return [dict get $::vivado_timing_mock::options clock_ports] }
    vivado_timing_mock::validate_options $args {-filter} {-quiet}
    switch -- [vivado_timing_mock::option $args -filter] {
        {DIRECTION == IN || DIRECTION == INOUT} {
            return [dict get $::vivado_timing_mock::options input_ports]
        }
        {DIRECTION == OUT || DIRECTION == INOUT} {
            return [dict get $::vivado_timing_mock::options output_ports]
        }
        default { error "Unexpected modeled port query $args" }
    }
}

proc create_clock {args} {
    vivado_timing_mock::record create_clock {*}$args
    set name [vivado_timing_mock::option $args -name]
    set period [vivado_timing_mock::option $args -period]
    if {$name eq "" || $period eq ""} { error "Clock name and period are required" }
    vivado_timing_mock::set_clock $name $period
    vivado_timing_mock::set_option input_clocks [list $name]
}

proc report_route_status {args} {
    vivado_timing_mock::record report_route_status {*}$args
    vivado_timing_mock::validate_options $args {-boolean_check -file -route_type} {-return_nets}
    set kind [vivado_timing_mock::option $args -boolean_check]
    switch -- $kind {
        ROUTED_FULLY { return [dict get $::vivado_timing_mock::options fully_routed] }
        ERRORS_IN_ROUTES { return [dict get $::vivado_timing_mock::options routing_errors] }
        "" { vivado_timing_mock::report_file $args; return }
        default { error "Unknown modeled route check $kind" }
    }
}

proc get_drc_checks {args} {
    vivado_timing_mock::record get_drc_checks {*}$args
    vivado_timing_mock::validate_options $args {-ruledecks -filter} {}
    if {[dict get $::vivado_timing_mock::options no_drc_checks]} { return [list] }
    set filter [vivado_timing_mock::option $args -filter]
    foreach severity {Fatal Error {Critical Warning}} {
        if {[string first $severity $filter] < 0} {
            error "The required DRC filter does not include $severity"
        }
    }
    return [list DRC_FATAL DRC_ERROR DRC_CRITICAL]
}

proc report_drc {args} {
    vivado_timing_mock::record report_drc {*}$args
    vivado_timing_mock::validate_options $args {-name -checks -file} {}
    set ::vivado_timing_mock::selected_checks [vivado_timing_mock::option $args -checks]
    vivado_timing_mock::report_file $args
}

proc get_drc_violations {args} {
    vivado_timing_mock::record get_drc_violations {*}$args
    vivado_timing_mock::validate_options $args {-name} {}
    if {[vivado_timing_mock::option $args -name] ne "required_post_route"} {
        error "Expected the named post-route DRC result"
    }
    set result [list]
    foreach check [dict get $::vivado_timing_mock::options drc_failures] {
        if {$check in $::vivado_timing_mock::selected_checks} { lappend result $check }
    }
    return $result
}

proc check_timing {args} {
    vivado_timing_mock::record check_timing {*}$args
    vivado_timing_mock::validate_options $args {-override_defaults} {-verbose -return_string}
    if {[lsearch -exact $args -return_string] < 0} {
        error "The timing checker must capture the report text"
    }
    return [dict get $::vivado_timing_mock::options check_report]
}

proc write_xdc {args} {
    vivado_timing_mock::record write_xdc {*}$args
    vivado_timing_mock::validate_options [lrange $args 0 end-1] {-constraints -type} {-force}
    if {[vivado_timing_mock::option $args -type] ne "timing" ||
        [vivado_timing_mock::option $args -constraints] ne "valid"} {
        error "Expected valid effective timing constraints"
    }
    set stream [open [lindex $args end] w]
    puts -nonewline $stream [dict get $::vivado_timing_mock::options xdc]
    close $stream
}

proc report_exceptions {args} {
    vivado_timing_mock::record report_exceptions {*}$args
    vivado_timing_mock::validate_options $args {-file} {-summary}
    vivado_timing_mock::report_file $args
}

proc get_timing_paths {args} {
    vivado_timing_mock::record get_timing_paths {*}$args
    vivado_timing_mock::validate_options $args \
        {-delay_type -to -from -nworst -max_paths -rise_from -fall_from -rise_to -fall_to} \
        {-no_report_unconstrained}
    set limit [vivado_timing_mock::option $args -max_paths 1]
    set maximum [dict get $::vivado_timing_mock::options max_path_query_limit]
    if {$maximum > 0 && ($limit > $maximum || $limit < 1)} {
        error "Timing path query exceeds modeled limit: $args"
    }
    if {[lsearch -exact $args -rise_from] >= 0 && [lsearch -exact $args -fall_to] >= 0} {
        return [lrange [dict get $::vivado_timing_mock::options half_rise_fall] 0 [expr {$limit-1}]]
    }
    if {[lsearch -exact $args -fall_from] >= 0 && [lsearch -exact $args -rise_to] >= 0} {
        return [lrange [dict get $::vivado_timing_mock::options half_fall_rise] 0 [expr {$limit-1}]]
    }
    set delay [vivado_timing_mock::option $args -delay_type max]
    set capture [vivado_timing_mock::option $args -to]
    set launch [vivado_timing_mock::option $args -from]
    set ordered [list]
    dict for {name properties} $::vivado_timing_mock::paths {
        if {[dict get $properties DELAY_TYPE] ne $delay} { continue }
        set endpoint_cell [join [lrange [split [dict get $properties ENDPOINT_PIN] /] 0 end-1] /]
        if {$capture ne "" && [dict get $properties ENDPOINT_CLOCK] ni $capture &&
            [dict get $properties ENDPOINT_PIN] ni $capture && $endpoint_cell ni $capture} { continue }
        if {$launch ne "" && [dict get $properties STARTPOINT_CLOCK] ni $launch &&
            [dict get $properties STARTPOINT_PIN] ni $launch} { continue }
        set slack [dict get $properties SLACK]
        # 非法属性仍返回给待测脚本，让该脚本执行数值检查。
        if {![string is double -strict $slack] || [string match -nocase *nan* $slack]} { set slack -Inf }
        lappend ordered [list $slack $name]
    }
    # 按最差裕量选择每个端点的路径，保留次差起点供显式筛选查询检查。
    set nworst [vivado_timing_mock::option $args -nworst 1]
    set counts [dict create]
    set result [list]
    foreach pair [lsort -real -index 0 $ordered] {
        set name [lindex $pair 1]
        set endpoint [dict get $::vivado_timing_mock::paths $name ENDPOINT_PIN]
        dict incr counts $endpoint
        if {[dict get $counts $endpoint] <= $nworst} { lappend result $name }
    }
    return [lrange $result 0 [expr {$limit-1}]]
}

proc read_xdc {path} {
    vivado_timing_mock::record read_xdc $path
    source $path
}

proc version {args} { return "VIVADO_COMMAND_SIMULATION" }

foreach command {set_param create_project read_verilog link_design opt_design place_design phys_opt_design route_design write_checkpoint report_utilization report_timing_summary report_timing write_bitstream} {
    if {[llength [info commands ::$command]] == 0} {
        proc ::$command {args} [format {vivado_timing_mock::record %s {*}$args; return} $command]
    }
}

vivado_timing_mock::reset
