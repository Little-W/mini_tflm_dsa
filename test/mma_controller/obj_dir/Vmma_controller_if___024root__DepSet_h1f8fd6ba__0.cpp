// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Design implementation internals
// See Vmma_controller_if.h for the primary calling header

#include "Vmma_controller_if__pch.h"
#include "Vmma_controller_if___024root.h"

VL_INLINE_OPT VlCoroutine Vmma_controller_if___024root___eval_initial__TOP__Vtiming__0(Vmma_controller_if___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vmma_controller_if___024root___eval_initial__TOP__Vtiming__0\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    vlSelfRef.tb_mma_controller__DOT__clk = 0U;
    while (1U) {
        co_await vlSelfRef.__VdlySched.delay(0x1388ULL, 
                                             nullptr, 
                                             "tb_mma_controller.sv", 
                                             92);
        vlSelfRef.tb_mma_controller__DOT__clk = (1U 
                                                 & (~ (IData)(vlSelfRef.tb_mma_controller__DOT__clk)));
    }
}

VL_INLINE_OPT VlCoroutine Vmma_controller_if___024root___eval_initial__TOP__Vtiming__2(Vmma_controller_if___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vmma_controller_if___024root___eval_initial__TOP__Vtiming__2\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    co_await vlSelfRef.__VdlySched.delay(0x5f5e100ULL, 
                                         nullptr, "tb_mma_controller.sv", 
                                         187);
    VL_WRITEF_NX("\n\033[31mERROR: Simulation timeout!\033[0m\n",0);
    VL_FINISH_MT("tb_mma_controller.sv", 189, "");
}

void Vmma_controller_if___024root___act_sequent__TOP__0(Vmma_controller_if___024root* vlSelf);

void Vmma_controller_if___024root___eval_act(Vmma_controller_if___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vmma_controller_if___024root___eval_act\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    if ((4ULL & vlSelfRef.__VactTriggered.word(0U))) {
        Vmma_controller_if___024root___act_sequent__TOP__0(vlSelf);
    }
}

void Vmma_controller_if___024root___nba_sequent__TOP__0(Vmma_controller_if___024root* vlSelf);

void Vmma_controller_if___024root___eval_nba(Vmma_controller_if___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vmma_controller_if___024root___eval_nba\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    if ((1ULL & vlSelfRef.__VnbaTriggered.word(0U))) {
        Vmma_controller_if___024root___nba_sequent__TOP__0(vlSelf);
        vlSelfRef.__Vm_traceActivity[1U] = 1U;
    }
    if ((5ULL & vlSelfRef.__VnbaTriggered.word(0U))) {
        Vmma_controller_if___024root___act_sequent__TOP__0(vlSelf);
    }
}

