if {![info exists TARGET_FREQ_MHZ]} {
    set TARGET_FREQ_MHZ 400.0
}

if {![info exists CLK_PERIOD_NS]} {
    set CLK_PERIOD_NS [expr 1000.0 / double($TARGET_FREQ_MHZ)]
}

set clk_name "CORE_CLK"
set clk_port "clk"
set rst_port "rst_n"

create_clock -name $clk_name [get_ports $clk_port] \
    -period $CLK_PERIOD_NS \
    -waveform [list 0 [expr $CLK_PERIOD_NS / 2.0]]

set setup_uncer [expr 0.10 * $CLK_PERIOD_NS]
set hold_uncer  [expr min(0.05 * $CLK_PERIOD_NS, 0.125)]

set_clock_uncertainty -setup $setup_uncer [get_clocks $clk_name]
set_clock_uncertainty -hold  $hold_uncer  [get_clocks $clk_name]
if {![string equal -nocase $COMPILE_MODE "drc"]} {
    set_fix_hold [get_clocks $clk_name]
}

set non_clock_inputs [remove_from_collection [all_inputs] [get_ports [list $clk_port $rst_port]]]
if {[sizeof_collection $non_clock_inputs] > 0} {
    set_input_delay -max [expr 0.20 * $CLK_PERIOD_NS] -clock [get_clocks $clk_name] $non_clock_inputs
    set_input_delay -min 0.0 -clock [get_clocks $clk_name] $non_clock_inputs
}

set outputs [all_outputs]
if {[sizeof_collection $outputs] > 0} {
    set_output_delay -max [expr 0.20 * $CLK_PERIOD_NS] -clock [get_clocks $clk_name] $outputs
    set_output_delay -min 0.0 -clock [get_clocks $clk_name] $outputs
}

set_false_path -from [get_ports $rst_port]
set_ideal_network [get_ports $rst_port]

set_max_area 0
set_max_fanout 32 [current_design]
