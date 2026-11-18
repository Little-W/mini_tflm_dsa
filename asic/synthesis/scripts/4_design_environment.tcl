set ports_clock_root [get_ports clk]
group_path -name REGOUT -to [all_outputs]
group_path -name REGIN -from [remove_from_collection [all_inputs] $ports_clock_root]
group_path -name FEEDTHROUGH \
    -from [remove_from_collection [all_inputs] $ports_clock_root] \
    -to [all_outputs]

set_operating_conditions $std_operating_condition -library [get_libs ${std_lib_name}]
set timing_enable_multiple_clocks_per_reg true

set auto_wire_load_selection true
set_wire_load_mode top
set_max_area 0
