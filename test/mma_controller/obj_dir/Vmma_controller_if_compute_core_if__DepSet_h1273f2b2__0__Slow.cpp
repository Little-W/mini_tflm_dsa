// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Design implementation internals
// See Vmma_controller_if.h for the primary calling header

#include "Vmma_controller_if__pch.h"
#include "Vmma_controller_if_compute_core_if.h"

VL_ATTR_COLD void Vmma_controller_if_compute_core_if___eval_static__TOP__tb_mma_controller__DOT__comp_if(Vmma_controller_if_compute_core_if* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+        Vmma_controller_if_compute_core_if___eval_static__TOP__tb_mma_controller__DOT__comp_if\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    vlSelfRef.cb__DOT__partial_sum_calc_over = vlSelfRef.partial_sum_calc_over;
    vlSelfRef.__Vclocking_prev__cb__DOT__partial_sum_calc_over 
        = vlSelfRef.cb__DOT__partial_sum_calc_over;
    vlSelfRef.cb__DOT__tile_calc_over = vlSelfRef.tile_calc_over;
    vlSelfRef.__Vclocking_prev__cb__DOT__tile_calc_over 
        = vlSelfRef.cb__DOT__tile_calc_over;
}

VL_ATTR_COLD void Vmma_controller_if_compute_core_if___ctor_var_reset(Vmma_controller_if_compute_core_if* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+        Vmma_controller_if_compute_core_if___ctor_var_reset\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    vlSelf->clk = VL_RAND_RESET_I(1);
    vlSelf->partial_sum_calc_over = VL_RAND_RESET_I(1);
    vlSelf->tile_calc_over = VL_RAND_RESET_I(1);
    vlSelf->cb__DOT__tile_calc_over = VL_RAND_RESET_I(1);
    vlSelf->cb__DOT__partial_sum_calc_over = VL_RAND_RESET_I(1);
    vlSelf->__Vclocking_prev__cb__DOT__partial_sum_calc_over = VL_RAND_RESET_I(1);
    vlSelf->__Vclocking_prev__cb__DOT__tile_calc_over = VL_RAND_RESET_I(1);
    vlSelf->__Vintraval_h5f1db4e6__0 = VL_RAND_RESET_I(1);
    vlSelf->__Vintraval_ha30227c0__0 = VL_RAND_RESET_I(1);
}
