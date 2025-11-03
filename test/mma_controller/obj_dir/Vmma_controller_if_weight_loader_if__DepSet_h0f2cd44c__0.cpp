// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Design implementation internals
// See Vmma_controller_if.h for the primary calling header

#include "Vmma_controller_if__pch.h"
#include "Vmma_controller_if__Syms.h"
#include "Vmma_controller_if_weight_loader_if.h"

VL_INLINE_OPT VlCoroutine Vmma_controller_if_weight_loader_if___obs_sequent__TOP__tb_mma_controller__DOT__weight_if__0____Vfork_1__0(Vmma_controller_if_weight_loader_if* vlSelf, CData/*0:0*/ __Vintraval_h33b037ac__0) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+        Vmma_controller_if_weight_loader_if___obs_sequent__TOP__tb_mma_controller__DOT__weight_if__0____Vfork_1__0\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    if (((IData)(vlSelfRef.__Vclocking_prev__cb__DOT__weight_data_valid) 
         != (IData)(vlSelfRef.cb__DOT__weight_data_valid))) {
        __Vintraval_h33b037ac__0 = vlSelfRef.cb__DOT__weight_data_valid;
        co_await vlSymsp->TOP.__VdlySched.delay(0x3e8ULL, 
                                                nullptr, 
                                                "mma_controller_if.sv", 
                                                56);
        vlSelfRef.weight_data_valid = __Vintraval_h33b037ac__0;
        vlSelfRef.__Vclocking_prev__cb__DOT__weight_data_valid 
            = vlSelfRef.cb__DOT__weight_data_valid;
    }
}

VL_INLINE_OPT VlCoroutine Vmma_controller_if_weight_loader_if___obs_sequent__TOP__tb_mma_controller__DOT__weight_if__0____Vfork_2__0(Vmma_controller_if_weight_loader_if* vlSelf, CData/*0:0*/ __Vintraval_hbff9f8db__0) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+        Vmma_controller_if_weight_loader_if___obs_sequent__TOP__tb_mma_controller__DOT__weight_if__0____Vfork_2__0\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    if (((IData)(vlSelfRef.__Vclocking_prev__cb__DOT__weight_sending_done) 
         != (IData)(vlSelfRef.cb__DOT__weight_sending_done))) {
        __Vintraval_hbff9f8db__0 = vlSelfRef.cb__DOT__weight_sending_done;
        co_await vlSymsp->TOP.__VdlySched.delay(0x3e8ULL, 
                                                nullptr, 
                                                "mma_controller_if.sv", 
                                                55);
        vlSelfRef.weight_sending_done = __Vintraval_hbff9f8db__0;
        vlSelfRef.__Vclocking_prev__cb__DOT__weight_sending_done 
            = vlSelfRef.cb__DOT__weight_sending_done;
    }
}

VL_INLINE_OPT VlCoroutine Vmma_controller_if_weight_loader_if___obs_sequent__TOP__tb_mma_controller__DOT__weight_if__0____Vfork_3__0(Vmma_controller_if_weight_loader_if* vlSelf, CData/*0:0*/ __Vintraval_h995cdc00__0) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+        Vmma_controller_if_weight_loader_if___obs_sequent__TOP__tb_mma_controller__DOT__weight_if__0____Vfork_3__0\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    if (((IData)(vlSelfRef.__Vclocking_prev__cb__DOT__load_weight_req) 
         != (IData)(vlSelfRef.cb__DOT__load_weight_req))) {
        __Vintraval_h995cdc00__0 = vlSelfRef.cb__DOT__load_weight_req;
        co_await vlSymsp->TOP.__VdlySched.delay(0x3e8ULL, 
                                                nullptr, 
                                                "mma_controller_if.sv", 
                                                52);
        vlSelfRef.load_weight_req = __Vintraval_h995cdc00__0;
        vlSelfRef.__Vclocking_prev__cb__DOT__load_weight_req 
            = vlSelfRef.cb__DOT__load_weight_req;
    }
}
