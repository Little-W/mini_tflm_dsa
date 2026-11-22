# Rank the returned worst-slack path per endpoint by data-path delay.
# Do not filter on a rounded delay: the tool's -greater comparison can omit
# candidates even when their reported cell and net delays meet that threshold.
set paths [get_timing_paths -delay_type max -nworst 1 -max_paths 1000000]
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
puts $detail "Data-path delay ranking of returned maximum-delay analysis paths, one path per endpoint."
puts $detail "Candidate query: worst-slack path per endpoint, up to 1000000 paths per path group."
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
