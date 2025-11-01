// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Design implementation internals
// See Vtb_e203_nice.h for the primary calling header

#include "Vtb_e203_nice__pch.h"
#include "Vtb_e203_nice___024root.h"

VL_ATTR_COLD void Vtb_e203_nice___024root___eval_initial__TOP(Vtb_e203_nice___024root* vlSelf);
VlCoroutine Vtb_e203_nice___024root___eval_initial__TOP__Vtiming__0(Vtb_e203_nice___024root* vlSelf);
VlCoroutine Vtb_e203_nice___024root___eval_initial__TOP__Vtiming__1(Vtb_e203_nice___024root* vlSelf);

void Vtb_e203_nice___024root___eval_initial(Vtb_e203_nice___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vtb_e203_nice__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_e203_nice___024root___eval_initial\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    Vtb_e203_nice___024root___eval_initial__TOP(vlSelf);
    Vtb_e203_nice___024root___eval_initial__TOP__Vtiming__0(vlSelf);
    Vtb_e203_nice___024root___eval_initial__TOP__Vtiming__1(vlSelf);
    vlSelfRef.__Vtrigprevexpr___TOP__tb_e203_nice__DOT__clk__0 
        = vlSelfRef.tb_e203_nice__DOT__clk;
    vlSelfRef.__Vtrigprevexpr___TOP__tb_e203_nice__DOT__rst_n__0 
        = vlSelfRef.tb_e203_nice__DOT__rst_n;
    vlSelfRef.__Vtrigprevexpr_haaedec92__0 = ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_decode_dispatch__DOT__is_csr_inst)
                                               ? (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_ready)
                                               : (0U 
                                                  == (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_mma_top__DOT__state)));
    vlSelfRef.__Vtrigprevexpr_h57ac893f__0 = ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__csr_buf_rd_valid) 
                                              | (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__mma_buf_rd_valid));
}

VL_INLINE_OPT VlCoroutine Vtb_e203_nice___024root___eval_initial__TOP__Vtiming__1(Vtb_e203_nice___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vtb_e203_nice__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_e203_nice___024root___eval_initial__TOP__Vtiming__1\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    while (1U) {
        co_await vlSelfRef.__VdlySched.delay(0x1388ULL, 
                                             nullptr, 
                                             "tb_e203_nice.sv", 
                                             53);
        vlSelfRef.__VdlyVal__tb_e203_nice__DOT__clk__v0 
            = (1U & (~ (IData)(vlSelfRef.tb_e203_nice__DOT__clk)));
        vlSelfRef.__VdlySet__tb_e203_nice__DOT__clk__v0 = 1U;
    }
}

void Vtb_e203_nice___024root___act_comb__TOP__0(Vtb_e203_nice___024root* vlSelf);

void Vtb_e203_nice___024root___eval_act(Vtb_e203_nice___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vtb_e203_nice__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_e203_nice___024root___eval_act\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    if ((0x3cULL & vlSelfRef.__VactTriggered.word(0U))) {
        Vtb_e203_nice___024root___act_comb__TOP__0(vlSelf);
    }
}

void Vtb_e203_nice___024root___nba_sequent__TOP__0(Vtb_e203_nice___024root* vlSelf);
void Vtb_e203_nice___024root___nba_sequent__TOP__1(Vtb_e203_nice___024root* vlSelf);

void Vtb_e203_nice___024root___eval_nba(Vtb_e203_nice___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vtb_e203_nice__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_e203_nice___024root___eval_nba\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    if ((1ULL & vlSelfRef.__VnbaTriggered.word(0U))) {
        Vtb_e203_nice___024root___nba_sequent__TOP__0(vlSelf);
        vlSelfRef.__Vm_traceActivity[1U] = 1U;
    }
    if ((2ULL & vlSelfRef.__VnbaTriggered.word(0U))) {
        Vtb_e203_nice___024root___nba_sequent__TOP__1(vlSelf);
    }
    if ((0x3dULL & vlSelfRef.__VnbaTriggered.word(0U))) {
        Vtb_e203_nice___024root___act_comb__TOP__0(vlSelf);
    }
}

VL_INLINE_OPT void Vtb_e203_nice___024root___nba_sequent__TOP__1(Vtb_e203_nice___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vtb_e203_nice__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_e203_nice___024root___nba_sequent__TOP__1\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    if (vlSelfRef.__VdlySet__tb_e203_nice__DOT__clk__v0) {
        vlSelfRef.__VdlySet__tb_e203_nice__DOT__clk__v0 = 0U;
        vlSelfRef.tb_e203_nice__DOT__clk = vlSelfRef.__VdlyVal__tb_e203_nice__DOT__clk__v0;
    }
}