void Vmma_controller_if___024root___timing_resume(Vmma_controller_if___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vmma_controller_if___024root___timing_resume\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    if ((2ULL & vlSelfRef.__VactTriggered.word(0U))) {
        vlSelfRef.__VtrigSched_hdac58424__0.resume(
                                                   "@(posedge tb_mma_controller.clk)");
    }
    if ((8ULL & vlSelfRef.__VactTriggered.word(0U))) {
        vlSelfRef.__VtrigSched_h42ebdd83__0.resume(
                                                   "@([event] tb_mma_controller.ctrl_if.cb)");
    }
    if ((0x10ULL & vlSelfRef.__VactTriggered.word(0U))) {
        vlSelfRef.__VtrigSched_h38e6f19c__0.resume(
                                                   "@([event] tb_mma_controller.comp_if.cb)");
    }
    if ((0x20ULL & vlSelfRef.__VactTriggered.word(0U))) {
        vlSelfRef.__VtrigSched_h742f9b30__0.resume(
                                                   "@([event] tb_mma_controller.ia_if.cb)");
    }
    if ((0x40ULL & vlSelfRef.__VactTriggered.word(0U))) {
        vlSelfRef.__VtrigSched_h9cd046e4__0.resume(
                                                   "@([event] tb_mma_controller.weight_if.cb)");
    }
    if ((0x80ULL & vlSelfRef.__VactTriggered.word(0U))) {
        vlSelfRef.__VtrigSched_h4c63e026__0.resume(
                                                   "@([event] tb_mma_controller.bias_if.cb)");
    }
    if ((0x100ULL & vlSelfRef.__VactTriggered.word(0U))) {
        vlSelfRef.__VtrigSched_h66f97190__0.resume(
                                                   "@([event] tb_mma_controller.quant_if.cb)");
    }
    if ((0x200ULL & vlSelfRef.__VactTriggered.word(0U))) {
        vlSelfRef.__VtrigSched_haadd1735__0.resume(
                                                   "@([event] tb_mma_controller.oa_if.cb)");
    }
    if ((0x400ULL & vlSelfRef.__VactTriggered.word(0U))) {
        vlSelfRef.__VtrigSched_h47b3a967__0.resume(
                                                   "@([changed] (tb_mma_controller.__Vcellout__dut__init_cfg_ia & tb_mma_controller.__Vcellout__dut__init_cfg_weight))");
    }
    if ((0x800ULL & vlSelfRef.__VactTriggered.word(0U))) {
        vlSelfRef.__VtrigSched_hb997b169__0.resume(
                                                   "@([changed] tb_mma_controller.__Vcellout__dut__load_weight_granted)");
    }
    if ((0x1000ULL & vlSelfRef.__VactTriggered.word(0U))) {
        vlSelfRef.__VtrigSched_hf7995922__0.resume(
                                                   "@([changed] tb_mma_controller.__Vcellout__dut__send_weight_trigger)");
    }
    if ((0x2000ULL & vlSelfRef.__VactTriggered.word(0U))) {
        vlSelfRef.__VtrigSched_h41abe5e7__0.resume(
                                                   "@([changed] tb_mma_controller.__Vcellout__dut__load_ia_granted)");
    }
    if ((0x4000ULL & vlSelfRef.__VactTriggered.word(0U))) {
        vlSelfRef.__VtrigSched_h8b2b3151__0.resume(
                                                   "@([changed] tb_mma_controller.__Vcellout__dut__send_ia_trigger)");
    }
    if ((0x8000ULL & vlSelfRef.__VactTriggered.word(0U))) {
        vlSelfRef.__VtrigSched_h90096cfe__0.resume(
                                                   "@([changed] tb_mma_controller.__Vcellout__dut__load_bias_granted)");
    }
    if ((0x10000ULL & vlSelfRef.__VactTriggered.word(0U))) {
        vlSelfRef.__VtrigSched_ha535fff4__0.resume(
                                                   "@([changed] tb_mma_controller.comp_if.tile_calc_over)");
    }
    if ((0x20000ULL & vlSelfRef.__VactTriggered.word(0U))) {
        vlSelfRef.__VtrigSched_h4a02e0d9__0.resume(
                                                   "@([changed] tb_mma_controller.__Vcellout__dut__load_quant_granted)");
    }
    if ((0x40000ULL & vlSelfRef.__VactTriggered.word(0U))) {
        vlSelfRef.__VtrigSched_h28ec1f55__0.resume(
                                                   "@([changed] tb_mma_controller.__Vcellout__dut__write_oa_granted)");
    }
    if ((0x80000ULL & vlSelfRef.__VactTriggered.word(0U))) {
        vlSelfRef.__VtrigSched_h4463a28d__0.resume(
                                                   "@([changed] tb_mma_controller.ia_if.ia_sending_done)");
    }
    if ((0x100000ULL & vlSelfRef.__VactTriggered.word(0U))) {
        vlSelfRef.__VtrigSched_hcbbc710c__0.resume(
                                                   "@([changed] tb_mma_controller.oa_if.oa_calc_over)");
    }
    if ((0x200000ULL & vlSelfRef.__VactTriggered.word(0U))) {
        vlSelfRef.__VtrigSched_h2ab923a2__0.resume(
                                                   "@([changed] (4'h0 == tb_mma_controller.dut.current_state))");
    }
    if ((4ULL & vlSelfRef.__VactTriggered.word(0U))) {
        vlSelfRef.__VdlySched.resume();
    }
}

