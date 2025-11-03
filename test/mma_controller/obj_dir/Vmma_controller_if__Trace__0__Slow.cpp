// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Tracing implementation internals
#include "verilated_vcd_c.h"
#include "Vmma_controller_if__Syms.h"


VL_ATTR_COLD void Vmma_controller_if___024root__trace_init_sub__TOP__tb_mma_controller__DOT__ctrl_if__0(Vmma_controller_if___024root* vlSelf, VerilatedVcd* tracep);
VL_ATTR_COLD void Vmma_controller_if___024root__trace_init_sub__TOP__tb_mma_controller__DOT__ia_if__0(Vmma_controller_if___024root* vlSelf, VerilatedVcd* tracep);
VL_ATTR_COLD void Vmma_controller_if___024root__trace_init_sub__TOP__tb_mma_controller__DOT__weight_if__0(Vmma_controller_if___024root* vlSelf, VerilatedVcd* tracep);
VL_ATTR_COLD void Vmma_controller_if___024root__trace_init_sub__TOP__tb_mma_controller__DOT__bias_if__0(Vmma_controller_if___024root* vlSelf, VerilatedVcd* tracep);
VL_ATTR_COLD void Vmma_controller_if___024root__trace_init_sub__TOP__tb_mma_controller__DOT__quant_if__0(Vmma_controller_if___024root* vlSelf, VerilatedVcd* tracep);
VL_ATTR_COLD void Vmma_controller_if___024root__trace_init_sub__TOP__tb_mma_controller__DOT__oa_if__0(Vmma_controller_if___024root* vlSelf, VerilatedVcd* tracep);
VL_ATTR_COLD void Vmma_controller_if___024root__trace_init_sub__TOP__tb_mma_controller__DOT__comp_if__0(Vmma_controller_if___024root* vlSelf, VerilatedVcd* tracep);

