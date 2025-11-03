// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Design implementation internals
// See Vtb_compute_core.h for the primary calling header

#include "Vtb_compute_core__pch.h"
#include "Vtb_compute_core___024root.h"

VL_ATTR_COLD void Vtb_compute_core___024root___eval_initial__TOP(Vtb_compute_core___024root* vlSelf);
VlCoroutine Vtb_compute_core___024root___eval_initial__TOP__Vtiming__0(Vtb_compute_core___024root* vlSelf);
VlCoroutine Vtb_compute_core___024root___eval_initial__TOP__Vtiming__1(Vtb_compute_core___024root* vlSelf);

void Vtb_compute_core___024root___eval_initial(Vtb_compute_core___024root* vlSelf) {
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_compute_core___024root___eval_initial\n"); );
    Vtb_compute_core__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    auto& vlSelfRef = std::ref(*vlSelf).get();
    // Body
    Vtb_compute_core___024root___eval_initial__TOP(vlSelf);
    vlSelfRef.__Vm_traceActivity[1U] = 1U;
    Vtb_compute_core___024root___eval_initial__TOP__Vtiming__0(vlSelf);
    Vtb_compute_core___024root___eval_initial__TOP__Vtiming__1(vlSelf);
}

void Vtb_compute_core___024root___eval_act(Vtb_compute_core___024root* vlSelf) {
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_compute_core___024root___eval_act\n"); );
    Vtb_compute_core__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    auto& vlSelfRef = std::ref(*vlSelf).get();
}

VL_INLINE_OPT void Vtb_compute_core___024root___nba_sequent__TOP__1(Vtb_compute_core___024root* vlSelf) {
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_compute_core___024root___nba_sequent__TOP__1\n"); );
    Vtb_compute_core__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    auto& vlSelfRef = std::ref(*vlSelf).get();
    // Body
    if (vlSelfRef.__VdlySet__tb_compute_core__DOT__clk__v0) {
        vlSelfRef.__VdlySet__tb_compute_core__DOT__clk__v0 = 0U;
        vlSelfRef.tb_compute_core__DOT__clk = vlSelfRef.__VdlyVal__tb_compute_core__DOT__clk__v0;
    }
}

void Vtb_compute_core___024root___timing_resume(Vtb_compute_core___024root* vlSelf) {
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_compute_core___024root___timing_resume\n"); );
    Vtb_compute_core__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    auto& vlSelfRef = std::ref(*vlSelf).get();
    // Body
    if ((0x200ULL & vlSelfRef.__VactTriggered.word(0U))) {
        vlSelfRef.__VtrigSched_h08f02b2e__0.resume(
                                                   "@([event] tb_compute_core.tb_if.cb)");
    }
    if ((0x400ULL & vlSelfRef.__VactTriggered.word(0U))) {
        vlSelfRef.__VtrigSched_h76832c6c__0.resume(
                                                   "@( tb_compute_core.__Vcellout__u_dut__partial_sum_calc_over)");
    }
    if ((0x800ULL & vlSelfRef.__VactTriggered.word(0U))) {
        vlSelfRef.__VtrigSched_hf86aeebc__0.resume(
                                                   "@( tb_compute_core.__Vcellout__u_dut__tile_calc_over)");
    }
    if ((2ULL & vlSelfRef.__VactTriggered.word(0U))) {
        vlSelfRef.__VdlySched.resume();
    }
}

void Vtb_compute_core___024root___timing_commit(Vtb_compute_core___024root* vlSelf) {
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_compute_core___024root___timing_commit\n"); );
    Vtb_compute_core__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    auto& vlSelfRef = std::ref(*vlSelf).get();
    // Body
    if ((! (0x200ULL & vlSelfRef.__VactTriggered.word(0U)))) {
        vlSelfRef.__VtrigSched_h08f02b2e__0.commit(
                                                   "@([event] tb_compute_core.tb_if.cb)");
    }
    if ((! (0x400ULL & vlSelfRef.__VactTriggered.word(0U)))) {
        vlSelfRef.__VtrigSched_h76832c6c__0.commit(
                                                   "@( tb_compute_core.__Vcellout__u_dut__partial_sum_calc_over)");
    }
    if ((! (0x800ULL & vlSelfRef.__VactTriggered.word(0U)))) {
        vlSelfRef.__VtrigSched_hf86aeebc__0.commit(
                                                   "@( tb_compute_core.__Vcellout__u_dut__tile_calc_over)");
    }
}

