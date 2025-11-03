// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Design implementation internals
// See Vmma_controller_if.h for the primary calling header

#include "Vmma_controller_if__pch.h"
#include "Vmma_controller_if_bias_loader_if.h"

VL_ATTR_COLD void Vmma_controller_if_bias_loader_if___eval_static__TOP__tb_mma_controller__DOT__bias_if(Vmma_controller_if_bias_loader_if* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+        Vmma_controller_if_bias_loader_if___eval_static__TOP__tb_mma_controller__DOT__bias_if\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    vlSelfRef.cb__DOT__load_bias_req = vlSelfRef.load_bias_req;
    vlSelfRef.__Vclocking_prev__cb__DOT__load_bias_req 
        = vlSelfRef.cb__DOT__load_bias_req;
    vlSelfRef.cb__DOT__bias_valid = vlSelfRef.bias_valid;
    vlSelfRef.__Vclocking_prev__cb__DOT__bias_valid 
        = vlSelfRef.cb__DOT__bias_valid;
}

VL_ATTR_COLD void Vmma_controller_if_bias_loader_if___ctor_var_reset(Vmma_controller_if_bias_loader_if* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+        Vmma_controller_if_bias_loader_if___ctor_var_reset\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    vlSelf->clk = VL_RAND_RESET_I(1);
    vlSelf->load_bias_req = VL_RAND_RESET_I(1);
    vlSelf->bias_valid = VL_RAND_RESET_I(1);
    vlSelf->cb__DOT__bias_valid = VL_RAND_RESET_I(1);
    vlSelf->cb__DOT__load_bias_req = VL_RAND_RESET_I(1);
    vlSelf->__Vclocking_prev__cb__DOT__load_bias_req = VL_RAND_RESET_I(1);
    vlSelf->__Vclocking_prev__cb__DOT__bias_valid = VL_RAND_RESET_I(1);
    vlSelf->__Vintraval_hbfa2d195__0 = VL_RAND_RESET_I(1);
    vlSelf->__Vintraval_hcf882d00__0 = VL_RAND_RESET_I(1);
}
