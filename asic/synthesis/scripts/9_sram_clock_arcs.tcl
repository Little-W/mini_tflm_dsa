# 导出 SRAM 双时钟引脚、条件和库弧；全部操作保持现有时序约束。
namespace eval npu_sram_report {
    proc attribute {object name {fallback "NA"}} {
        if {[catch {get_attribute $object $name} value]} {return $fallback}
        return $value
    }
}

set arc_file [open ${PROJ_TEMP}/${DESIGN_TOP}_sram_clock_arcs.tsv w]
puts $arc_file "library_cell\tfrom_pin\tto_pin\ttiming_type\twhen\tstatus"
set pin_file [open ${PROJ_TEMP}/${DESIGN_TOP}_sram_clock_pins.tsv w]
puts $pin_file "instance\treference\tpin\tnets\tclocks\tcase_value"
set diagnostics [open ${PROJ_TEMP}/${DESIGN_TOP}_sram_clock_diagnostics.rpt w]
puts $diagnostics "SRAM CLKA/CLKB library arcs and design connectivity"
puts $diagnostics "Timing checks and clock uncertainty remain active."
set libraries [get_libs -quiet *RAMTP*]
puts $diagnostics "Memory library count: [sizeof_collection $libraries]"
foreach_in_collection library $libraries {
    set library_name [get_object_name $library]
    set report_name [string map [list / _ : _] $library_name]
    set report_path ${PROJ_TEMP}/${DESIGN_TOP}_${report_name}_timing_arcs.rpt
    if {[catch {redirect -file $report_path [list report_lib -timing_arcs $library_name]} message]} {
        puts $diagnostics "Library report unavailable for $library_name: $message"
    } else {
        puts $diagnostics "Library timing report: $report_path"
    }
    foreach_in_collection cell [get_lib_cells -quiet ${library_name}/*] {
        set cell_name [get_object_name $cell]
        foreach direction {{CLKA CLKB} {CLKB CLKA}} {
            lassign $direction from_name to_name
            set from_pin [get_lib_pins -quiet ${cell_name}/${from_name}]
            set to_pin [get_lib_pins -quiet ${cell_name}/${to_name}]
            if {[sizeof_collection $from_pin] == 0 || [sizeof_collection $to_pin] == 0} {
                puts $arc_file "$cell_name\t$from_name\t$to_name\tNA\tNA\tPIN_UNAVAILABLE"
                continue
            }
            if {[llength [info commands get_lib_timing_arcs]] == 0} {
                puts $arc_file "$cell_name\t$from_name\t$to_name\tNA\tNA\tSEE_LIBRARY_REPORT"
                continue
            }
            if {[catch {get_lib_timing_arcs -from $from_pin -to $to_pin} arcs]} {
                puts $arc_file "$cell_name\t$from_name\t$to_name\tNA\tNA\tSEE_LIBRARY_REPORT"
                puts $diagnostics "Arc query unavailable for $cell_name $from_name->$to_name: $arcs"
                continue
            }
            if {[sizeof_collection $arcs] == 0} {
                puts $arc_file "$cell_name\t$from_name\t$to_name\tNA\tNA\tNO_DIRECT_ARC"
            }
            foreach_in_collection arc $arcs {
                puts $arc_file "$cell_name\t$from_name\t$to_name\t[npu_sram_report::attribute $arc timing_type]\t[npu_sram_report::attribute $arc when]\tEXPORTED"
            }
        }
    }
}
foreach_in_collection cell [get_cells -hierarchical -filter {ref_name =~ RAMTP*}] {
    set name [get_object_name $cell]
    set reference [get_attribute $cell ref_name]
    set clock_nets [dict create]
    foreach pin_name {CLKA CLKB COLLDISN} {
        set pins [get_pins -quiet ${name}/${pin_name}]
        if {[sizeof_collection $pins] == 0} {continue}
        set nets [get_object_name [get_nets -quiet -of_objects $pins]]
        set clocks "NA"
        if {$pin_name ne "COLLDISN"} {
            dict set clock_nets $pin_name $nets
            if {![catch {get_clocks -quiet -of_objects $pins} pin_clocks]} {
                set clocks [get_object_name $pin_clocks]
            }
        }
        puts $pin_file "$name\t$reference\t$pin_name\t$nets\t$clocks\t[npu_sram_report::attribute $pins case_value]"
    }
    if {[dict exists $clock_nets CLKA] && [dict exists $clock_nets CLKB]} {
        puts $diagnostics "${name}: CLKA/CLKB same net = [expr {[dict get $clock_nets CLKA] eq [dict get $clock_nets CLKB]}]"
    }
}
close $arc_file
close $pin_file
close $diagnostics