void Vtb_compute_core___024root___eval_triggers__act(Vtb_compute_core___024root* vlSelf);

bool Vtb_compute_core___024root___eval_phase__act(Vtb_compute_core___024root* vlSelf) {
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_compute_core___024root___eval_phase__act\n"); );
    Vtb_compute_core__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    auto& vlSelfRef = std::ref(*vlSelf).get();
    // Init
    VlTriggerVec<12> __VpreTriggered;
    CData/*0:0*/ __VactExecute;
    // Body
    Vtb_compute_core___024root___eval_triggers__act(vlSelf);
    Vtb_compute_core___024root___timing_commit(vlSelf);
    __VactExecute = vlSelfRef.__VactTriggered.any();
    if (__VactExecute) {
        __VpreTriggered.andNot(vlSelfRef.__VactTriggered, vlSelfRef.__VnbaTriggered);
        vlSelfRef.__VnbaTriggered.thisOr(vlSelfRef.__VactTriggered);
        Vtb_compute_core___024root___timing_resume(vlSelf);
        Vtb_compute_core___024root___eval_act(vlSelf);
    }
    return (__VactExecute);
}

void Vtb_compute_core___024root___eval_nba(Vtb_compute_core___024root* vlSelf);

bool Vtb_compute_core___024root___eval_phase__nba(Vtb_compute_core___024root* vlSelf) {
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_compute_core___024root___eval_phase__nba\n"); );
    Vtb_compute_core__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    auto& vlSelfRef = std::ref(*vlSelf).get();
    // Init
    CData/*0:0*/ __VnbaExecute;
    // Body
    __VnbaExecute = vlSelfRef.__VnbaTriggered.any();
    if (__VnbaExecute) {
        vlSelfRef.__VobsTriggered.thisOr(vlSelfRef.__VnbaTriggered);
        Vtb_compute_core___024root___eval_nba(vlSelf);
        vlSelfRef.__VnbaTriggered.clear();
    }
    return (__VnbaExecute);
}

void Vtb_compute_core___024root___eval_obs(Vtb_compute_core___024root* vlSelf);

bool Vtb_compute_core___024root___eval_phase__obs(Vtb_compute_core___024root* vlSelf) {
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_compute_core___024root___eval_phase__obs\n"); );
    Vtb_compute_core__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    auto& vlSelfRef = std::ref(*vlSelf).get();
    // Init
    CData/*0:0*/ __VobsExecute;
    // Body
    __VobsExecute = vlSelfRef.__VobsTriggered.any();
    if (__VobsExecute) {
        vlSelfRef.__VreactTriggered.thisOr(vlSelfRef.__VobsTriggered);
        Vtb_compute_core___024root___eval_obs(vlSelf);
        vlSelfRef.__VobsTriggered.clear();
    }
    return (__VobsExecute);
}

void Vtb_compute_core___024root___eval_react(Vtb_compute_core___024root* vlSelf);

bool Vtb_compute_core___024root___eval_phase__react(Vtb_compute_core___024root* vlSelf) {
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_compute_core___024root___eval_phase__react\n"); );
    Vtb_compute_core__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    auto& vlSelfRef = std::ref(*vlSelf).get();
    // Init
    CData/*0:0*/ __VreactExecute;
    // Body
    __VreactExecute = vlSelfRef.__VreactTriggered.any();
    if (__VreactExecute) {
        Vtb_compute_core___024root___eval_react(vlSelf);
        vlSelfRef.__VreactTriggered.clear();
    }
    return (__VreactExecute);
}

#ifdef VL_DEBUG
VL_ATTR_COLD void Vtb_compute_core___024root___dump_triggers__react(Vtb_compute_core___024root* vlSelf);
#endif  // VL_DEBUG
#ifdef VL_DEBUG
VL_ATTR_COLD void Vtb_compute_core___024root___dump_triggers__obs(Vtb_compute_core___024root* vlSelf);
#endif  // VL_DEBUG
#ifdef VL_DEBUG
VL_ATTR_COLD void Vtb_compute_core___024root___dump_triggers__nba(Vtb_compute_core___024root* vlSelf);
#endif  // VL_DEBUG
#ifdef VL_DEBUG
VL_ATTR_COLD void Vtb_compute_core___024root___dump_triggers__act(Vtb_compute_core___024root* vlSelf);
#endif  // VL_DEBUG

