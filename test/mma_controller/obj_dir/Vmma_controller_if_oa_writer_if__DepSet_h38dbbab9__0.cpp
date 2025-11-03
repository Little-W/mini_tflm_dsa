// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Design implementation internals
// See Vmma_controller_if.h for the primary calling header

#include "Vmma_controller_if__pch.h"
#include "Vmma_controller_if__Syms.h"
#include "Vmma_controller_if_oa_writer_if.h"

VL_INLINE_OPT VlCoroutine Vmma_controller_if_oa_writer_if___obs_sequent__TOP__tb_mma_controller__DOT__oa_if__0____Vfork_1__0(Vmma_controller_if_oa_writer_if* vlSelf, CData/*0:0*/ __Vintraval_h32b2c1a4__0) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+        Vmma_controller_if_oa_writer_if___obs_sequent__TOP__tb_mma_controller__DOT__oa_if__0____Vfork_1__0\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    if (((IData)(vlSelfRef.__Vclocking_prev__cb__DOT__oa_calc_over) 
         != (IData)(vlSelfRef.cb__DOT__oa_calc_over))) {
        __Vintraval_h32b2c1a4__0 = vlSelfRef.cb__DOT__oa_calc_over;
        co_await vlSymsp->TOP.__VdlySched.delay(0x3e8ULL, 
                                                nullptr, 
                                                "mma_controller_if.sv", 
                                                143);
        vlSelfRef.oa_calc_over = __Vintraval_h32b2c1a4__0;
        vlSelfRef.__Vclocking_prev__cb__DOT__oa_calc_over 
            = vlSelfRef.cb__DOT__oa_calc_over;
    }
}

VL_INLINE_OPT VlCoroutine Vmma_controller_if_oa_writer_if___obs_sequent__TOP__tb_mma_controller__DOT__oa_if__0____Vfork_2__0(Vmma_controller_if_oa_writer_if* vlSelf, CData/*0:0*/ __Vintraval_hcc7d76c7__0) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+        Vmma_controller_if_oa_writer_if___obs_sequent__TOP__tb_mma_controller__DOT__oa_if__0____Vfork_2__0\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    if (((IData)(vlSelfRef.__Vclocking_prev__cb__DOT__write_done) 
         != (IData)(vlSelfRef.cb__DOT__write_done))) {
        __Vintraval_hcc7d76c7__0 = vlSelfRef.cb__DOT__write_done;
        co_await vlSymsp->TOP.__VdlySched.delay(0x3e8ULL, 
                                                nullptr, 
                                                "mma_controller_if.sv", 
                                                142);
        vlSelfRef.write_done = __Vintraval_hcc7d76c7__0;
        vlSelfRef.__Vclocking_prev__cb__DOT__write_done 
            = vlSelfRef.cb__DOT__write_done;
    }
}

VL_INLINE_OPT VlCoroutine Vmma_controller_if_oa_writer_if___obs_sequent__TOP__tb_mma_controller__DOT__oa_if__0____Vfork_3__0(Vmma_controller_if_oa_writer_if* vlSelf, CData/*0:0*/ __Vintraval_h541f8722__0) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+        Vmma_controller_if_oa_writer_if___obs_sequent__TOP__tb_mma_controller__DOT__oa_if__0____Vfork_3__0\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    if (((IData)(vlSelfRef.__Vclocking_prev__cb__DOT__write_oa_req) 
         != (IData)(vlSelfRef.cb__DOT__write_oa_req))) {
        __Vintraval_h541f8722__0 = vlSelfRef.cb__DOT__write_oa_req;
        co_await vlSymsp->TOP.__VdlySched.delay(0x3e8ULL, 
                                                nullptr, 
                                                "mma_controller_if.sv", 
                                                140);
        vlSelfRef.write_oa_req = __Vintraval_h541f8722__0;
        vlSelfRef.__Vclocking_prev__cb__DOT__write_oa_req 
            = vlSelfRef.cb__DOT__write_oa_req;
    }
}
