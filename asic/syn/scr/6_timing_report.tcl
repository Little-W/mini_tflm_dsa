report_qor > ${PROJ_TEMP}/${DESIGN_TOP}_qor.rpt
report_area > ${PROJ_TEMP}/${DESIGN_TOP}_area.rpt
report_area -hierarchy >> ${PROJ_TEMP}/${DESIGN_TOP}_area.rpt
report_design > ${PROJ_TEMP}/${DESIGN_TOP}_design.rpt
report_reference > ${PROJ_TEMP}/${DESIGN_TOP}_reference.rpt
report_constraints > ${PROJ_TEMP}/${DESIGN_TOP}_constraints.rpt
report_constraints -all_violators >> ${PROJ_TEMP}/${DESIGN_TOP}_constraints.rpt
report_timing -nets -input -transition_time -capacitance -nworst 10 \
    > ${PROJ_TEMP}/${DESIGN_TOP}_timing.rpt
report_power -hierarchy -verbose > ${PROJ_TEMP}/${DESIGN_TOP}_power.rpt
report_power >> ${PROJ_TEMP}/${DESIGN_TOP}_power.rpt
report_threshold_voltage_group > ${PROJ_TEMP}/${DESIGN_TOP}_cell_usage.rpt
sizeof_collection [get_cells -hierarchical] > ${PROJ_TEMP}/${DESIGN_TOP}_instances.rpt
report_clock_gating -verbose -ungated > ${PROJ_TEMP}/${DESIGN_TOP}_clock_gating.rpt

set worst_setup_slack "NA"
set timing_paths [get_timing_paths -max_paths 1 -nworst 1]
if {[sizeof_collection $timing_paths] > 0} {
    set path [index_collection $timing_paths 0]
    set worst_setup_slack [get_attribute $path slack]
}

set all_cells [sizeof_collection [get_cells -hierarchical]]
set result "UNKNOWN"
if {$worst_setup_slack ne "NA"} {
    if {$worst_setup_slack >= 0.0} {
        set result "PASS"
    } else {
        set result "FAIL"
    }
}

set summary_file ${PROJ_TEMP}/${DESIGN_TOP}_summary.rpt
set fd [open $summary_file w]
puts $fd "design: $DESIGN_TOP"
puts $fd "target_freq_mhz: $TARGET_FREQ_MHZ"
puts $fd "clock_period_ns: $CLK_PERIOD_NS"
puts $fd "compile_mode: $COMPILE_MODE"
puts $fd "parameters: $DESIGN_PARAMETERS"
puts $fd "worst_setup_slack_ns: $worst_setup_slack"
puts $fd "timing_result: $result"
puts $fd "instance_count: $all_cells"
puts $fd "output_dir: $PROJ_TEMP"
close $fd

puts "Summary written to $summary_file"
puts "timing_result: $result"
puts "worst_setup_slack_ns: $worst_setup_slack"
