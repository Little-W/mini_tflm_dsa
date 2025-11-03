// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Design implementation internals
// See Vmma_controller_if.h for the primary calling header

#include "Vmma_controller_if__pch.h"
#include "Vmma_controller_if_compute_core_if.h"

VlCoroutine Vmma_controller_if_compute_core_if___obs_sequent__TOP__tb_mma_controller__DOT__comp_if__0____Vfork_1__0(Vmma_controller_if_compute_core_if* vlSelf, CData/*0:0*/ __Vintraval_h5f1db4e6__0);
VlCoroutine Vmma_controller_if_compute_core_if___obs_sequent__TOP__tb_mma_controller__DOT__comp_if__0____Vfork_2__0(Vmma_controller_if_compute_core_if* vlSelf, CData/*0:0*/ __Vintraval_ha30227c0__0);

VL_INLINE_OPT void Vmma_controller_if_compute_core_if___obs_sequent__TOP__tb_mma_controller__DOT__comp_if__0(Vmma_controller_if_compute_core_if* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+        Vmma_controller_if_compute_core_if___obs_sequent__TOP__tb_mma_controller__DOT__comp_if__0\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    vlSelfRef.cb.fire();
    Vmma_controller_if_compute_core_if___obs_sequent__TOP__tb_mma_controller__DOT__comp_if__0____Vfork_1__0(vlSelf, vlSelfRef.__Vintraval_h5f1db4e6__0);
    Vmma_controller_if_compute_core_if___obs_sequent__TOP__tb_mma_controller__DOT__comp_if__0____Vfork_2__0(vlSelf, vlSelfRef.__Vintraval_ha30227c0__0);
}

std::string VL_TO_STRING(const Vmma_controller_if_compute_core_if* obj) {
    VL_DEBUG_IF(VL_DBG_MSGF("+        Vmma_controller_if_compute_core_if::VL_TO_STRING\n"); );
    // Body
    return (obj ? obj->name() : "null");
}