void Vmma_controller_if___024root___timing_commit(Vmma_controller_if___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vmma_controller_if___024root___timing_commit\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    if ((! (2ULL & vlSelfRef.__VactTriggered.word(0U)))) {
        vlSelfRef.__VtrigSched_hdac58424__0.commit(
                                                   "@(posedge tb_mma_controller.clk)");
    }
    if ((! (8ULL & vlSelfRef.__VactTriggered.word(0U)))) {
        vlSelfRef.__VtrigSched_h42ebdd83__0.commit(
                                                   "@([event] tb_mma_controller.ctrl_if.cb)");
    }
    if ((! (0x10ULL & vlSelfRef.__VactTriggered.word(0U)))) {
        vlSelfRef.__VtrigSched_h38e6f19c__0.commit(
                                                   "@([event] tb_mma_controller.comp_if.cb)");
    }
    if ((! (0x20ULL & vlSelfRef.__VactTriggered.word(0U)))) {
        vlSelfRef.__VtrigSched_h742f9b30__0.commit(
                                                   "@([event] tb_mma_controller.ia_if.cb)");
    }
    if ((! (0x40ULL & vlSelfRef.__VactTriggered.word(0U)))) {
        vlSelfRef.__VtrigSched_h9cd046e4__0.commit(
                                                   "@([event] tb_mma_controller.weight_if.cb)");
    }
    if ((! (0x80ULL & vlSelfRef.__VactTriggered.word(0U)))) {
        vlSelfRef.__VtrigSched_h4c63e026__0.commit(
                                                   "@([event] tb_mma_controller.bias_if.cb)");
    }
    if ((! (0x100ULL & vlSelfRef.__VactTriggered.word(0U)))) {
        vlSelfRef.__VtrigSched_h66f97190__0.commit(
                                                   "@([event] tb_mma_controller.quant_if.cb)");
    }
    if ((! (0x200ULL & vlSelfRef.__VactTriggered.word(0U)))) {
        vlSelfRef.__VtrigSched_haadd1735__0.commit(
                                                   "@([event] tb_mma_controller.oa_if.cb)");
    }
    if ((! (0x400ULL & vlSelfRef.__VactTriggered.word(0U)))) {
        vlSelfRef.__VtrigSched_h47b3a967__0.commit(
                                                   "@([changed] (tb_mma_controller.__Vcellout__dut__init_cfg_ia & tb_mma_controller.__Vcellout__dut__init_cfg_weight))");
    }
    if ((! (0x800ULL & vlSelfRef.__VactTriggered.word(0U)))) {
        vlSelfRef.__VtrigSched_hb997b169__0.commit(
                                                   "@([changed] tb_mma_controller.__Vcellout__dut__load_weight_granted)");
    }
    if ((! (0x1000ULL & vlSelfRef.__VactTriggered.word(0U)))) {
        vlSelfRef.__VtrigSched_hf7995922__0.commit(
                                                   "@([changed] tb_mma_controller.__Vcellout__dut__send_weight_trigger)");
    }
    if ((! (0x2000ULL & vlSelfRef.__VactTriggered.word(0U)))) {
        vlSelfRef.__VtrigSched_h41abe5e7__0.commit(
                                                   "@([changed] tb_mma_controller.__Vcellout__dut__load_ia_granted)");
    }
    if ((! (0x4000ULL & vlSelfRef.__VactTriggered.word(0U)))) {
        vlSelfRef.__VtrigSched_h8b2b3151__0.commit(
                                                   "@([changed] tb_mma_controller.__Vcellout__dut__send_ia_trigger)");
    }
    if ((! (0x8000ULL & vlSelfRef.__VactTriggered.word(0U)))) {
        vlSelfRef.__VtrigSched_h90096cfe__0.commit(
                                                   "@([changed] tb_mma_controller.__Vcellout__dut__load_bias_granted)");
    }
    if ((! (0x10000ULL & vlSelfRef.__VactTriggered.word(0U)))) {
        vlSelfRef.__VtrigSched_ha535fff4__0.commit(
                                                   "@([changed] tb_mma_controller.comp_if.tile_calc_over)");
    }
    if ((! (0x20000ULL & vlSelfRef.__VactTriggered.word(0U)))) {
        vlSelfRef.__VtrigSched_h4a02e0d9__0.commit(
                                                   "@([changed] tb_mma_controller.__Vcellout__dut__load_quant_granted)");
    }
    if ((! (0x40000ULL & vlSelfRef.__VactTriggered.word(0U)))) {
        vlSelfRef.__VtrigSched_h28ec1f55__0.commit(
                                                   "@([changed] tb_mma_controller.__Vcellout__dut__write_oa_granted)");
    }
    if ((! (0x80000ULL & vlSelfRef.__VactTriggered.word(0U)))) {
        vlSelfRef.__VtrigSched_h4463a28d__0.commit(
                                                   "@([changed] tb_mma_controller.ia_if.ia_sending_done)");
    }
    if ((! (0x100000ULL & vlSelfRef.__VactTriggered.word(0U)))) {
        vlSelfRef.__VtrigSched_hcbbc710c__0.commit(
                                                   "@([changed] tb_mma_controller.oa_if.oa_calc_over)");
    }
    if ((! (0x200000ULL & vlSelfRef.__VactTriggered.word(0U)))) {
        vlSelfRef.__VtrigSched_h2ab923a2__0.commit(
                                                   "@([changed] (4'h0 == tb_mma_controller.dut.current_state))");
    }
}

void Vmma_controller_if___024root___eval_triggers__act(Vmma_controller_if___024root* vlSelf);

bool Vmma_controller_if___024root___eval_phase__act(Vmma_controller_if___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vmma_controller_if___024root___eval_phase__act\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Init
    VlTriggerVec<22> __VpreTriggered;
    CData/*0:0*/ __VactExecute;
    // Body
    Vmma_controller_if___024root___eval_triggers__act(vlSelf);
    Vmma_controller_if___024root___timing_commit(vlSelf);
    __VactExecute = vlSelfRef.__VactTriggered.any();
    if (__VactExecute) {
        __VpreTriggered.andNot(vlSelfRef.__VactTriggered, vlSelfRef.__VnbaTriggered);
        vlSelfRef.__VnbaTriggered.thisOr(vlSelfRef.__VactTriggered);
        Vmma_controller_if___024root___timing_resume(vlSelf);
        Vmma_controller_if___024root___eval_act(vlSelf);
    }
    return (__VactExecute);
}

