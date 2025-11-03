// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Design implementation internals
// See Vmma_controller_if.h for the primary calling header

#include "Vmma_controller_if__pch.h"
#include "Vmma_controller_if_ia_loader_if.h"

VL_ATTR_COLD void Vmma_controller_if_ia_loader_if___eval_static__TOP__tb_mma_controller__DOT__ia_if(Vmma_controller_if_ia_loader_if* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+        Vmma_controller_if_ia_loader_if___eval_static__TOP__tb_mma_controller__DOT__ia_if\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    vlSelfRef.cb__DOT__load_ia_req = vlSelfRef.load_ia_req;
    vlSelfRef.__Vclocking_prev__cb__DOT__load_ia_req 
        = vlSelfRef.cb__DOT__load_ia_req;
    vlSelfRef.cb__DOT__ia_sending_done = vlSelfRef.ia_sending_done;
    vlSelfRef.__Vclocking_prev__cb__DOT__ia_sending_done 
        = vlSelfRef.cb__DOT__ia_sending_done;
    vlSelfRef.cb__DOT__ia_calc_done = vlSelfRef.__PVT__ia_calc_done;
    vlSelfRef.__Vclocking_prev__cb__DOT__ia_calc_done 
        = vlSelfRef.cb__DOT__ia_calc_done;
    vlSelfRef.cb__DOT__ia_data_valid = vlSelfRef.ia_data_valid;
    vlSelfRef.__Vclocking_prev__cb__DOT__ia_data_valid 
        = vlSelfRef.cb__DOT__ia_data_valid;
}

VL_ATTR_COLD void Vmma_controller_if_ia_loader_if___ctor_var_reset(Vmma_controller_if_ia_loader_if* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+        Vmma_controller_if_ia_loader_if___ctor_var_reset\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    vlSelf->clk = VL_RAND_RESET_I(1);
    vlSelf->load_ia_req = VL_RAND_RESET_I(1);
    vlSelf->ia_sending_done = VL_RAND_RESET_I(1);
    vlSelf->__PVT__ia_calc_done = VL_RAND_RESET_I(1);
    vlSelf->ia_data_valid = VL_RAND_RESET_I(1);
    vlSelf->cb__DOT__ia_data_valid = VL_RAND_RESET_I(1);
    vlSelf->cb__DOT__ia_calc_done = VL_RAND_RESET_I(1);
    vlSelf->cb__DOT__ia_sending_done = VL_RAND_RESET_I(1);
    vlSelf->cb__DOT__load_ia_req = VL_RAND_RESET_I(1);
    vlSelf->__Vclocking_prev__cb__DOT__load_ia_req = VL_RAND_RESET_I(1);
    vlSelf->__Vclocking_prev__cb__DOT__ia_sending_done = VL_RAND_RESET_I(1);
    vlSelf->__Vclocking_prev__cb__DOT__ia_calc_done = VL_RAND_RESET_I(1);
    vlSelf->__Vclocking_prev__cb__DOT__ia_data_valid = VL_RAND_RESET_I(1);
    vlSelf->__Vintraval_h730566a9__0 = VL_RAND_RESET_I(1);
    vlSelf->__Vintraval_h7dd9d4e9__0 = VL_RAND_RESET_I(1);
    vlSelf->__Vintraval_he9ec439d__0 = VL_RAND_RESET_I(1);
    vlSelf->__Vintraval_h2002632b__0 = VL_RAND_RESET_I(1);
}
