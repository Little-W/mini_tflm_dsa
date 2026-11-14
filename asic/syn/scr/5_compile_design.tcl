set_fix_multiple_port_nets -all -exclude_clock_network
set_app_var dc_allow_rtl_pg true

if {[string equal -nocase $COMPILE_MODE "ultra"]} {
    puts "Running compile_ultra"
    compile_ultra -no_autoungroup
} else {
    puts "Running compile"
    compile -map_effort high -area_effort medium -power_effort none
}

change_names -rules verilog -verbose -hierarchy

check_design > ${PROJ_TEMP}/${DESIGN_TOP}_check_design.rpt
check_timing > ${PROJ_TEMP}/${DESIGN_TOP}_check_timing.rpt

write -f verilog -hierarchy -o ${PROJ_TEMP}/${DESIGN_TOP}_syn.vg
write -f ddc -hierarchy -o ${PROJ_TEMP}/${DESIGN_TOP}_syn.ddc
write_sdc ${PROJ_TEMP}/${DESIGN_TOP}_syn.sdc

report_timing -nets -input -transition_time -capacitance -nworst 10 \
    > ${PROJ_TEMP}/${DESIGN_TOP}_before_report_timing.rpt
