proc create_tflm_soc_clk_wiz {core_clk_mhz} {
    set ip_name clk_wiz_0
    set input_clk_mhz 50.000
    set input_clk_period_ns 20.000

    if {[llength [get_ips -quiet $ip_name]] == 0} {
        create_ip -name clk_wiz -vendor xilinx.com -library ip -module_name $ip_name
    }

    set core_clk_mhz_fmt [format "%.3f" [expr {double($core_clk_mhz)}]]
    set ip_obj [get_ips $ip_name]

    set_property -dict [list \
        CONFIG.PRIM_SOURCE {Single_ended_clock_capable_pin} \
        CONFIG.PRIM_IN_FREQ [format "%.3f" $input_clk_mhz] \
        CONFIG.PRIM_IN_TIMEPERIOD [format "%.3f" $input_clk_period_ns] \
        CONFIG.CLKIN1_JITTER_PS {200.000} \
        CONFIG.USE_RESET {true} \
        CONFIG.RESET_TYPE {ACTIVE_HIGH} \
        CONFIG.RESET_PORT {reset} \
        CONFIG.USE_LOCKED {true} \
        CONFIG.CLKOUT1_USED {true} \
        CONFIG.CLKOUT1_REQUESTED_OUT_FREQ $core_clk_mhz_fmt \
        CONFIG.CLKOUT1_REQUESTED_DUTY_CYCLE {50.000} \
        CONFIG.CLKOUT1_REQUESTED_PHASE {0.000} \
    ] $ip_obj

    generate_target all $ip_obj
    export_ip_user_files -of_objects $ip_obj -no_script -sync -force -quiet
}

proc get_tflm_soc_clk_wiz_synth_files {} {
    set ip_name clk_wiz_0
    set synth_files [list]

    foreach ip_file [get_files -all -of_objects [get_ips $ip_name]] {
        if {![string match "*.v" $ip_file]} {
            continue
        }
        if {[string match "*_bmstub.v" $ip_file]} {
            continue
        }
        lappend synth_files $ip_file
    }

    return $synth_files
}
