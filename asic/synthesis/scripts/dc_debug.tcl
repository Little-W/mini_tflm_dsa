set PROJ_PATH [getenv PROJ_PATH]
source -e -v ${PROJ_PATH}/scripts/1_common_setup.tcl
source -e -v ${PROJ_PATH}/scripts/2_dc_setup.tcl
source -e -v ${PROJ_PATH}/scripts/3_read_design.tcl

if {$INTERRUPT != 1} {
    exit
}
