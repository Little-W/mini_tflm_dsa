// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Design implementation internals
// See Vmma_controller_if.h for the primary calling header

#include "Vmma_controller_if__pch.h"
#include "Vmma_controller_if__Syms.h"
#include "Vmma_controller_if_control_if__R20.h"

VL_INLINE_OPT VlCoroutine Vmma_controller_if_control_if__R20___obs_sequent__TOP__tb_mma_controller__DOT__ctrl_if__0____Vfork_3__0(Vmma_controller_if_control_if__R20* vlSelf, CData/*0:0*/ __Vintraval_h56cfd7c8__0) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+        Vmma_controller_if_control_if__R20___obs_sequent__TOP__tb_mma_controller__DOT__ctrl_if__0____Vfork_3__0\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    if (((IData)(vlSelfRef.__Vclocking_prev__cb__DOT__calc_start) 
         != (IData)(vlSelfRef.cb__DOT__calc_start))) {
        __Vintraval_h56cfd7c8__0 = vlSelfRef.cb__DOT__calc_start;
        co_await vlSymsp->TOP.__VdlySched.delay(0x3e8ULL, 
                                                nullptr, 
                                                "mma_controller_if.sv", 
                                                204);
        vlSelfRef.calc_start = __Vintraval_h56cfd7c8__0;
        vlSelfRef.__Vclocking_prev__cb__DOT__calc_start 
            = vlSelfRef.cb__DOT__calc_start;
    }
}

VL_INLINE_OPT VlCoroutine Vmma_controller_if_control_if__R20___obs_sequent__TOP__tb_mma_controller__DOT__ctrl_if__0____Vfork_1__0(Vmma_controller_if_control_if__R20* vlSelf, CData/*0:0*/ __Vintraval_h9028ce99__0) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+        Vmma_controller_if_control_if__R20___obs_sequent__TOP__tb_mma_controller__DOT__ctrl_if__0____Vfork_1__0\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    if (((IData)(vlSelfRef.__Vclocking_prev__cb__DOT__fifo_full_flag) 
         != (IData)(vlSelfRef.cb__DOT__fifo_full_flag))) {
        __Vintraval_h9028ce99__0 = vlSelfRef.cb__DOT__fifo_full_flag;
        co_await vlSymsp->TOP.__VdlySched.delay(0x3e8ULL, 
                                                nullptr, 
                                                "mma_controller_if.sv", 
                                                215);
        vlSelfRef.fifo_full_flag = __Vintraval_h9028ce99__0;
        vlSelfRef.__Vclocking_prev__cb__DOT__fifo_full_flag 
            = vlSelfRef.cb__DOT__fifo_full_flag;
    }
}

VL_INLINE_OPT VlCoroutine Vmma_controller_if_control_if__R20___obs_sequent__TOP__tb_mma_controller__DOT__ctrl_if__0____Vfork_2__0(Vmma_controller_if_control_if__R20* vlSelf, CData/*0:0*/ __Vintraval_h10c76d9d__0) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+        Vmma_controller_if_control_if__R20___obs_sequent__TOP__tb_mma_controller__DOT__ctrl_if__0____Vfork_2__0\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    if (((IData)(vlSelfRef.__Vclocking_prev__cb__DOT__cfg_16bits_ia) 
         != (IData)(vlSelfRef.cb__DOT__cfg_16bits_ia))) {
        __Vintraval_h10c76d9d__0 = vlSelfRef.cb__DOT__cfg_16bits_ia;
        co_await vlSymsp->TOP.__VdlySched.delay(0x3e8ULL, 
                                                nullptr, 
                                                "mma_controller_if.sv", 
                                                205);
        vlSelfRef.cfg_16bits_ia = __Vintraval_h10c76d9d__0;
        vlSelfRef.__Vclocking_prev__cb__DOT__cfg_16bits_ia 
            = vlSelfRef.cb__DOT__cfg_16bits_ia;
    }
}