void Vtb_e203_nice___024root___timing_resume(Vtb_e203_nice___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vtb_e203_nice__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_e203_nice___024root___timing_resume\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    if ((4ULL & vlSelfRef.__VactTriggered.word(0U))) {
        vlSelfRef.__VtrigSched_hef2abcd9__0.resume(
                                                   "@(posedge tb_e203_nice.clk)");
    }
    if ((8ULL & vlSelfRef.__VactTriggered.word(0U))) {
        vlSelfRef.__VtrigSched_hc83f1028__0.resume(
                                                   "@([event] tb_e203_nice.nice_if_inst.cb)");
    }
    if ((0x10ULL & vlSelfRef.__VactTriggered.word(0U))) {
        vlSelfRef.__VtrigSched_h3ada226f__0.resume(
                                                   "@([changed] (tb_e203_nice.u_nice_core.u_decode_dispatch.is_csr_inst ? tb_e203_nice.u_nice_core.csr_ready : (2'h0 == tb_e203_nice.u_nice_core.u_mma_top.state)))");
    }
    if ((0x20ULL & vlSelfRef.__VactTriggered.word(0U))) {
        vlSelfRef.__VtrigSched_hcf9bbd92__0.resume(
                                                   "@([changed] (tb_e203_nice.u_nice_core.u_wbu.csr_buf_rd_valid | tb_e203_nice.u_nice_core.u_wbu.mma_buf_rd_valid))");
    }
    if ((2ULL & vlSelfRef.__VactTriggered.word(0U))) {
        vlSelfRef.__VdlySched.resume();
    }
}

void Vtb_e203_nice___024root___timing_commit(Vtb_e203_nice___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vtb_e203_nice__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_e203_nice___024root___timing_commit\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    if ((! (4ULL & vlSelfRef.__VactTriggered.word(0U)))) {
        vlSelfRef.__VtrigSched_hef2abcd9__0.commit(
                                                   "@(posedge tb_e203_nice.clk)");
    }
    if ((! (8ULL & vlSelfRef.__VactTriggered.word(0U)))) {
        vlSelfRef.__VtrigSched_hc83f1028__0.commit(
                                                   "@([event] tb_e203_nice.nice_if_inst.cb)");
    }
    if ((! (0x10ULL & vlSelfRef.__VactTriggered.word(0U)))) {
        vlSelfRef.__VtrigSched_h3ada226f__0.commit(
                                                   "@([changed] (tb_e203_nice.u_nice_core.u_decode_dispatch.is_csr_inst ? tb_e203_nice.u_nice_core.csr_ready : (2'h0 == tb_e203_nice.u_nice_core.u_mma_top.state)))");
    }
    if ((! (0x20ULL & vlSelfRef.__VactTriggered.word(0U)))) {
        vlSelfRef.__VtrigSched_hcf9bbd92__0.commit(
                                                   "@([changed] (tb_e203_nice.u_nice_core.u_wbu.csr_buf_rd_valid | tb_e203_nice.u_nice_core.u_wbu.mma_buf_rd_valid))");
    }
}

void Vtb_e203_nice___024root___eval_triggers__act(Vtb_e203_nice___024root* vlSelf);

bool Vtb_e203_nice___024root___eval_phase__act(Vtb_e203_nice___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vtb_e203_nice__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_e203_nice___024root___eval_phase__act\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Init
    VlTriggerVec<6> __VpreTriggered;
    CData/*0:0*/ __VactExecute;
    // Body
    Vtb_e203_nice___024root___eval_triggers__act(vlSelf);
    Vtb_e203_nice___024root___timing_commit(vlSelf);
    __VactExecute = vlSelfRef.__VactTriggered.any();
    if (__VactExecute) {
        __VpreTriggered.andNot(vlSelfRef.__VactTriggered, vlSelfRef.__VnbaTriggered);
        vlSelfRef.__VnbaTriggered.thisOr(vlSelfRef.__VactTriggered);
        Vtb_e203_nice___024root___timing_resume(vlSelf);
        Vtb_e203_nice___024root___eval_act(vlSelf);
    }
    return (__VactExecute);
}

bool Vtb_e203_nice___024root___eval_phase__nba(Vtb_e203_nice___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vtb_e203_nice__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_e203_nice___024root___eval_phase__nba\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Init
    CData/*0:0*/ __VnbaExecute;
    // Body
    __VnbaExecute = vlSelfRef.__VnbaTriggered.any();
    if (__VnbaExecute) {
        vlSelfRef.__VobsTriggered.thisOr(vlSelfRef.__VnbaTriggered);
        Vtb_e203_nice___024root___eval_nba(vlSelf);
        vlSelfRef.__VnbaTriggered.clear();
    }
    return (__VnbaExecute);
}

void Vtb_e203_nice___024root___eval_obs(Vtb_e203_nice___024root* vlSelf);

bool Vtb_e203_nice___024root___eval_phase__obs(Vtb_e203_nice___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vtb_e203_nice__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_e203_nice___024root___eval_phase__obs\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Init
    CData/*0:0*/ __VobsExecute;
    // Body
    __VobsExecute = vlSelfRef.__VobsTriggered.any();
    if (__VobsExecute) {
        vlSelfRef.__VreactTriggered.thisOr(vlSelfRef.__VobsTriggered);
        Vtb_e203_nice___024root___eval_obs(vlSelf);
        vlSelfRef.__VobsTriggered.clear();
    }
    return (__VobsExecute);
}

void Vtb_e203_nice___024root___eval_react(Vtb_e203_nice___024root* vlSelf);

