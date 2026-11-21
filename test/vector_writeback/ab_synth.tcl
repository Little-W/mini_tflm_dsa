read_verilog -sv [lindex $argv 0]
synth_design -top vector_writeback -part xc7a200tfbg484-3 -flatten_hierarchy rebuilt
report_utilization -file [lindex $argv 1]
exit
