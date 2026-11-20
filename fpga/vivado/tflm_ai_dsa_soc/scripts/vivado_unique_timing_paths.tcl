# Reusable bounded diagnostic, not an endpoint census or a source of TNS/WNS.
# Call after opening a synthesized/implemented design:
#   source fpga/vivado/tflm_ai_dsa_soc/scripts/vivado_unique_timing_paths.tcl
#   unique_timing_paths::write output.rpt max 100 1000
# Identity means identical complete Vivado path-detail text (including clocks,
# edges, pins, nets and timing), not merely an identical endpoint pair. Values
# hidden by Vivado's report formatting cannot be distinguished by this method.
namespace eval unique_timing_paths {}

proc unique_timing_paths::detail {report} {
    # The native header contains a timestamp and the report command; neither is
    # part of a path. Fail rather than silently deduplicate on a bad report.
    if {![regexp -indices -line {^Slack \(} $report match]} {
        error "Vivado timing report has no Slack detail block"
    }
    return [string trim [string range $report [lindex $match 0] end]]
}

proc unique_timing_paths::write {file {delay_type max} {count 100} {query_limit 1000}} {
    if {$delay_type ni {max min}} { error "delay_type must be max or min" }
    if {![string is integer -strict $count] || $count < 1 ||
        ![string is integer -strict $query_limit] || $query_limit < $count || $query_limit > 10000} {
        error "Require 1 <= count <= query_limit <= 10000"
    }
    # A single bounded query; -nworst allows different paths to the same endpoint.
    set paths [get_timing_paths -delay_type $delay_type -max_paths $query_limit \
        -nworst $query_limit -no_report_unconstrained]
    set ranked {}
    foreach path $paths {
        set slack [get_property SLACK $path]
        if {![string is double -strict $slack] || [catch {expr {double($slack)}} number] ||
            [string match -nocase *inf* $number] || [string match -nocase *nan* $number]} {
            error "Non-finite timing slack '$slack'"
        }
        lappend ranked [list $number $path]
    }
    set seen [dict create]
    set details {}
    foreach entry [lsort -real -index 0 $ranked] {
        set body [detail [report_timing -of_objects [lindex $entry 1] -return_string]]
        if {[dict exists $seen $body]} { continue }
        dict set seen $body 1
        lappend details $body
        if {[llength $details] == $count} { break }
    }
    set stream [open $file w]
    try {
        puts $stream "Vivado bounded unique timing path diagnostic"
        puts $stream "delay_type=$delay_type requested=$count query_limit=$query_limit returned=[llength $paths] unique_reported=[llength $details]"
        puts $stream "Deduplication: identical native path-detail text; ordered by numerical slack."
        puts $stream "Bounded query; not a full path census or endpoint statistics. Use timing summary for WNS/TNS."
        if {[llength $paths] >= $query_limit} {
            puts $stream "QUERY LIMIT REACHED: results may omit paths; increase the bound to investigate."
        }
        if {[llength $details] < $count} {
            puts $stream "Fewer than requested unique paths were found within this query."
        }
        set index 0
        foreach body $details {
            puts $stream "\n===== Unique path [incr index] =====\n$body"
        }
    } finally { close $stream }
    return [dict create queried [llength $paths] reported [llength $details] \
        query_limit $query_limit limit_reached [expr {[llength $paths] >= $query_limit}]]
}