bool Vtb_e203_nice___024root___eval_phase__react(Vtb_e203_nice___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vtb_e203_nice__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_e203_nice___024root___eval_phase__react\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Init
    CData/*0:0*/ __VreactExecute;
    // Body
    __VreactExecute = vlSelfRef.__VreactTriggered.any();
    if (__VreactExecute) {
        Vtb_e203_nice___024root___eval_react(vlSelf);
        vlSelfRef.__VreactTriggered.clear();
    }
    return (__VreactExecute);
}

#ifdef VL_DEBUG
VL_ATTR_COLD void Vtb_e203_nice___024root___dump_triggers__react(Vtb_e203_nice___024root* vlSelf);
#endif  // VL_DEBUG
#ifdef VL_DEBUG
VL_ATTR_COLD void Vtb_e203_nice___024root___dump_triggers__obs(Vtb_e203_nice___024root* vlSelf);
#endif  // VL_DEBUG
#ifdef VL_DEBUG
VL_ATTR_COLD void Vtb_e203_nice___024root___dump_triggers__nba(Vtb_e203_nice___024root* vlSelf);
#endif  // VL_DEBUG
#ifdef VL_DEBUG
VL_ATTR_COLD void Vtb_e203_nice___024root___dump_triggers__act(Vtb_e203_nice___024root* vlSelf);
#endif  // VL_DEBUG

void Vtb_e203_nice___024root___eval(Vtb_e203_nice___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vtb_e203_nice__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_e203_nice___024root___eval\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Init
    IData/*31:0*/ __VreactIterCount;
    CData/*0:0*/ __VreactContinue;
    // Body
    __VreactIterCount = 0U;
    __VreactContinue = 1U;
    while (__VreactContinue) {
        if (VL_UNLIKELY((0x64U < __VreactIterCount))) {
#ifdef VL_DEBUG
            Vtb_e203_nice___024root___dump_triggers__react(vlSelf);
#endif
            VL_FATAL_MT("tb_e203_nice.sv", 5, "", "Reactive region did not converge.");
        }
        __VreactIterCount = ((IData)(1U) + __VreactIterCount);
        __VreactContinue = 0U;
        vlSelfRef.__VobsIterCount = 0U;
        vlSelfRef.__VobsContinue = 1U;
        while (vlSelfRef.__VobsContinue) {
            if (VL_UNLIKELY((0x64U < vlSelfRef.__VobsIterCount))) {
#ifdef VL_DEBUG
                Vtb_e203_nice___024root___dump_triggers__obs(vlSelf);
#endif
                VL_FATAL_MT("tb_e203_nice.sv", 5, "", "Observed region did not converge.");
            }
            vlSelfRef.__VobsIterCount = ((IData)(1U) 
                                         + vlSelfRef.__VobsIterCount);
            vlSelfRef.__VobsContinue = 0U;
            vlSelfRef.__VnbaIterCount = 0U;
            vlSelfRef.__VnbaContinue = 1U;
            while (vlSelfRef.__VnbaContinue) {
                if (VL_UNLIKELY((0x64U < vlSelfRef.__VnbaIterCount))) {
#ifdef VL_DEBUG
                    Vtb_e203_nice___024root___dump_triggers__nba(vlSelf);
#endif
                    VL_FATAL_MT("tb_e203_nice.sv", 5, "", "NBA region did not converge.");
                }
                vlSelfRef.__VnbaIterCount = ((IData)(1U) 
                                             + vlSelfRef.__VnbaIterCount);
                vlSelfRef.__VnbaContinue = 0U;
                vlSelfRef.__VactIterCount = 0U;
                vlSelfRef.__VactContinue = 1U;
                while (vlSelfRef.__VactContinue) {
                    if (VL_UNLIKELY((0x64U < vlSelfRef.__VactIterCount))) {
#ifdef VL_DEBUG
                        Vtb_e203_nice___024root___dump_triggers__act(vlSelf);
#endif
                        VL_FATAL_MT("tb_e203_nice.sv", 5, "", "Active region did not converge.");
                    }
                    vlSelfRef.__VactIterCount = ((IData)(1U) 
                                                 + vlSelfRef.__VactIterCount);
                    vlSelfRef.__VactContinue = 0U;
                    if (Vtb_e203_nice___024root___eval_phase__act(vlSelf)) {
                        vlSelfRef.__VactContinue = 1U;
                    }
                }
                if (Vtb_e203_nice___024root___eval_phase__nba(vlSelf)) {
                    vlSelfRef.__VnbaContinue = 1U;
                }
            }
            if (Vtb_e203_nice___024root___eval_phase__obs(vlSelf)) {
                vlSelfRef.__VobsContinue = 1U;
            }
        }
        if (Vtb_e203_nice___024root___eval_phase__react(vlSelf)) {
            __VreactContinue = 1U;
        }
    }
}

#ifdef VL_DEBUG
void Vtb_e203_nice___024root___eval_debug_assertions(Vtb_e203_nice___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vtb_e203_nice__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_e203_nice___024root___eval_debug_assertions\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
}
#endif  // VL_DEBUG
