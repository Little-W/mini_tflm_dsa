proc getenv_default {name default_value} {
    if {[info exists ::env($name)] && $::env($name) ne ""} {
        return $::env($name)
    }
    return $default_value
}

set MAX_CORES [getenv_default MAX_CORES 1]
set_host_options -max_cores $MAX_CORES
report_host_options

set INTERRUPT          [getenv_default INTERRUPT 0]
set DCT                [getenv_default DCT 0]

set DATE               [getenv_default DATE ""]
set PROJ               [getenv_default PROJ "tflm_ai_dsa"]
set PROJ_PATH          [getenv_default PROJ_PATH "."]
set PROJ_ROOT          [getenv_default PROJ_ROOT "../.."]
set ASIC_ROOT          [getenv_default ASIC_ROOT ".."]
set PRJ_HOME           [getenv_default PRJ_HOME $ASIC_ROOT]
set PROJ_TEMP          [getenv_default PROJ_TEMP "./output/default"]

set RTL_ROOT           [getenv_default RTL_ROOT "../../rtl"]
set INC_ROOT           [getenv_default INC_ROOT "../../inc"]
set DESIGN_FILELIST    [getenv_default DESIGN_FILELIST "${ASIC_ROOT}/filelist/npu_top.f"]

set postCTS            [getenv_default postCTS 0]
set enableDFT          [getenv_default enableDFT 0]
set clockGate          [getenv_default clockGate 0]

set DESIGN             [getenv_default DESIGN "npu_top"]
set DESIGN_TOP         [getenv_default DESIGN_TOP $DESIGN]
set DESIGN_PARAMETERS  [getenv_default DESIGN_PARAMETERS ""]

set DESIGN_SYN_SDC     [getenv_default DESIGN_SYN_SDC "${ASIC_ROOT}/sdc/${DESIGN_TOP}_400m.sdc"]

set TARGET_FREQ_MHZ    [getenv_default TARGET_FREQ_MHZ 400.0]
set CLK_PERIOD_NS      [expr 1000.0 / double($TARGET_FREQ_MHZ)]
set COMPILE_MODE       [getenv_default COMPILE_MODE "ultra"]

set DW_DB_PATH         [getenv_default DW_DB_PATH ""]
set STD_DB_PATH        [getenv_default STD_DB_PATH ""]
set STD_DB_LIST        [getenv_default STD_DB_LIST ""]
set SYNC_DB_PATH       [getenv_default SYNC_DB_PATH $STD_DB_PATH]
set SYNC_DB_LIST       [getenv_default SYNC_DB_LIST $STD_DB_LIST]
set MEM_DB_PATH        [getenv_default MEM_DB_PATH ""]
set MEM_DB_LIST        [getenv_default MEM_DB_LIST ""]
set IO_DB_PATH         [getenv_default IO_DB_PATH ""]
set IO_DB_LIST         [getenv_default IO_DB_LIST ""]
set LPK_DB_PATH        [getenv_default LPK_DB_PATH ""]
set LPK_DB_LIST        [getenv_default LPK_DB_LIST ""]
set AFE_DB_PATH        [getenv_default AFE_DB_PATH ""]
set AFE_DB_LIST        [getenv_default AFE_DB_LIST ""]

set PROCE              [getenv_default PROCE "gscl45nm"]
set CORNER             [getenv_default SYN_CONER ""]
set std_db_name        "${PROCE}_${CORNER}"
set std_lib_name       [getenv_default SYN_STD_LIB_NAME "gscl45nm"]
set std_operating_condition [getenv_default SYN_OPER_CONDITION "typical"]

set flow "syn"

set verilogout_show_unconnected_pins true
set verilogout_no_tri true
set hdlin_auto_save_templates true
set hdlin_enable_rtldrc_info true
set hdlin_vrlg_std "2001"
set hdlin_sv_enable_rtl_attributes true
set power_preserve_rtl_hier_names true
set hdlin_shorten_long_module_name true
set hdlin_module_name_limit 256

file mkdir $PROJ_TEMP

puts "ASIC synthesis setup:"
puts "  top              = $DESIGN_TOP"
puts "  target_freq_mhz  = $TARGET_FREQ_MHZ"
puts "  clk_period_ns    = $CLK_PERIOD_NS"
puts "  rtl_root         = $RTL_ROOT"
puts "  filelist         = $DESIGN_FILELIST"
puts "  parameters       = $DESIGN_PARAMETERS"
puts "  output           = $PROJ_TEMP"
