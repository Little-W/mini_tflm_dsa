# Rank one maximum-delay path per endpoint, including paths with positive slack.
set initial_paths [get_timing_paths -delay_type max -nworst 1 -max_paths 100]
set initial_ranked {}
set initial_index 0
foreach cell_delay [get_attribute $initial_paths cell_delay] net_delay [get_attribute $initial_paths net_delay] {
    lappend initial_ranked [list [expr {$cell_delay+$net_delay}] $initial_index]
    incr initial_index
}
set initial_delays {}
set endpoints [dict create]
foreach entry [lsort -real -decreasing -index 0 $initial_ranked] {
    lassign $entry delay index
    set endpoint [get_object_name [get_attribute [index_collection $initial_paths $index] endpoint]]
    if {![dict exists $endpoints $endpoint]} {
        dict set endpoints $endpoint 1
        lappend initial_delays $delay
    }
}
set threshold [expr {max(0.0,[lindex $initial_delays [expr {min(99,[llength $initial_delays]-1)}]]-1e-9)}]
set paths [get_timing_paths -delay_type max -nworst 1 -max_paths 1000000 -greater $threshold]
if {[sizeof_collection $paths] < min(100,[llength $initial_delays])} {
    error "Timing path delay filter omitted required candidates"
}
set ranked {}
set index 0
set cell_delays [get_attribute $paths cell_delay]
set net_delays [get_attribute $paths net_delay]
foreach cell_delay $cell_delays net_delay $net_delays {
    lappend ranked [list [expr {$cell_delay + $net_delay}] $index]
    incr index
}
set ranked [lsort -real -decreasing -index 0 $ranked]
set csv [open ${PROJ_TEMP}/${DESIGN_TOP}_top100_delay.csv w]
puts $csv "rank,delay_ns,slack_ns,logic_depth,startpoint,endpoint,path_group"
set detail [open ${PROJ_TEMP}/${DESIGN_TOP}_top100_delay.rpt w]
puts $detail "Maximum data-path delay, one path per endpoint; all constrained endpoints are considered."
puts $detail "Candidate paths: [sizeof_collection $paths]"
set rank 0
set endpoints [dict create]
foreach entry $ranked {
    lassign $entry delay index
    set path [index_collection $paths $index]
    set endpoint [get_object_name [get_attribute $path endpoint]]
    if {[dict exists $endpoints $endpoint]} {continue}
    dict set endpoints $endpoint 1
    incr rank
    set start [get_object_name [get_attribute $path startpoint]]
    set end [get_object_name [get_attribute $path endpoint]]
    set group [get_object_name [get_attribute $path path_group]]
    set slack [get_attribute $path slack]
    set depth [get_attribute $path logic_depth]
    puts $csv "$rank,$delay,$slack,$depth,\"$start\",\"$end\",\"$group\""
    puts $detail "\nPath $rank: delay=$delay ns; slack=$slack ns; logic_depth=$depth"
    puts $detail "Startpoint: $start"
    puts $detail "Endpoint: $end"
    foreach_in_collection point [get_attribute $path points] {
        set object [get_attribute $point object]
        set name [get_object_name $object]
        set cell [get_cells -quiet -of_objects $object]
        set reference "port"
        if {[sizeof_collection $cell] > 0} {set reference [get_attribute [index_collection $cell 0] ref_name]}
        puts $detail "[get_attribute $point arrival]\t[ get_attribute $point delay]\t$name\t$reference"
    }
    if {$rank == 100} {break}
}
close $csv
close $detail
report_timing -delay_type max -nworst 1 -max_paths 100 -sort_by slack \
    -nets -input_pins -transition_time -capacitance -significant_digits 6 \
    > ${PROJ_TEMP}/${DESIGN_TOP}_top100_slack.rpt
puts "Ranked $rank paths by data-path delay from [sizeof_collection $paths] candidate paths"

if {[getenv_default DESIGN_EXTENDED_REPORTS 0]} {
    source [file join $PROJ_PATH scripts 8_endpoint_paths.tcl]
}
