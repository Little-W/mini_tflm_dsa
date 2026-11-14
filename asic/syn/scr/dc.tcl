#--------------------------------------------
# Common setup
#--------------------------------------------
set PROJ_PATH [getenv PROJ_PATH]
source -e -v ${PROJ_PATH}/scr/1_common_setup.tcl

#--------------------------------------------
# Library setup
#--------------------------------------------
source -e -v ${PROJ_PATH}/scr/2_dc_setup.tcl

#--------------------------------------------
# Parse design
#--------------------------------------------
source -e -v ${PROJ_PATH}/scr/3_read_design.tcl

#--------------------------------------------
# Constraints
#--------------------------------------------
source -e -v ${DESIGN_SYN_SDC}

#--------------------------------------------
# Design environment
#--------------------------------------------
source -e -v ${PROJ_PATH}/scr/4_design_environment.tcl

#--------------------------------------------
# Compile
#--------------------------------------------
source -e -v ${PROJ_PATH}/scr/5_compile_design.tcl

#--------------------------------------------
# Reports
#--------------------------------------------
source -e -v ${PROJ_PATH}/scr/6_timing_report.tcl

if {$INTERRUPT != 1} {
    exit
}
