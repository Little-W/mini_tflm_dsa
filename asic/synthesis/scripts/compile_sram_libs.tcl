source library_config.tcl
foreach cell {RAMTP128X16 RAMTP1024X16} {
    set name ${cell}_tt_1p10v_1p10v_25c
    set source [file join $sram_root $cell lib ${name}.lib]
    if {![file exists $source]} { error "Missing SRAM timing library: $source" }
    read_lib $source
    write_lib $name -format db -output [file join [pwd] ${name}.db]
}
exit
