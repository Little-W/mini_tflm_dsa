# 每个端点保留最差裕量路径，建立时间与保持时间分别导出。
namespace eval npu_endpoint_report {
    proc quoted {value} {
        return "\"[string map [list \" \"\"] $value]\""
    }

    proc attribute {object name {fallback "NA"}} {
        if {[catch {get_attribute $object $name} value]} {return $fallback}
        return $value
    }

    proc export {delay_type requested prefix coverage} {
        set limit $requested
        set ceiling [expr {max(1000000,$requested)}]
        set selected {}
        set examined 0
        set exhausted 0
        while {1} {
            set paths [get_timing_paths -delay_type $delay_type -nworst 1 -max_paths $limit]
            set examined [sizeof_collection $paths]
            set ranked {}
            set index 0
            foreach_in_collection path $paths {
                lappend ranked [list [get_attribute $path slack] $index]
                incr index
            }
            set endpoints [dict create]
            set selected {}
            foreach entry [lsort -real -increasing -index 0 $ranked] {
                set index [lindex $entry 1]
                set path [index_collection $paths $index]
                set endpoint [get_object_name [get_attribute $path endpoint]]
                if {[dict exists $endpoints $endpoint]} {continue}
                dict set endpoints $endpoint 1
                lappend selected $index
                if {[llength $selected] >= $requested} {break}
            }
            set exhausted [expr {$examined < $limit}]
            if {[llength $selected] >= $requested || $exhausted || $limit >= $ceiling} {break}
            set limit [expr {min($ceiling,2*$limit)}]
        }
        set csv [open ${prefix}.csv w]
        puts $csv "rank,slack_ns,data_delay_ns,logic_depth,startpoint,endpoint,path_group"
        set detail [open ${prefix}.rpt w]
        puts $detail "Delay type: $delay_type"
        puts $detail "Requested distinct endpoints: $requested"
        puts $detail "Exported distinct endpoints: [llength $selected]"
        puts $detail "Examined paths: $examined"
        puts $detail "Candidate search exhausted: $exhausted"
        set rank 0
        foreach index $selected {
            set path [index_collection $paths $index]
            incr rank
            set start [get_object_name [get_attribute $path startpoint]]
            set endpoint [get_object_name [get_attribute $path endpoint]]
            set group [get_object_name [get_attribute $path path_group]]
            set slack [get_attribute $path slack]
            set cell_delay [attribute $path cell_delay]
            set net_delay [attribute $path net_delay]
            set delay "NA"
            if {[string is double -strict $cell_delay] && [string is double -strict $net_delay]} {
                set delay [expr {$cell_delay+$net_delay}]
            }
            set depth [attribute $path logic_depth]
            puts $csv "$rank,$slack,$delay,$depth,[quoted $start],[quoted $endpoint],[quoted $group]"
            puts $detail "\nPath $rank: slack=$slack ns; data_delay=$delay ns; logic_depth=$depth"
            puts $detail "Startpoint: $start"
            puts $detail "Endpoint: $endpoint"
            puts $detail "Path group: $group"
            puts $detail "arrival_ns\tincrement_ns\tobject\treference"
            foreach_in_collection point [get_attribute $path points] {
                set object [get_attribute $point object]
                set cells [get_cells -quiet -of_objects $object]
                set reference "port"
                if {[sizeof_collection $cells] > 0} {
                    set reference [get_attribute [index_collection $cells 0] ref_name]
                }
                puts $detail "[attribute $point arrival]\t[attribute $point delay]\t[get_object_name $object]\t$reference"
            }
        }
        close $csv
        close $detail
        puts $coverage "$delay_type\t$requested\t[llength $selected]\t$examined\t$exhausted"
        puts "Exported [llength $selected] distinct $delay_type endpoints to ${prefix}.rpt"
    }
}

set setup_path_count [getenv_default DESIGN_SETUP_PATH_COUNT 5000]
set hold_path_count [getenv_default DESIGN_HOLD_PATH_COUNT 5000]
if {$setup_path_count < 1 || $hold_path_count < 1} {error "Timing path counts must be positive"}
set coverage [open ${PROJ_TEMP}/${DESIGN_TOP}_path_coverage.tsv w]
puts $coverage "delay_type\trequested\texported\texamined\texhausted"
npu_endpoint_report::export max $setup_path_count ${PROJ_TEMP}/${DESIGN_TOP}_setup_paths $coverage
npu_endpoint_report::export min $hold_path_count ${PROJ_TEMP}/${DESIGN_TOP}_hold_paths $coverage
close $coverage

report_timing -delay_type max -nworst 1 -max_paths $setup_path_count -sort_by slack \
    -nets -input_pins -transition_time -capacitance -significant_digits 6 \
    > ${PROJ_TEMP}/${DESIGN_TOP}_setup_paths_full.rpt
report_timing -delay_type min -nworst 1 -max_paths $hold_path_count -sort_by slack \
    -nets -input_pins -transition_time -capacitance -significant_digits 6 \
    > ${PROJ_TEMP}/${DESIGN_TOP}_hold_paths_full.rpt

source [file join $PROJ_PATH scripts 9_sram_clock_arcs.tcl]
