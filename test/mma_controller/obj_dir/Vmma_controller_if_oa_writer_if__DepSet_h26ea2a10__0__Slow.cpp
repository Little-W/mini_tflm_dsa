// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Design implementation internals
// See Vmma_controller_if.h for the primary calling header

#include "Vmma_controller_if__pch.h"
#include "Vmma_controller_if_oa_writer_if.h"

VL_ATTR_COLD void Vmma_controller_if_oa_writer_if___eval_static__TOP__tb_mma_controller__DOT__oa_if(Vmma_controller_if_oa_writer_if* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+        Vmma_controller_if_oa_writer_if___eval_static__TOP__tb_mma_controller__DOT__oa_if\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    vlSelfRef.cb__DOT__write_oa_req = vlSelfRef.write_oa_req;
    vlSelfRef.__Vclocking_prev__cb__DOT__write_oa_req 
        = vlSelfRef.cb__DOT__write_oa_req;
    vlSelfRef.cb__DOT__write_done = vlSelfRef.write_done;
    vlSelfRef.__Vclocking_prev__cb__DOT__write_done 
        = vlSelfRef.cb__DOT__write_done;
    vlSelfRef.cb__DOT__oa_calc_over = vlSelfRef.oa_calc_over;
    vlSelfRef.__Vclocking_prev__cb__DOT__oa_calc_over 
        = vlSelfRef.cb__DOT__oa_calc_over;
}

VL_ATTR_COLD void Vmma_controller_if_oa_writer_if___ctor_var_reset(Vmma_controller_if_oa_writer_if* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+        Vmma_controller_if_oa_writer_if___ctor_var_reset\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    vlSelf->clk = VL_RAND_RESET_I(1);
    vlSelf->write_oa_req = VL_RAND_RESET_I(1);
    vlSelf->write_done = VL_RAND_RESET_I(1);
    vlSelf->oa_calc_over = VL_RAND_RESET_I(1);
    vlSelf->cb__DOT__oa_calc_over = VL_RAND_RESET_I(1);
    vlSelf->cb__DOT__write_done = VL_RAND_RESET_I(1);
    vlSelf->cb__DOT__write_oa_req = VL_RAND_RESET_I(1);
    vlSelf->__Vclocking_prev__cb__DOT__write_oa_req = VL_RAND_RESET_I(1);
    vlSelf->__Vclocking_prev__cb__DOT__write_done = VL_RAND_RESET_I(1);
    vlSelf->__Vclocking_prev__cb__DOT__oa_calc_over = VL_RAND_RESET_I(1);
    vlSelf->__Vintraval_h32b2c1a4__0 = VL_RAND_RESET_I(1);
    vlSelf->__Vintraval_hcc7d76c7__0 = VL_RAND_RESET_I(1);
    vlSelf->__Vintraval_h541f8722__0 = VL_RAND_RESET_I(1);
}
