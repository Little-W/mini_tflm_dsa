file mkdir WORK
define_design_lib work -path "./WORK"

set_svf ${PROJ_TEMP}/${DESIGN_TOP}.svf
set_app_var simplified_verification_mode true

puts "#------------------------------------------"
puts "Read RTL:"
puts "  $DESIGN_FILELIST"
puts "#------------------------------------------"

set vcs_options "+define+SYNTHESIS +define+ASIC_SYNTHESIS +incdir+${RTL_ROOT} +incdir+${INC_ROOT} -f ${DESIGN_FILELIST}"
analyze -vcs $vcs_options -format sverilog

if {$DESIGN_PARAMETERS ne ""} {
    elaborate ${DESIGN_TOP} -parameters $DESIGN_PARAMETERS
} else {
    elaborate ${DESIGN_TOP}
}

set ELAB_DESIGN [get_object_name [current_design]]
puts "Elaborated design: $ELAB_DESIGN"

write -f ddc -hierarchy -o ${PROJ_TEMP}/${DESIGN_TOP}_elab.ddc

set uniquify_naming_style "${DESIGN_TOP}_%s_%d"
uniquify -force

link
check_design > ${PROJ_TEMP}/${DESIGN_TOP}_check_design_elab.rpt