VL_ATTR_COLD void Vmma_controller_if___024root__trace_init_sub__TOP__0(Vmma_controller_if___024root* vlSelf, VerilatedVcd* tracep) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vmma_controller_if___024root__trace_init_sub__TOP__0\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Init
    const int c = vlSymsp->__Vm_baseCode;
    // Body
    tracep->pushPrefix("tb_mma_controller", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->declBus(c+57,0,"WEIGHT_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBus(c+58,0,"DATA_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBus(c+58,0,"SIZE",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBus(c+59,0,"BUS_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBus(c+59,0,"REG_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBus(c+60,0,"CLK_PERIOD",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBit(c+32,0,"clk",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+33,0,"rst_n",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->pushPrefix("ctrl_if", VerilatedTracePrefixType::SCOPE_INTERFACE);
    Vmma_controller_if___024root__trace_init_sub__TOP__tb_mma_controller__DOT__ctrl_if__0(vlSelf, tracep);
    tracep->popPrefix();
    tracep->pushPrefix("ia_if", VerilatedTracePrefixType::SCOPE_INTERFACE);
    Vmma_controller_if___024root__trace_init_sub__TOP__tb_mma_controller__DOT__ia_if__0(vlSelf, tracep);
    tracep->popPrefix();
    tracep->pushPrefix("weight_if", VerilatedTracePrefixType::SCOPE_INTERFACE);
    Vmma_controller_if___024root__trace_init_sub__TOP__tb_mma_controller__DOT__weight_if__0(vlSelf, tracep);
    tracep->popPrefix();
    tracep->pushPrefix("bias_if", VerilatedTracePrefixType::SCOPE_INTERFACE);
    Vmma_controller_if___024root__trace_init_sub__TOP__tb_mma_controller__DOT__bias_if__0(vlSelf, tracep);
    tracep->popPrefix();
    tracep->pushPrefix("quant_if", VerilatedTracePrefixType::SCOPE_INTERFACE);
    Vmma_controller_if___024root__trace_init_sub__TOP__tb_mma_controller__DOT__quant_if__0(vlSelf, tracep);
    tracep->popPrefix();
    tracep->pushPrefix("oa_if", VerilatedTracePrefixType::SCOPE_INTERFACE);
    Vmma_controller_if___024root__trace_init_sub__TOP__tb_mma_controller__DOT__oa_if__0(vlSelf, tracep);
    tracep->popPrefix();
    tracep->pushPrefix("comp_if", VerilatedTracePrefixType::SCOPE_INTERFACE);
    Vmma_controller_if___024root__trace_init_sub__TOP__tb_mma_controller__DOT__comp_if__0(vlSelf, tracep);
    tracep->popPrefix();
    tracep->pushPrefix("dut", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->declBus(c+57,0,"WEIGHT_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBus(c+58,0,"DATA_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBus(c+58,0,"SIZE",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBus(c+59,0,"BUS_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBus(c+59,0,"REG_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBit(c+32,0,"clk",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+33,0,"rst_n",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+34,0,"calc_start",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+35,0,"cfg_16bits_ia",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+1,0,"sa_ready",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+61,0,"lhs_base",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+62,0,"rhs_base",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+63,0,"dst_base",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+64,0,"bias_base",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+65,0,"q_mult_pt",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+66,0,"q_shift_pt",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBit(c+67,0,"use_per_channel",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+68,0,"k",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+69,0,"n",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+70,0,"m",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+71,0,"lhs_row_stride_b",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+72,0,"dst_row_stride_b",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+73,0,"rhs_row_stride_b",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+2,0,"icb_sel",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 2,0);
    tracep->declBit(c+3,0,"init_cfg_ia",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+4,0,"init_cfg_weight",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+5,0,"init_cfg_bias",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+6,0,"init_cfg_requant",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+7,0,"init_cfg_oa",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+8,0,"use_16bits",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+74,0,"tile_count",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBit(c+36,0,"partial_sum_calc_over",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+37,0,"load_ia_req",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+9,0,"load_ia_granted",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+10,0,"send_ia_trigger",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+38,0,"ia_sending_done",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+39,0,"ia_data_valid",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+40,0,"load_weight_req",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+11,0,"load_weight_granted",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+12,0,"send_weight_trigger",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+41,0,"weight_sending_done",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+42,0,"weight_data_valid",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+43,0,"load_bias_req",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+13,0,"load_bias_granted",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+44,0,"bias_valid",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+45,0,"load_quant_req",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+14,0,"load_quant_granted",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+46,0,"quant_params_valid",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+47,0,"fifo_full_flag",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+48,0,"write_oa_req",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+15,0,"write_oa_granted",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+49,0,"write_done",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+50,0,"oa_calc_over",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+51,0,"wb_valid",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+75,0,"wb_ready",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+16,0,"err_code",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 1,0);
    tracep->declBus(c+17,0,"current_state",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 3,0);
    tracep->declBus(c+52,0,"next_state",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 3,0);
    tracep->declBit(c+18,0,"cfg_16bits_ia_reg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+19,0,"config_error",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+20,0,"error_type",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 1,0);
    tracep->pushPrefix("u_icb_arbiter", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->declBit(c+32,0,"clk",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+33,0,"rst_n",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+37,0,"s0_req",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+9,0,"s0_granted",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+39,0,"s0_done",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+40,0,"s1_req",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+11,0,"s1_granted",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+42,0,"s1_done",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+43,0,"s2_req",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+13,0,"s2_granted",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+44,0,"s2_done",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+45,0,"s3_req",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+14,0,"s3_granted",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+46,0,"s3_done",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+48,0,"s4_req",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+15,0,"s4_granted",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+49,0,"s4_done",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+2,0,"icb_sel",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 2,0);
    tracep->declBus(c+21,0,"current_master",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 2,0);
    tracep->declBit(c+22,0,"bus_busy",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->pushPrefix("priority_queue", VerilatedTracePrefixType::ARRAY_UNPACKED);
    for (int i = 0; i < 4; ++i) {
        tracep->declBus(c+23+i*1,0,"",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, true,(i+0), 2,0);
    }
    tracep->popPrefix();
    tracep->pushPrefix("next_priority_queue", VerilatedTracePrefixType::ARRAY_UNPACKED);
    for (int i = 0; i < 4; ++i) {
        tracep->declBus(c+27+i*1,0,"",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, true,(i+0), 2,0);
    }
    tracep->popPrefix();
    tracep->declBit(c+53,0,"bus_idle",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+54,0,"current_done",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->pushPrefix("unnamedblk1", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->declBus(c+31,0,"next_device",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 2,0);
    tracep->popPrefix();
    tracep->popPrefix();
    tracep->popPrefix();
    tracep->popPrefix();
}

VL_ATTR_COLD void Vmma_controller_if___024root__trace_init_sub__TOP__tb_mma_controller__DOT__ia_if__0(Vmma_controller_if___024root* vlSelf, VerilatedVcd* tracep) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vmma_controller_if___024root__trace_init_sub__TOP__tb_mma_controller__DOT__ia_if__0\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Init
    const int c = vlSymsp->__Vm_baseCode;
    // Body
    tracep->declBit(c+32,0,"clk",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+37,0,"load_ia_req",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+9,0,"load_ia_granted",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+10,0,"send_ia_trigger",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+38,0,"ia_sending_done",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+55,0,"ia_calc_done",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+39,0,"ia_data_valid",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
}

VL_ATTR_COLD void Vmma_controller_if___024root__trace_init_sub__TOP__tb_mma_controller__DOT__weight_if__0(Vmma_controller_if___024root* vlSelf, VerilatedVcd* tracep) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vmma_controller_if___024root__trace_init_sub__TOP__tb_mma_controller__DOT__weight_if__0\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Init
    const int c = vlSymsp->__Vm_baseCode;
    // Body
    tracep->declBit(c+32,0,"clk",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+40,0,"load_weight_req",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+11,0,"load_weight_granted",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+12,0,"send_weight_trigger",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+41,0,"weight_sending_done",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+42,0,"weight_data_valid",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
}

VL_ATTR_COLD void Vmma_controller_if___024root__trace_init_sub__TOP__tb_mma_controller__DOT__bias_if__0(Vmma_controller_if___024root* vlSelf, VerilatedVcd* tracep) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vmma_controller_if___024root__trace_init_sub__TOP__tb_mma_controller__DOT__bias_if__0\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Init
    const int c = vlSymsp->__Vm_baseCode;
    // Body
    tracep->declBit(c+32,0,"clk",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+43,0,"load_bias_req",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+13,0,"load_bias_granted",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+44,0,"bias_valid",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
}

VL_ATTR_COLD void Vmma_controller_if___024root__trace_init_sub__TOP__tb_mma_controller__DOT__quant_if__0(Vmma_controller_if___024root* vlSelf, VerilatedVcd* tracep) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vmma_controller_if___024root__trace_init_sub__TOP__tb_mma_controller__DOT__quant_if__0\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Init
    const int c = vlSymsp->__Vm_baseCode;
    // Body
    tracep->declBit(c+32,0,"clk",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+45,0,"load_quant_req",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+14,0,"load_quant_granted",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+46,0,"quant_params_valid",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
}

VL_ATTR_COLD void Vmma_controller_if___024root__trace_init_sub__TOP__tb_mma_controller__DOT__oa_if__0(Vmma_controller_if___024root* vlSelf, VerilatedVcd* tracep) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vmma_controller_if___024root__trace_init_sub__TOP__tb_mma_controller__DOT__oa_if__0\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Init
    const int c = vlSymsp->__Vm_baseCode;
    // Body
    tracep->declBit(c+32,0,"clk",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+48,0,"write_oa_req",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+15,0,"write_oa_granted",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+49,0,"write_done",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+50,0,"oa_calc_over",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
}

VL_ATTR_COLD void Vmma_controller_if___024root__trace_init_sub__TOP__tb_mma_controller__DOT__comp_if__0(Vmma_controller_if___024root* vlSelf, VerilatedVcd* tracep) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vmma_controller_if___024root__trace_init_sub__TOP__tb_mma_controller__DOT__comp_if__0\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Init
    const int c = vlSymsp->__Vm_baseCode;
    // Body
    tracep->declBit(c+32,0,"clk",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+36,0,"partial_sum_calc_over",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+56,0,"tile_calc_over",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
}

VL_ATTR_COLD void Vmma_controller_if___024root__trace_init_sub__TOP__tb_mma_controller__DOT__ctrl_if__0(Vmma_controller_if___024root* vlSelf, VerilatedVcd* tracep) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vmma_controller_if___024root__trace_init_sub__TOP__tb_mma_controller__DOT__ctrl_if__0\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Init
    const int c = vlSymsp->__Vm_baseCode;
    // Body
    tracep->declBus(c+59,0,"REG_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBit(c+32,0,"clk",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+34,0,"calc_start",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+35,0,"cfg_16bits_ia",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+1,0,"sa_ready",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+2,0,"icb_sel",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 2,0);
    tracep->declBit(c+3,0,"init_cfg_ia",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+4,0,"init_cfg_weight",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+5,0,"init_cfg_bias",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+6,0,"init_cfg_requant",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+7,0,"init_cfg_oa",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+8,0,"use_16bits",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+74,0,"tile_count",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBit(c+47,0,"fifo_full_flag",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
}

VL_ATTR_COLD void Vmma_controller_if___024root__trace_init_top(Vmma_controller_if___024root* vlSelf, VerilatedVcd* tracep) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vmma_controller_if___024root__trace_init_top\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    Vmma_controller_if___024root__trace_init_sub__TOP__0(vlSelf, tracep);
}

VL_ATTR_COLD void Vmma_controller_if___024root__trace_const_0(void* voidSelf, VerilatedVcd::Buffer* bufp);
VL_ATTR_COLD void Vmma_controller_if___024root__trace_full_0(void* voidSelf, VerilatedVcd::Buffer* bufp);
void Vmma_controller_if___024root__trace_chg_0(void* voidSelf, VerilatedVcd::Buffer* bufp);
void Vmma_controller_if___024root__trace_cleanup(void* voidSelf, VerilatedVcd* /*unused*/);

VL_ATTR_COLD void Vmma_controller_if___024root__trace_register(Vmma_controller_if___024root* vlSelf, VerilatedVcd* tracep) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vmma_controller_if___024root__trace_register\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    tracep->addConstCb(&Vmma_controller_if___024root__trace_const_0, 0U, vlSelf);
    tracep->addFullCb(&Vmma_controller_if___024root__trace_full_0, 0U, vlSelf);
    tracep->addChgCb(&Vmma_controller_if___024root__trace_chg_0, 0U, vlSelf);
    tracep->addCleanupCb(&Vmma_controller_if___024root__trace_cleanup, vlSelf);
}

VL_ATTR_COLD void Vmma_controller_if___024root__trace_const_0_sub_0(Vmma_controller_if___024root* vlSelf, VerilatedVcd::Buffer* bufp);

VL_ATTR_COLD void Vmma_controller_if___024root__trace_const_0(void* voidSelf, VerilatedVcd::Buffer* bufp) {
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vmma_controller_if___024root__trace_const_0\n"); );
    // Init
    Vmma_controller_if___024root* const __restrict vlSelf VL_ATTR_UNUSED = static_cast<Vmma_controller_if___024root*>(voidSelf);
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    // Body
    Vmma_controller_if___024root__trace_const_0_sub_0((&vlSymsp->TOP), bufp);
}

VL_ATTR_COLD void Vmma_controller_if___024root__trace_const_0_sub_0(Vmma_controller_if___024root* vlSelf, VerilatedVcd::Buffer* bufp) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vmma_controller_if___024root__trace_const_0_sub_0\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Init
    uint32_t* const oldp VL_ATTR_UNUSED = bufp->oldp(vlSymsp->__Vm_baseCode);
    // Body
    bufp->fullIData(oldp+57,(8U),32);
    bufp->fullIData(oldp+58,(0x10U),32);
    bufp->fullIData(oldp+59,(0x20U),32);
    bufp->fullIData(oldp+60,(0xaU),32);
    bufp->fullIData(oldp+61,(vlSelfRef.tb_mma_controller__DOT__dut__DOT__lhs_base),32);
    bufp->fullIData(oldp+62,(vlSelfRef.tb_mma_controller__DOT__dut__DOT__rhs_base),32);
    bufp->fullIData(oldp+63,(vlSelfRef.tb_mma_controller__DOT__dut__DOT__dst_base),32);
    bufp->fullIData(oldp+64,(vlSelfRef.tb_mma_controller__DOT__dut__DOT__bias_base),32);
    bufp->fullIData(oldp+65,(vlSelfRef.tb_mma_controller__DOT__dut__DOT__q_mult_pt),32);
    bufp->fullIData(oldp+66,(vlSelfRef.tb_mma_controller__DOT__dut__DOT__q_shift_pt),32);
    bufp->fullBit(oldp+67,(vlSelfRef.tb_mma_controller__DOT__dut__DOT__use_per_channel));
    bufp->fullIData(oldp+68,(vlSelfRef.tb_mma_controller__DOT__dut__DOT__k),32);
    bufp->fullIData(oldp+69,(vlSelfRef.tb_mma_controller__DOT__dut__DOT__n),32);
    bufp->fullIData(oldp+70,(vlSelfRef.tb_mma_controller__DOT__dut__DOT__m),32);
    bufp->fullIData(oldp+71,(vlSelfRef.tb_mma_controller__DOT__dut__DOT__lhs_row_stride_b),32);
    bufp->fullIData(oldp+72,(vlSelfRef.tb_mma_controller__DOT__dut__DOT__dst_row_stride_b),32);
    bufp->fullIData(oldp+73,(vlSelfRef.tb_mma_controller__DOT__dut__DOT__rhs_row_stride_b),32);
    bufp->fullIData(oldp+74,(vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__tile_count),32);
    bufp->fullBit(oldp+75,(vlSelfRef.tb_mma_controller__DOT__dut__DOT__wb_ready));
}

VL_ATTR_COLD void Vmma_controller_if___024root__trace_full_0_sub_0(Vmma_controller_if___024root* vlSelf, VerilatedVcd::Buffer* bufp);

VL_ATTR_COLD void Vmma_controller_if___024root__trace_full_0(void* voidSelf, VerilatedVcd::Buffer* bufp) {
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vmma_controller_if___024root__trace_full_0\n"); );
    // Init
    Vmma_controller_if___024root* const __restrict vlSelf VL_ATTR_UNUSED = static_cast<Vmma_controller_if___024root*>(voidSelf);
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    // Body
    Vmma_controller_if___024root__trace_full_0_sub_0((&vlSymsp->TOP), bufp);
}

VL_ATTR_COLD void Vmma_controller_if___024root__trace_full_0_sub_0(Vmma_controller_if___024root* vlSelf, VerilatedVcd::Buffer* bufp) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vmma_controller_if___024root__trace_full_0_sub_0\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Init
    uint32_t* const oldp VL_ATTR_UNUSED = bufp->oldp(vlSymsp->__Vm_baseCode);
    // Body
    bufp->fullBit(oldp+1,((0U == (IData)(vlSelfRef.tb_mma_controller__DOT__dut__DOT__current_state))));
    bufp->fullCData(oldp+2,(vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__icb_sel),3);
    bufp->fullBit(oldp+3,(vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__init_cfg_ia));
    bufp->fullBit(oldp+4,(vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__init_cfg_weight));
    bufp->fullBit(oldp+5,(vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__init_cfg_bias));
    bufp->fullBit(oldp+6,(vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__init_cfg_requant));
    bufp->fullBit(oldp+7,(vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__init_cfg_oa));
    bufp->fullBit(oldp+8,(vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__use_16bits));
    bufp->fullBit(oldp+9,(vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__load_ia_granted));
    bufp->fullBit(oldp+10,(vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__send_ia_trigger));
    bufp->fullBit(oldp+11,(vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__load_weight_granted));
    bufp->fullBit(oldp+12,(vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__send_weight_trigger));
    bufp->fullBit(oldp+13,(vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__load_bias_granted));
    bufp->fullBit(oldp+14,(vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__load_quant_granted));
    bufp->fullBit(oldp+15,(vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__write_oa_granted));
    bufp->fullCData(oldp+16,(vlSelfRef.tb_mma_controller__DOT__dut__DOT__err_code),2);
    bufp->fullCData(oldp+17,(vlSelfRef.tb_mma_controller__DOT__dut__DOT__current_state),4);
    bufp->fullBit(oldp+18,(vlSelfRef.tb_mma_controller__DOT__dut__DOT__cfg_16bits_ia_reg));
    bufp->fullBit(oldp+19,(vlSelfRef.tb_mma_controller__DOT__dut__DOT__config_error));
    bufp->fullCData(oldp+20,(vlSelfRef.tb_mma_controller__DOT__dut__DOT__error_type),2);
    bufp->fullCData(oldp+21,(vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__current_master),3);
    bufp->fullBit(oldp+22,(vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__bus_busy));
    bufp->fullCData(oldp+23,(vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__priority_queue[0]),3);
    bufp->fullCData(oldp+24,(vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__priority_queue[1]),3);
    bufp->fullCData(oldp+25,(vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__priority_queue[2]),3);
    bufp->fullCData(oldp+26,(vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__priority_queue[3]),3);
    bufp->fullCData(oldp+27,(vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__next_priority_queue[0]),3);
    bufp->fullCData(oldp+28,(vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__next_priority_queue[1]),3);
    bufp->fullCData(oldp+29,(vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__next_priority_queue[2]),3);
    bufp->fullCData(oldp+30,(vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__next_priority_queue[3]),3);
    bufp->fullCData(oldp+31,(vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__unnamedblk1__DOT__next_device),3);
    bufp->fullBit(oldp+32,(vlSelfRef.tb_mma_controller__DOT__clk));
    bufp->fullBit(oldp+33,(vlSelfRef.tb_mma_controller__DOT__rst_n));
    bufp->fullBit(oldp+34,(vlSymsp->TOP__tb_mma_controller__DOT__ctrl_if.calc_start));
    bufp->fullBit(oldp+35,(vlSymsp->TOP__tb_mma_controller__DOT__ctrl_if.cfg_16bits_ia));
    bufp->fullBit(oldp+36,(vlSymsp->TOP__tb_mma_controller__DOT__comp_if.partial_sum_calc_over));
    bufp->fullBit(oldp+37,(vlSymsp->TOP__tb_mma_controller__DOT__ia_if.load_ia_req));
    bufp->fullBit(oldp+38,(vlSymsp->TOP__tb_mma_controller__DOT__ia_if.ia_sending_done));
    bufp->fullBit(oldp+39,(vlSymsp->TOP__tb_mma_controller__DOT__ia_if.ia_data_valid));
    bufp->fullBit(oldp+40,(vlSymsp->TOP__tb_mma_controller__DOT__weight_if.load_weight_req));
    bufp->fullBit(oldp+41,(vlSymsp->TOP__tb_mma_controller__DOT__weight_if.weight_sending_done));
    bufp->fullBit(oldp+42,(vlSymsp->TOP__tb_mma_controller__DOT__weight_if.weight_data_valid));
    bufp->fullBit(oldp+43,(vlSymsp->TOP__tb_mma_controller__DOT__bias_if.load_bias_req));
    bufp->fullBit(oldp+44,(vlSymsp->TOP__tb_mma_controller__DOT__bias_if.bias_valid));
    bufp->fullBit(oldp+45,(vlSymsp->TOP__tb_mma_controller__DOT__quant_if.load_quant_req));
    bufp->fullBit(oldp+46,(vlSymsp->TOP__tb_mma_controller__DOT__quant_if.quant_params_valid));
    bufp->fullBit(oldp+47,(vlSymsp->TOP__tb_mma_controller__DOT__ctrl_if.fifo_full_flag));
    bufp->fullBit(oldp+48,(vlSymsp->TOP__tb_mma_controller__DOT__oa_if.write_oa_req));
    bufp->fullBit(oldp+49,(vlSymsp->TOP__tb_mma_controller__DOT__oa_if.write_done));
    bufp->fullBit(oldp+50,(vlSymsp->TOP__tb_mma_controller__DOT__oa_if.oa_calc_over));
    bufp->fullBit(oldp+51,(((IData)(vlSymsp->TOP__tb_mma_controller__DOT__oa_if.oa_calc_over) 
                            | ((7U == (IData)(vlSelfRef.tb_mma_controller__DOT__dut__DOT__current_state)) 
                               | (8U == (IData)(vlSelfRef.tb_mma_controller__DOT__dut__DOT__current_state))))));
    bufp->fullCData(oldp+52,(vlSelfRef.tb_mma_controller__DOT__dut__DOT__next_state),4);
    bufp->fullBit(oldp+53,((1U & ((~ (IData)(vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__bus_busy)) 
                                  | ((IData)(vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__bus_busy) 
                                     & (IData)(vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__current_done))))));
    bufp->fullBit(oldp+54,(vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__current_done));
    bufp->fullBit(oldp+55,(vlSymsp->TOP__tb_mma_controller__DOT__ia_if.__PVT__ia_calc_done));
    bufp->fullBit(oldp+56,(vlSymsp->TOP__tb_mma_controller__DOT__comp_if.tile_calc_over));
}
