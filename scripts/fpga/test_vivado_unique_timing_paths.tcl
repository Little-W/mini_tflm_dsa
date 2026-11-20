source [file join [file dirname [info script]] .. .. fpga vivado tflm_ai_dsa_soc scripts vivado_unique_timing_paths.tcl]
proc assert {condition message} { if {![uplevel 1 [list expr $condition]]} { error $message } }
proc get_timing_paths {args} { return {a b c d} }
proc get_property {property path} {
    return [dict get {a 2.0 b -1.0 c -1.0 d 0.0} $path]
}
proc report_timing {args} {
    set path [lindex $args 1]
    set label [dict get {a later b same c same d distinct} $path]
    return "header [clock clicks]\nSlack (MET) : $label\nfull path detail"
}
set output [file join /tmp test_vivado_unique_[pid].rpt]
try {
    set result [unique_timing_paths::write $output max 3 4]
    assert {[dict get $result reported] == 3} "wrong deduplicated count"
    assert {[dict get $result limit_reached]} "missing query limit indication"
    set stream [open $output r]; set text [read $stream]; close $stream
    assert {[string first {Slack (MET) : same} $text] < [string first {Slack (MET) : distinct} $text]} "incorrect slack ordering"
    assert {[string first {Slack (MET) : distinct} $text] < [string first {Slack (MET) : later} $text]} "incorrect slack ordering"
    assert {[regexp -all {Slack \(MET\) : same} $text] == 1} "duplicates remain"
    assert {[string first {QUERY LIMIT REACHED} $text] >= 0} "limit warning absent"
    assert {[catch {unique_timing_paths::write $output max 5 4}]} "invalid bounds accepted"
    assert {[catch {unique_timing_paths::detail {missing slack}}]} "invalid report accepted"
} finally { file delete $output }
puts "unique timing path tests passed"
