// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Design implementation internals
// See Vmma_controller_if.h for the primary calling header

#include "Vmma_controller_if__pch.h"
#include "Vmma_controller_if__Syms.h"
#include "Vmma_controller_if_compute_core_if.h"

VL_INLINE_OPT VlCoroutine Vmma_controller_if_compute_core_if___obs_sequent__TOP__tb_mma_controller__DOT__comp_if__0____Vfork_2__0(Vmma_controller_if_compute_core_if* vlSelf, CData/*0:0*/ __Vintraval_ha30227c0__0) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+        Vmma_controller_if_compute_core_if___obs_sequent__TOP__tb_mma_controller__DOT__comp_if__0____Vfork_2__0\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    if (((IData)(vlSelfRef.__Vclocking_prev__cb__DOT__partial_sum_calc_over) 
         != (IData)(vlSelfRef.cb__DOT__partial_sum_calc_over))) {
        __Vintraval_ha30227c0__0 = vlSelfRef.cb__DOT__partial_sum_calc_over;
        co_await vlSymsp->TOP.__VdlySched.delay(0x3e8ULL, 
                                                nullptr, 
                                                "mma_controller_if.sv", 
                                                169);
        vlSelfRef.partial_sum_calc_over = __Vintraval_ha30227c0__0;
        vlSelfRef.__Vclocking_prev__cb__DOT__partial_sum_calc_over 
            = vlSelfRef.cb__DOT__partial_sum_calc_over;
    }
}

VL_INLINE_OPT VlCoroutine Vmma_controller_if_compute_core_if___obs_sequent__TOP__tb_mma_controller__DOT__comp_if__0____Vfork_1__0(Vmma_controller_if_compute_core_if* vlSelf, CData/*0:0*/ __Vintraval_h5f1db4e6__0) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+        Vmma_controller_if_compute_core_if___obs_sequent__TOP__tb_mma_controller__DOT__comp_if__0____Vfork_1__0\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    if (((IData)(vlSelfRef.__Vclocking_prev__cb__DOT__tile_calc_over) 
         != (IData)(vlSelfRef.cb__DOT__tile_calc_over))) {
        __Vintraval_h5f1db4e6__0 = vlSelfRef.cb__DOT__tile_calc_over;
        co_await vlSymsp->TOP.__VdlySched.delay(0x3e8ULL, 
                                                nullptr, 
                                                "mma_controller_if.sv", 
                                                170);
        vlSelfRef.tile_calc_over = __Vintraval_h5f1db4e6__0;
        vlSelfRef.__Vclocking_prev__cb__DOT__tile_calc_over 
            = vlSelfRef.cb__DOT__tile_calc_over;
    }
}
