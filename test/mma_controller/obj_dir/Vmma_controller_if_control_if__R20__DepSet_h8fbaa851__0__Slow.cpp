// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Design implementation internals
// See Vmma_controller_if.h for the primary calling header

#include "Vmma_controller_if__pch.h"
#include "Vmma_controller_if_control_if__R20.h"

VL_ATTR_COLD void Vmma_controller_if_control_if__R20___eval_static__TOP__tb_mma_controller__DOT__ctrl_if(Vmma_controller_if_control_if__R20* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+        Vmma_controller_if_control_if__R20___eval_static__TOP__tb_mma_controller__DOT__ctrl_if\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    vlSelfRef.cb__DOT__calc_start = vlSelfRef.calc_start;
    vlSelfRef.__Vclocking_prev__cb__DOT__calc_start 
        = vlSelfRef.cb__DOT__calc_start;
    vlSelfRef.cb__DOT__cfg_16bits_ia = vlSelfRef.cfg_16bits_ia;
    vlSelfRef.__Vclocking_prev__cb__DOT__cfg_16bits_ia 
        = vlSelfRef.cb__DOT__cfg_16bits_ia;
    vlSelfRef.cb__DOT__fifo_full_flag = vlSelfRef.fifo_full_flag;
    vlSelfRef.__Vclocking_prev__cb__DOT__fifo_full_flag 
        = vlSelfRef.cb__DOT__fifo_full_flag;
}

VL_ATTR_COLD void Vmma_controller_if_control_if__R20___ctor_var_reset(Vmma_controller_if_control_if__R20* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+        Vmma_controller_if_control_if__R20___ctor_var_reset\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    vlSelf->clk = VL_RAND_RESET_I(1);
    vlSelf->calc_start = VL_RAND_RESET_I(1);
    vlSelf->cfg_16bits_ia = VL_RAND_RESET_I(1);
    vlSelf->fifo_full_flag = VL_RAND_RESET_I(1);
    vlSelf->cb__DOT__fifo_full_flag = VL_RAND_RESET_I(1);
    vlSelf->cb__DOT__cfg_16bits_ia = VL_RAND_RESET_I(1);
    vlSelf->cb__DOT__calc_start = VL_RAND_RESET_I(1);
    vlSelf->__Vclocking_prev__cb__DOT__calc_start = VL_RAND_RESET_I(1);
    vlSelf->__Vclocking_prev__cb__DOT__cfg_16bits_ia = VL_RAND_RESET_I(1);
    vlSelf->__Vclocking_prev__cb__DOT__fifo_full_flag = VL_RAND_RESET_I(1);
    vlSelf->__Vintraval_h9028ce99__0 = VL_RAND_RESET_I(1);
    vlSelf->__Vintraval_h10c76d9d__0 = VL_RAND_RESET_I(1);
    vlSelf->__Vintraval_h56cfd7c8__0 = VL_RAND_RESET_I(1);
}
