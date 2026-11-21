# Standalone predictor comparison on the SoC target, without timing claims.
set root [file normalize [lindex $argv 0]]
set predictor [file normalize [lindex $argv 1]]
set out [file normalize [lindex $argv 2]]
file mkdir $out
read_verilog -sv [list $root/rtl/npu/conv/conv_im2col_pkg.sv $root/rtl/common/onehot_check.sv $predictor]
synth_design -top conv_next_use_predictor -part xc7a200tfbg484-3 -flatten_hierarchy rebuilt
report_utilization -file $out/utilization.rpt
write_checkpoint -force $out/predictor.dcp