bool Vmma_controller_if___024root___eval_phase__nba(Vmma_controller_if___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vmma_controller_if___024root___eval_phase__nba\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Init
    CData/*0:0*/ __VnbaExecute;
    // Body
    __VnbaExecute = vlSelfRef.__VnbaTriggered.any();
    if (__VnbaExecute) {
        vlSelfRef.__VobsTriggered.thisOr(vlSelfRef.__VnbaTriggered);
        Vmma_controller_if___024root___eval_nba(vlSelf);
        vlSelfRef.__VnbaTriggered.clear();
    }
    return (__VnbaExecute);
}

void Vmma_controller_if___024root___eval_obs(Vmma_controller_if___024root* vlSelf);

bool Vmma_controller_if___024root___eval_phase__obs(Vmma_controller_if___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vmma_controller_if___024root___eval_phase__obs\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Init
    CData/*0:0*/ __VobsExecute;
    // Body
    __VobsExecute = vlSelfRef.__VobsTriggered.any();
    if (__VobsExecute) {
        Vmma_controller_if___024root___eval_obs(vlSelf);
        vlSelfRef.__VobsTriggered.clear();
    }
    return (__VobsExecute);
}

#ifdef VL_DEBUG
VL_ATTR_COLD void Vmma_controller_if___024root___dump_triggers__obs(Vmma_controller_if___024root* vlSelf);
#endif  // VL_DEBUG
#ifdef VL_DEBUG
VL_ATTR_COLD void Vmma_controller_if___024root___dump_triggers__nba(Vmma_controller_if___024root* vlSelf);
#endif  // VL_DEBUG
#ifdef VL_DEBUG
VL_ATTR_COLD void Vmma_controller_if___024root___dump_triggers__act(Vmma_controller_if___024root* vlSelf);
#endif  // VL_DEBUG

void Vmma_controller_if___024root___eval(Vmma_controller_if___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vmma_controller_if___024root___eval\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Init
    IData/*31:0*/ __VobsIterCount;
    CData/*0:0*/ __VobsContinue;
    // Body
    __VobsIterCount = 0U;
    __VobsContinue = 1U;
    while (__VobsContinue) {
        if (VL_UNLIKELY((0x64U < __VobsIterCount))) {
#ifdef VL_DEBUG
            Vmma_controller_if___024root___dump_triggers__obs(vlSelf);
#endif
            VL_FATAL_MT("tb_mma_controller.sv", 3, "", "Observed region did not converge.");
        }
        __VobsIterCount = ((IData)(1U) + __VobsIterCount);
        __VobsContinue = 0U;
        vlSelfRef.__VnbaIterCount = 0U;
        vlSelfRef.__VnbaContinue = 1U;
        while (vlSelfRef.__VnbaContinue) {
            if (VL_UNLIKELY((0x64U < vlSelfRef.__VnbaIterCount))) {
#ifdef VL_DEBUG
                Vmma_controller_if___024root___dump_triggers__nba(vlSelf);
#endif
                VL_FATAL_MT("tb_mma_controller.sv", 3, "", "NBA region did not converge.");
            }
            vlSelfRef.__VnbaIterCount = ((IData)(1U) 
                                         + vlSelfRef.__VnbaIterCount);
            vlSelfRef.__VnbaContinue = 0U;
            vlSelfRef.__VactIterCount = 0U;
            vlSelfRef.__VactContinue = 1U;
            while (vlSelfRef.__VactContinue) {
                if (VL_UNLIKELY((0x64U < vlSelfRef.__VactIterCount))) {
#ifdef VL_DEBUG
                    Vmma_controller_if___024root___dump_triggers__act(vlSelf);
#endif
                    VL_FATAL_MT("tb_mma_controller.sv", 3, "", "Active region did not converge.");
                }
                vlSelfRef.__VactIterCount = ((IData)(1U) 
                                             + vlSelfRef.__VactIterCount);
                vlSelfRef.__VactContinue = 0U;
                if (Vmma_controller_if___024root___eval_phase__act(vlSelf)) {
                    vlSelfRef.__VactContinue = 1U;
                }
            }
            if (Vmma_controller_if___024root___eval_phase__nba(vlSelf)) {
                vlSelfRef.__VnbaContinue = 1U;
            }
        }
        if (Vmma_controller_if___024root___eval_phase__obs(vlSelf)) {
            __VobsContinue = 1U;
        }
    }
}

#ifdef VL_DEBUG
void Vmma_controller_if___024root___eval_debug_assertions(Vmma_controller_if___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vmma_controller_if___024root___eval_debug_assertions\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
}
#endif  // VL_DEBUG
