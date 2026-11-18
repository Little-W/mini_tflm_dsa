file mkdir ${PROJ_TEMP}/work
define_design_lib work -path "${PROJ_TEMP}/work"

set_svf ${PROJ_TEMP}/${DESIGN_TOP}.svf
set_app_var simplified_verification_mode true

puts "#------------------------------------------"
puts "Read RTL:"
puts "  $DESIGN_FILELIST"
puts "#------------------------------------------"

set checkpoint [getenv_default DESIGN_CHECKPOINT ""]
if {$checkpoint ne ""} {
    read_ddc $checkpoint
    set top_designs [filter_collection [get_designs *] {is_hierarchical == true}]
    set found_top ""
    foreach_in_collection candidate $top_designs {
        set name [get_object_name $candidate]
        if {$name eq $DESIGN_TOP || [string match "*${DESIGN_TOP}_h_*" $name]} {set found_top $name; break}
    }
    if {$found_top eq ""} {error "Checkpoint does not contain the requested top design"}
    current_design $found_top
    if {[sizeof_collection [all_clocks]] > 0} {remove_clock [all_clocks]}
} else {
set generated_f [file join $PROJ_TEMP sources.f]
set out [open $generated_f w]
set in [open $DESIGN_FILELIST r]
while {[gets $in line] >= 0} {
    set line [string trim $line]
    if {$line eq "" || [string index $line 0] eq "#"} { continue }
    if {[string match "+incdir+*" $line]} {
        puts $out "+incdir+[file normalize [file join $PROJ_PATH [string range $line 8 end]]]"
    } else {
        puts $out [file normalize [file join $PROJ_PATH $line]]
    }
}
close $in
puts $out [file join $PROJ_ROOT asic rtl smic40_sram_1r1w.sv]
close $out
set extra_defines [getenv_default DESIGN_RTL_DEFINES ""]
set vcs_options "$extra_defines +define+SYNTHESIS +define+ASIC_SYNTHESIS +define+ASIC_SRAM +incdir+${RTL_ROOT} +incdir+${INC_ROOT} -f ${generated_f}"
if {![analyze -vcs $vcs_options -format sverilog]} { error "RTL analysis failed" }

if {$DESIGN_PARAMETERS ne ""} {
    if {![elaborate ${DESIGN_TOP} -parameters $DESIGN_PARAMETERS]} { error "RTL elaboration failed" }
} else {
    if {![elaborate ${DESIGN_TOP}]} { error "RTL elaboration failed" }
}

}

set ELAB_DESIGN [get_object_name [current_design]]
puts "Elaborated design: $ELAB_DESIGN"

write -f ddc -hierarchy -o ${PROJ_TEMP}/${DESIGN_TOP}_elab.ddc

set uniquify_naming_style "${DESIGN_TOP}_%s_%d"
if {[getenv_default DESIGN_FORCE_UNIQUIFY 0]} {
    uniquify -force
}

if {![link]} { error "Design contains unresolved references" }
check_design > ${PROJ_TEMP}/${DESIGN_TOP}_check_design_elab.rpt
set macro_cells [get_cells -hierarchical -filter {ref_name =~ RAMTP*}]
set macro_count [sizeof_collection $macro_cells]
set macro_report [open ${PROJ_TEMP}/${DESIGN_TOP}_sram_instances.rpt w]
puts $macro_report "SRAM macro instances: $macro_count"
foreach_in_collection cell $macro_cells {
    puts $macro_report "[get_object_name $cell] [get_attribute $cell ref_name]"
}
close $macro_report
if {$macro_count == 0} { error "No SRAM macro instances were linked" }
