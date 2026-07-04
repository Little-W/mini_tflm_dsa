# TFLM AI DSA SoC board-level constraints for fpga_top.
# Pin locations and I/O standards follow the Alkaid Artix-7 board reference:
# /home/etc/FPGA/jichuangsai/alkaid_soc/rv_test.srcs/constrs_1/new/con_1.xdc
#
# The board input clock is 50 MHz. clk_wiz_0 generates the internal SoC/NPU
# clock, and Vivado derives the generated clock from the Clocking Wizard XDC.

set_property CFGBVS VCCO [current_design]
set_property CONFIG_VOLTAGE 3.3 [current_design]

set_property BITSTREAM.GENERAL.COMPRESS true [current_design]
set_property BITSTREAM.CONFIG.CONFIGRATE 50 [current_design]
set_property BITSTREAM.CONFIG.SPI_BUSWIDTH 4 [current_design]
set_property BITSTREAM.CONFIG.SPI_FALL_EDGE yes [current_design]

set_property PACKAGE_PIN R4 [get_ports sys_clk]
set_property IOSTANDARD LVCMOS15 [get_ports sys_clk]

set_property PACKAGE_PIN U7 [get_ports sys_rst_n]
set_property IOSTANDARD LVCMOS15 [get_ports sys_rst_n]

set_property PACKAGE_PIN E14 [get_ports UART_0_rxd]
set_property IOSTANDARD LVCMOS33 [get_ports UART_0_rxd]

set_property PACKAGE_PIN D17 [get_ports UART_0_txd]
set_property IOSTANDARD LVCMOS33 [get_ports UART_0_txd]

set_property PACKAGE_PIN W7 [get_ports {user_led_tri_o[0]}]
set_property PACKAGE_PIN Y7 [get_ports {user_led_tri_o[1]}]
set_property PACKAGE_PIN Y8 [get_ports {user_led_tri_o[2]}]
set_property PACKAGE_PIN V9 [get_ports {user_led_tri_o[3]}]
set_property IOSTANDARD LVCMOS15 [get_ports {user_led_tri_o[0]}]
set_property IOSTANDARD LVCMOS15 [get_ports {user_led_tri_o[1]}]
set_property IOSTANDARD LVCMOS15 [get_ports {user_led_tri_o[2]}]
set_property IOSTANDARD LVCMOS15 [get_ports {user_led_tri_o[3]}]

set_false_path -from [get_ports sys_rst_n]
set_false_path -quiet -from [get_pins -hierarchical -quiet *soc_rst_n_sync_reg*/Q]