void Vtb_compute_core___024root___eval(Vtb_compute_core___024root* vlSelf) {
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_compute_core___024root___eval\n"); );
    Vtb_compute_core__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    auto& vlSelfRef = std::ref(*vlSelf).get();
    // Init
    IData/*31:0*/ __VreactIterCount;
    CData/*0:0*/ __VreactContinue;
    // Body
    __VreactIterCount = 0U;
    __VreactContinue = 1U;
    while (__VreactContinue) {
        if (VL_UNLIKELY(((0x64U < __VreactIterCount)))) {
#ifdef VL_DEBUG
            Vtb_compute_core___024root___dump_triggers__react(vlSelf);
#endif
            VL_FATAL_MT("tb_compute_core.sv", 3, "", "Reactive region did not converge.");
        }
        __VreactIterCount = ((IData)(1U) + __VreactIterCount);
        __VreactContinue = 0U;
        vlSelfRef.__VobsIterCount = 0U;
        vlSelfRef.__VobsContinue = 1U;
        while (vlSelfRef.__VobsContinue) {
            if (VL_UNLIKELY(((0x64U < vlSelfRef.__VobsIterCount)))) {
#ifdef VL_DEBUG
                Vtb_compute_core___024root___dump_triggers__obs(vlSelf);
#endif
                VL_FATAL_MT("tb_compute_core.sv", 3, "", "Observed region did not converge.");
            }
            vlSelfRef.__VobsIterCount = ((IData)(1U) 
                                         + vlSelfRef.__VobsIterCount);
            vlSelfRef.__VobsContinue = 0U;
            vlSelfRef.__VnbaIterCount = 0U;
            vlSelfRef.__VnbaContinue = 1U;
            while (vlSelfRef.__VnbaContinue) {
                if (VL_UNLIKELY(((0x64U < vlSelfRef.__VnbaIterCount)))) {
#ifdef VL_DEBUG
                    Vtb_compute_core___024root___dump_triggers__nba(vlSelf);
#endif
                    VL_FATAL_MT("tb_compute_core.sv", 3, "", "NBA region did not converge.");
                }
                vlSelfRef.__VnbaIterCount = ((IData)(1U) 
                                             + vlSelfRef.__VnbaIterCount);
                vlSelfRef.__VnbaContinue = 0U;
                vlSelfRef.__VactIterCount = 0U;
                vlSelfRef.__VactContinue = 1U;
                while (vlSelfRef.__VactContinue) {
                    if (VL_UNLIKELY(((0x64U < vlSelfRef.__VactIterCount)))) {
#ifdef VL_DEBUG
                        Vtb_compute_core___024root___dump_triggers__act(vlSelf);
#endif
                        VL_FATAL_MT("tb_compute_core.sv", 3, "", "Active region did not converge.");
                    }
                    vlSelfRef.__VactIterCount = ((IData)(1U) 
                                                 + vlSelfRef.__VactIterCount);
                    vlSelfRef.__VactContinue = 0U;
                    if (Vtb_compute_core___024root___eval_phase__act(vlSelf)) {
                        vlSelfRef.__VactContinue = 1U;
                    }
                }
                if (Vtb_compute_core___024root___eval_phase__nba(vlSelf)) {
                    vlSelfRef.__VnbaContinue = 1U;
                }
            }
            if (Vtb_compute_core___024root___eval_phase__obs(vlSelf)) {
                vlSelfRef.__VobsContinue = 1U;
            }
        }
        if (Vtb_compute_core___024root___eval_phase__react(vlSelf)) {
            __VreactContinue = 1U;
        }
    }
}

#ifdef VL_DEBUG
void Vtb_compute_core___024root___eval_debug_assertions(Vtb_compute_core___024root* vlSelf) {
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_compute_core___024root___eval_debug_assertions\n"); );
    Vtb_compute_core__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    auto& vlSelfRef = std::ref(*vlSelf).get();
}
#endif  // VL_DEBUG
