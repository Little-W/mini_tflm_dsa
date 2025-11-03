// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Design implementation internals
// See Vmma_controller_if.h for the primary calling header

#include "Vmma_controller_if__pch.h"
#include "Vmma_controller_if__Syms.h"
#include "Vmma_controller_if_requant_if.h"

VL_INLINE_OPT VlCoroutine Vmma_controller_if_requant_if___obs_sequent__TOP__tb_mma_controller__DOT__quant_if__0____Vfork_1__0(Vmma_controller_if_requant_if* vlSelf, CData/*0:0*/ __Vintraval_hba1b87f4__0) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+        Vmma_controller_if_requant_if___obs_sequent__TOP__tb_mma_controller__DOT__quant_if__0____Vfork_1__0\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    if (((IData)(vlSelfRef.__Vclocking_prev__cb__DOT__quant_params_valid) 
         != (IData)(vlSelfRef.cb__DOT__quant_params_valid))) {
        __Vintraval_hba1b87f4__0 = vlSelfRef.cb__DOT__quant_params_valid;
        co_await vlSymsp->TOP.__VdlySched.delay(0x3e8ULL, 
                                                nullptr, 
                                                "mma_controller_if.sv", 
                                                114);
        vlSelfRef.quant_params_valid = __Vintraval_hba1b87f4__0;
        vlSelfRef.__Vclocking_prev__cb__DOT__quant_params_valid 
            = vlSelfRef.cb__DOT__quant_params_valid;
    }
}

VL_INLINE_OPT VlCoroutine Vmma_controller_if_requant_if___obs_sequent__TOP__tb_mma_controller__DOT__quant_if__0____Vfork_2__0(Vmma_controller_if_requant_if* vlSelf, CData/*0:0*/ __Vintraval_hcbf2d946__0) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+        Vmma_controller_if_requant_if___obs_sequent__TOP__tb_mma_controller__DOT__quant_if__0____Vfork_2__0\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    if (((IData)(vlSelfRef.__Vclocking_prev__cb__DOT__load_quant_req) 
         != (IData)(vlSelfRef.cb__DOT__load_quant_req))) {
        __Vintraval_hcbf2d946__0 = vlSelfRef.cb__DOT__load_quant_req;
        co_await vlSymsp->TOP.__VdlySched.delay(0x3e8ULL, 
                                                nullptr, 
                                                "mma_controller_if.sv", 
                                                112);
        vlSelfRef.load_quant_req = __Vintraval_hcbf2d946__0;
        vlSelfRef.__Vclocking_prev__cb__DOT__load_quant_req 
            = vlSelfRef.cb__DOT__load_quant_req;
    }
}
