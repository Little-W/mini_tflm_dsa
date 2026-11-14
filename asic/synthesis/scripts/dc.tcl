set sh_continue_on_error false
#--------------------------------------------
# Common setup
#--------------------------------------------
set PROJ_PATH [getenv PROJ_PATH]
source -e -v ${PROJ_PATH}/scripts/1_common_setup.tcl

#--------------------------------------------
# Library setup
#--------------------------------------------
source -e -v ${PROJ_PATH}/scripts/2_dc_setup.tcl

#--------------------------------------------
# Parse design
#--------------------------------------------
source -e -v ${PROJ_PATH}/scripts/3_read_design.tcl

if {[getenv_default DESIGN_ELAB_ONLY 0] == 1} {
    report_reference > ${PROJ_TEMP}/${DESIGN_TOP}_elab_references.rpt
    exit
}

#--------------------------------------------
# Constraints
#--------------------------------------------
source -e -v ${DESIGN_SYN_SDC}

#--------------------------------------------
# Design environment
#--------------------------------------------
source -e -v ${PROJ_PATH}/scripts/4_design_environment.tcl

#--------------------------------------------
# Compile
#--------------------------------------------
source -e -v ${PROJ_PATH}/scripts/5_compile_design.tcl

#--------------------------------------------
# Reports
#--------------------------------------------
source -e -v ${PROJ_PATH}/scripts/6_timing_report.tcl

if {$INTERRUPT != 1} {
    exit
}
