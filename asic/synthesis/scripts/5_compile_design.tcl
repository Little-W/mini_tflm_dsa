set_fix_multiple_port_nets -all -exclude_clock_network
set_app_var dc_allow_rtl_pg true

if {[getenv_default DESIGN_REPORT_ONLY 0] == 0} {
set incremental [getenv_default DESIGN_INCREMENTAL 0]
if {$incremental} {
    set hierarchy [get_cells -hierarchical -filter {is_hierarchical == true}]
    if {[sizeof_collection $hierarchy]>0} {set_dont_touch $hierarchy false}
}
if {[string equal -nocase $COMPILE_MODE "drc"]} {
    puts "Running mapped design rule optimization"
    compile -only_design_rule
} elseif {[string equal -nocase $COMPILE_MODE "hold"]} {
    puts "Running mapped hold-time optimization"
    compile -only_hold_time
} elseif {[string equal -nocase $COMPILE_MODE "quick"]} {
    puts "Running low-effort compile"
    if {$incremental} {
        compile -incremental_mapping -map_effort medium -area_effort low -power_effort none
    } else {
        compile -map_effort medium -area_effort low -power_effort none
    }
} elseif {[string equal -nocase $COMPILE_MODE "ultra"]} {
    puts "Running compile_ultra"
    if {$incremental} {compile_ultra -incremental -no_autoungroup} else {compile_ultra -no_autoungroup}
} else {
    puts "Running compile"
    if {$incremental} {
        compile -incremental_mapping -map_effort high -area_effort medium -power_effort none
    } else {
        compile -map_effort high -area_effort medium -power_effort none
    }
}

}

change_names -rules verilog -verbose -hierarchy

check_design > ${PROJ_TEMP}/${DESIGN_TOP}_check_design.rpt
check_timing > ${PROJ_TEMP}/${DESIGN_TOP}_check_timing.rpt

write -f verilog -hierarchy -o ${PROJ_TEMP}/${DESIGN_TOP}_syn.vg
write -f ddc -hierarchy -o ${PROJ_TEMP}/${DESIGN_TOP}_syn.ddc
write_sdc ${PROJ_TEMP}/${DESIGN_TOP}_syn.sdc

report_timing -nets -input -transition_time -capacitance -nworst 10 \
    > ${PROJ_TEMP}/${DESIGN_TOP}_before_report_timing.rpt
