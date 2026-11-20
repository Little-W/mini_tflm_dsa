# 在已打开的 Vivado 综合网表中导出阵列 DSP 属性和 B 输入的真实连接。
namespace eval pe_dsp_boundary {
    variable script_dir [file dirname [file normalize [info script]]]
}

proc pe_dsp_boundary::check {out_dir cell_pattern {size 16} {maximum 0} {maximum_b_cells 9}} {
    variable script_dir
    file mkdir $out_dir
    set cells_file [file join $out_dir dsp_cells.tsv]
    set all_cells_file [file join $out_dir all_dsp_cells.tsv]
    set edges_file [file join $out_dir dsp_connections.tsv]
    set cells [get_cells -quiet -hierarchical -filter {REF_NAME == DSP48E1}]
    set selected [list]
    foreach cell $cells {
        if {[string match $cell_pattern [get_property NAME $cell]]} {
            lappend selected $cell
        }
    }
    if {[llength $selected] == 0} { error "No array DSP48E1 cells match $cell_pattern" }
    set cells_stream [open $cells_file w]
    set all_cells_stream [open $all_cells_file w]
    set header "name\tb_input\tbreg\tbcascreg\tareg\tacascreg\tmreg\tpreg"
    puts $cells_stream $header
    puts $all_cells_stream $header
    foreach cell $cells {
        set row [list [get_property NAME $cell]]
        foreach property {B_INPUT BREG BCASCREG AREG ACASCREG MREG PREG} {
            set value [get_property $property $cell]
            if {$value eq ""} {
                close $cells_stream
                close $all_cells_stream
                error "Missing DSP property $property on $cell"
            }
            lappend row $value
        }
        puts $all_cells_stream [join $row "\t"]
        if {$cell in $selected} { puts $cells_stream [join $row "\t"] }
    }
    close $cells_stream
    close $all_cells_stream
    set edges_stream [open $edges_file w]
    puts $edges_stream "source\ttarget\tport\tsource_pin\ttarget_pin"
    foreach cell $selected {
        set port [expr {[get_property B_INPUT $cell] eq "CASCADE" ? "BCIN" : "B"}]
        foreach input_pin [get_pins -quiet -of_objects $cell -filter {DIRECTION == IN}] {
            set ref_pin [get_property REF_PIN_NAME $input_pin]
            if {![regexp {^([A-Z]+)\[[0-9]+\]$} $ref_pin unused pin_port] || $pin_port ne $port} { continue }
            set nets [get_nets -quiet -segments -of_objects $input_pin]
            if {[llength $nets] == 0} { continue }
            foreach driver [get_pins -quiet -leaf -of_objects $nets -filter {DIRECTION == OUT}] {
                if {![regexp {^BCOUT\[[0-9]+\]$} [get_property REF_PIN_NAME $driver]]} { continue }
                set owner [get_cells -quiet -of_objects $driver]
                if {[llength $owner] != 1 || [get_property REF_NAME $owner] ne "DSP48E1"} { continue }
                puts $edges_stream [join [list [get_property NAME $owner] [get_property NAME $cell] \
                    $port [get_property NAME $driver] [get_property NAME $input_pin]] "\t"]
            }
        }
    }
    close $edges_stream
    set command [list python3 [file join $script_dir check.py] --cells $cells_file \
        --connections $edges_file --size $size --max-cross-pe-bypass $maximum \
        --max-b-dsp-cells $maximum_b_cells \
        --all-cells $all_cells_file \
        --out [file join $out_dir dsp_b_cascade.json]]
    if {[catch {exec {*}$command 2>@1} result]} {
        puts $result
        error "Array DSP B cascade check failed; see $out_dir"
    }
    puts $result
}
