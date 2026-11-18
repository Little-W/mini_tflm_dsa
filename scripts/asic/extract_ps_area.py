#!/usr/bin/env python3
"""Count mapped leaf cells and SRAM capacity in a synthesized NPU DDC."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess

TCL = r'''
set sh_continue_on_error false
foreach variable {DESIGN_COST_STD_DB DESIGN_COST_MEM128 DESIGN_COST_MEM1024} {
    read_db $env($variable)
}
set_app_var link_library [list * $env(DESIGN_COST_STD_DB) $env(DESIGN_COST_MEM128) $env(DESIGN_COST_MEM1024)]
read_ddc $env(DESIGN_COST_DDC)
current_design $env(DESIGN_COST_TOP)
if {![link]} {error "Unresolved mapped cells"}
set leaves [get_cells -hierarchical -filter {is_hierarchical == false}]
set names [get_object_name $leaves]
set references [get_attribute $leaves ref_name]
array set totals {total_area_um2 0 standard_area_um2 0 sequential_area_um2 0 combinational_area_um2 0
    macro_area_um2 0 macro_bytes 0 macro_count 0 leaf_count 0 constant_nodes 0 ps_standard_area_um2 0
    encoder_area_um2 0 decoder_area_um2 0 directory_area_um2 0 ps_macro_area_um2 0}
set cache [dict create]
foreach name $names reference $references {
    if {[regexp {^\*\*logic_[01zxZX]\*\*$} $reference]} {
        incr totals(constant_nodes)
        continue
    }
    if {![dict exists $cache $reference]} {
        set library_cell [get_lib_cells -quiet */$reference]
        if {[sizeof_collection $library_cell] != 1} {error "Ambiguous cell $reference"}
        dict set cache $reference [list [get_attribute $library_cell area] [get_attribute $library_cell is_sequential]]
    }
    lassign [dict get $cache $reference] area sequential
    set totals(total_area_um2) [expr {$totals(total_area_um2)+$area}]
    incr totals(leaf_count)
    set store [string match {*u_ps_buffer*g_compressed*u_store/*} $name]
    if {[regexp {^RAMTP([0-9]+)X([0-9]+)$} $reference ignored depth width]} {
        incr totals(macro_count)
        incr totals(macro_bytes) [expr {$depth*$width/8}]
        set totals(macro_area_um2) [expr {$totals(macro_area_um2)+$area}]
        if {$store} {set totals(ps_macro_area_um2) [expr {$totals(ps_macro_area_um2)+$area}]}
        if {[string match {*u_store/u_directory_ram/*} $name]} {
            set totals(directory_area_um2) [expr {$totals(directory_area_um2)+$area}]
        }
    } else {
        set totals(standard_area_um2) [expr {$totals(standard_area_um2)+$area}]
        if {$sequential} {set type sequential_area_um2} else {set type combinational_area_um2}
        set totals($type) [expr {$totals($type)+$area}]
        if {$store} {set totals(ps_standard_area_um2) [expr {$totals(ps_standard_area_um2)+$area}]}
        foreach part {encoder decoder} {
            if {[string match "*u_store/u_${part}/*" $name]} {
                set totals(${part}_area_um2) [expr {$totals(${part}_area_um2)+$area}]
            }
        }
    }
}
set output [open $env(DESIGN_COST_JSON) w]
puts $output "\{"
set separator ""
foreach key [lsort [array names totals]] {
    puts -nonewline $output "$separator  \"$key\": $totals($key)"
    set separator ",\n"
}
puts $output "\n\}"
close $output
exit
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--std-db',type=Path,required=True)
    parser.add_argument('--libs',type=Path,required=True)
    parser.add_argument('--ddc',type=Path,help='Mapped module DDC; defaults to the complete NPU checkpoint')
    parser.add_argument('--top',help='Root design name for module-level area inspection')
    args=parser.parse_args();directory=args.run.resolve()
    directory.mkdir(parents=True,exist_ok=True)
    if args.top:
        top=args.top
    else:
        source=(directory/'synthesis.log').read_text()
        match=re.search(r'Elaborated design: (\w+)',source)
        if not match:parser.error('Specify --top for a standalone mapped module')
        top=match[1]
    script=directory/'extract_ps_area.tcl';script.write_text(TCL)
    env=os.environ.copy()
    env.update(DESIGN_COST_STD_DB=str(args.std_db.resolve()),
        DESIGN_COST_MEM128=str(args.libs.resolve()/'RAMTP128X16_tt_1p10v_1p10v_25c.db'),
        DESIGN_COST_MEM1024=str(args.libs.resolve()/'RAMTP1024X16_tt_1p10v_1p10v_25c.db'),
        DESIGN_COST_DDC=str(args.ddc.resolve() if args.ddc else directory/'npu_top_syn.ddc'),DESIGN_COST_TOP=top,
        DESIGN_COST_JSON=str(directory/'cell_cost.json'))
    result=subprocess.run(['dc_shell','-f',str(script)],cwd=directory,env=env,
                          stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    (directory/'extract_ps_area.log').write_text(result.stdout)
    if result.returncode or any(line.startswith('Error:') for line in result.stdout.splitlines()):
        raise RuntimeError('Mapped-cell extraction failed; see extract_ps_area.log')
    values=json.loads((directory/'cell_cost.json').read_text())
    print(json.dumps(values,sort_keys=True))


if __name__=='__main__':
    main()
