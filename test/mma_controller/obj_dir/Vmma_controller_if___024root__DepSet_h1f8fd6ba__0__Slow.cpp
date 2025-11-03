// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Design implementation internals
// See Vmma_controller_if.h for the primary calling header

#include "Vmma_controller_if__pch.h"
#include "Vmma_controller_if___024root.h"

VL_ATTR_COLD void Vmma_controller_if___024root___eval_final(Vmma_controller_if___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vmma_controller_if___024root___eval_final\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
}

#ifdef VL_DEBUG
VL_ATTR_COLD void Vmma_controller_if___024root___dump_triggers__stl(Vmma_controller_if___024root* vlSelf);
#endif  // VL_DEBUG
VL_ATTR_COLD bool Vmma_controller_if___024root___eval_phase__stl(Vmma_controller_if___024root* vlSelf);

VL_ATTR_COLD void Vmma_controller_if___024root___eval_settle(Vmma_controller_if___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vmma_controller_if___024root___eval_settle\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Init
    IData/*31:0*/ __VstlIterCount;
    CData/*0:0*/ __VstlContinue;
    // Body
    __VstlIterCount = 0U;
    vlSelfRef.__VstlFirstIteration = 1U;
    __VstlContinue = 1U;
    while (__VstlContinue) {
        if (VL_UNLIKELY((0x64U < __VstlIterCount))) {
#ifdef VL_DEBUG
            Vmma_controller_if___024root___dump_triggers__stl(vlSelf);
#endif
            VL_FATAL_MT("tb_mma_controller.sv", 3, "", "Settle region did not converge.");
        }
        __VstlIterCount = ((IData)(1U) + __VstlIterCount);
        __VstlContinue = 0U;
        if (Vmma_controller_if___024root___eval_phase__stl(vlSelf)) {
            __VstlContinue = 1U;
        }
        vlSelfRef.__VstlFirstIteration = 0U;
    }
}

#ifdef VL_DEBUG
VL_ATTR_COLD void Vmma_controller_if___024root___dump_triggers__stl(Vmma_controller_if___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vmma_controller_if___024root___dump_triggers__stl\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    if ((1U & (~ vlSelfRef.__VstlTriggered.any()))) {
        VL_DBG_MSGF("         No triggers active\n");
    }
    if ((1ULL & vlSelfRef.__VstlTriggered.word(0U))) {
        VL_DBG_MSGF("         'stl' region trigger index 0 is active: Internal 'stl' trigger - first iteration\n");
    }
}
#endif  // VL_DEBUG

void Vmma_controller_if___024root___act_sequent__TOP__0(Vmma_controller_if___024root* vlSelf);

VL_ATTR_COLD void Vmma_controller_if___024root___eval_stl(Vmma_controller_if___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vmma_controller_if___024root___eval_stl\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    if ((1ULL & vlSelfRef.__VstlTriggered.word(0U))) {
        Vmma_controller_if___024root___act_sequent__TOP__0(vlSelf);
    }
}

VL_ATTR_COLD void Vmma_controller_if___024root___eval_triggers__stl(Vmma_controller_if___024root* vlSelf);

VL_ATTR_COLD bool Vmma_controller_if___024root___eval_phase__stl(Vmma_controller_if___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vmma_controller_if___024root___eval_phase__stl\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Init
    CData/*0:0*/ __VstlExecute;
    // Body
    Vmma_controller_if___024root___eval_triggers__stl(vlSelf);
    __VstlExecute = vlSelfRef.__VstlTriggered.any();
    if (__VstlExecute) {
        Vmma_controller_if___024root___eval_stl(vlSelf);
    }
    return (__VstlExecute);
}

#ifdef VL_DEBUG
VL_ATTR_COLD void Vmma_controller_if___024root___dump_triggers__act(Vmma_controller_if___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vmma_controller_if___024root___dump_triggers__act\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    if ((1U & (~ vlSelfRef.__VactTriggered.any()))) {
        VL_DBG_MSGF("         No triggers active\n");
    }
    if ((1ULL & vlSelfRef.__VactTriggered.word(0U))) {
        VL_DBG_MSGF("         'act' region trigger index 0 is active: @(posedge tb_mma_controller.clk or negedge tb_mma_controller.rst_n)\n");
    }
    if ((2ULL & vlSelfRef.__VactTriggered.word(0U))) {
        VL_DBG_MSGF("         'act' region trigger index 1 is active: @(posedge tb_mma_controller.clk)\n");
    }
    if ((4ULL & vlSelfRef.__VactTriggered.word(0U))) {
        VL_DBG_MSGF("         'act' region trigger index 2 is active: @([true] __VdlySched.awaitingCurrentTime())\n");
    }
    if ((8ULL & vlSelfRef.__VactTriggered.word(0U))) {
        VL_DBG_MSGF("         'act' region trigger index 3 is active: @([event] tb_mma_controller.ctrl_if.cb)\n");
    }
    if ((0x10ULL & vlSelfRef.__VactTriggered.word(0U))) {
        VL_DBG_MSGF("         'act' region trigger index 4 is active: @([event] tb_mma_controller.comp_if.cb)\n");
    }
    if ((0x20ULL & vlSelfRef.__VactTriggered.word(0U))) {
        VL_DBG_MSGF("         'act' region trigger index 5 is active: @([event] tb_mma_controller.ia_if.cb)\n");
    }
    if ((0x40ULL & vlSelfRef.__VactTriggered.word(0U))) {
        VL_DBG_MSGF("         'act' region trigger index 6 is active: @([event] tb_mma_controller.weight_if.cb)\n");
    }
    if ((0x80ULL & vlSelfRef.__VactTriggered.word(0U))) {
        VL_DBG_MSGF("         'act' region trigger index 7 is active: @([event] tb_mma_controller.bias_if.cb)\n");
    }
    if ((0x100ULL & vlSelfRef.__VactTriggered.word(0U))) {
        VL_DBG_MSGF("         'act' region trigger index 8 is active: @([event] tb_mma_controller.quant_if.cb)\n");
    }
    if ((0x200ULL & vlSelfRef.__VactTriggered.word(0U))) {
        VL_DBG_MSGF("         'act' region trigger index 9 is active: @([event] tb_mma_controller.oa_if.cb)\n");
    }
    if ((0x400ULL & vlSelfRef.__VactTriggered.word(0U))) {
        VL_DBG_MSGF("         'act' region trigger index 10 is active: @([changed] (tb_mma_controller.__Vcellout__dut__init_cfg_ia & tb_mma_controller.__Vcellout__dut__init_cfg_weight))\n");
    }
    if ((0x800ULL & vlSelfRef.__VactTriggered.word(0U))) {
        VL_DBG_MSGF("         'act' region trigger index 11 is active: @([changed] tb_mma_controller.__Vcellout__dut__load_weight_granted)\n");
    }
    if ((0x1000ULL & vlSelfRef.__VactTriggered.word(0U))) {
        VL_DBG_MSGF("         'act' region trigger index 12 is active: @([changed] tb_mma_controller.__Vcellout__dut__send_weight_trigger)\n");
    }
    if ((0x2000ULL & vlSelfRef.__VactTriggered.word(0U))) {
        VL_DBG_MSGF("         'act' region trigger index 13 is active: @([changed] tb_mma_controller.__Vcellout__dut__load_ia_granted)\n");
    }
    if ((0x4000ULL & vlSelfRef.__VactTriggered.word(0U))) {
        VL_DBG_MSGF("         'act' region trigger index 14 is active: @([changed] tb_mma_controller.__Vcellout__dut__send_ia_trigger)\n");
    }
    if ((0x8000ULL & vlSelfRef.__VactTriggered.word(0U))) {
        VL_DBG_MSGF("         'act' region trigger index 15 is active: @([changed] tb_mma_controller.__Vcellout__dut__load_bias_granted)\n");
    }
    if ((0x10000ULL & vlSelfRef.__VactTriggered.word(0U))) {
        VL_DBG_MSGF("         'act' region trigger index 16 is active: @([changed] tb_mma_controller.comp_if.tile_calc_over)\n");
    }
    if ((0x20000ULL & vlSelfRef.__VactTriggered.word(0U))) {
        VL_DBG_MSGF("         'act' region trigger index 17 is active: @([changed] tb_mma_controller.__Vcellout__dut__load_quant_granted)\n");
    }
    if ((0x40000ULL & vlSelfRef.__VactTriggered.word(0U))) {
        VL_DBG_MSGF("         'act' region trigger index 18 is active: @([changed] tb_mma_controller.__Vcellout__dut__write_oa_granted)\n");
    }
    if ((0x80000ULL & vlSelfRef.__VactTriggered.word(0U))) {
        VL_DBG_MSGF("         'act' region trigger index 19 is active: @([changed] tb_mma_controller.ia_if.ia_sending_done)\n");
    }
    if ((0x100000ULL & vlSelfRef.__VactTriggered.word(0U))) {
        VL_DBG_MSGF("         'act' region trigger index 20 is active: @([changed] tb_mma_controller.oa_if.oa_calc_over)\n");
    }
    if ((0x200000ULL & vlSelfRef.__VactTriggered.word(0U))) {
        VL_DBG_MSGF("         'act' region trigger index 21 is active: @([changed] (4'h0 == tb_mma_controller.dut.current_state))\n");
    }
}
#endif  // VL_DEBUG

#ifdef VL_DEBUG
VL_ATTR_COLD void Vmma_controller_if___024root___dump_triggers__obs(Vmma_controller_if___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vmma_controller_if___024root___dump_triggers__obs\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    if ((1U & (~ vlSelfRef.__VobsTriggered.any()))) {
        VL_DBG_MSGF("         No triggers active\n");
    }
    if ((1ULL & vlSelfRef.__VobsTriggered.word(0U))) {
        VL_DBG_MSGF("         'obs' region trigger index 0 is active: @(posedge tb_mma_controller.clk or negedge tb_mma_controller.rst_n)\n");
    }
    if ((2ULL & vlSelfRef.__VobsTriggered.word(0U))) {
        VL_DBG_MSGF("         'obs' region trigger index 1 is active: @(posedge tb_mma_controller.clk)\n");
    }
    if ((4ULL & vlSelfRef.__VobsTriggered.word(0U))) {
        VL_DBG_MSGF("         'obs' region trigger index 2 is active: @([true] __VdlySched.awaitingCurrentTime())\n");
    }
    if ((8ULL & vlSelfRef.__VobsTriggered.word(0U))) {
        VL_DBG_MSGF("         'obs' region trigger index 3 is active: @([event] tb_mma_controller.ctrl_if.cb)\n");
    }
    if ((0x10ULL & vlSelfRef.__VobsTriggered.word(0U))) {
        VL_DBG_MSGF("         'obs' region trigger index 4 is active: @([event] tb_mma_controller.comp_if.cb)\n");
    }
    if ((0x20ULL & vlSelfRef.__VobsTriggered.word(0U))) {
        VL_DBG_MSGF("         'obs' region trigger index 5 is active: @([event] tb_mma_controller.ia_if.cb)\n");
    }
    if ((0x40ULL & vlSelfRef.__VobsTriggered.word(0U))) {
        VL_DBG_MSGF("         'obs' region trigger index 6 is active: @([event] tb_mma_controller.weight_if.cb)\n");
    }
    if ((0x80ULL & vlSelfRef.__VobsTriggered.word(0U))) {
        VL_DBG_MSGF("         'obs' region trigger index 7 is active: @([event] tb_mma_controller.bias_if.cb)\n");
    }
    if ((0x100ULL & vlSelfRef.__VobsTriggered.word(0U))) {
        VL_DBG_MSGF("         'obs' region trigger index 8 is active: @([event] tb_mma_controller.quant_if.cb)\n");
    }
    if ((0x200ULL & vlSelfRef.__VobsTriggered.word(0U))) {
        VL_DBG_MSGF("         'obs' region trigger index 9 is active: @([event] tb_mma_controller.oa_if.cb)\n");
    }
    if ((0x400ULL & vlSelfRef.__VobsTriggered.word(0U))) {
        VL_DBG_MSGF("         'obs' region trigger index 10 is active: @([changed] (tb_mma_controller.__Vcellout__dut__init_cfg_ia & tb_mma_controller.__Vcellout__dut__init_cfg_weight))\n");
    }
    if ((0x800ULL & vlSelfRef.__VobsTriggered.word(0U))) {
        VL_DBG_MSGF("         'obs' region trigger index 11 is active: @([changed] tb_mma_controller.__Vcellout__dut__load_weight_granted)\n");
    }
    if ((0x1000ULL & vlSelfRef.__VobsTriggered.word(0U))) {
        VL_DBG_MSGF("         'obs' region trigger index 12 is active: @([changed] tb_mma_controller.__Vcellout__dut__send_weight_trigger)\n");
    }
    if ((0x2000ULL & vlSelfRef.__VobsTriggered.word(0U))) {
        VL_DBG_MSGF("         'obs' region trigger index 13 is active: @([changed] tb_mma_controller.__Vcellout__dut__load_ia_granted)\n");
    }
    if ((0x4000ULL & vlSelfRef.__VobsTriggered.word(0U))) {
        VL_DBG_MSGF("         'obs' region trigger index 14 is active: @([changed] tb_mma_controller.__Vcellout__dut__send_ia_trigger)\n");
    }
    if ((0x8000ULL & vlSelfRef.__VobsTriggered.word(0U))) {
        VL_DBG_MSGF("         'obs' region trigger index 15 is active: @([changed] tb_mma_controller.__Vcellout__dut__load_bias_granted)\n");
    }
    if ((0x10000ULL & vlSelfRef.__VobsTriggered.word(0U))) {
        VL_DBG_MSGF("         'obs' region trigger index 16 is active: @([changed] tb_mma_controller.comp_if.tile_calc_over)\n");
    }
    if ((0x20000ULL & vlSelfRef.__VobsTriggered.word(0U))) {
        VL_DBG_MSGF("         'obs' region trigger index 17 is active: @([changed] tb_mma_controller.__Vcellout__dut__load_quant_granted)\n");
    }
    if ((0x40000ULL & vlSelfRef.__VobsTriggered.word(0U))) {
        VL_DBG_MSGF("         'obs' region trigger index 18 is active: @([changed] tb_mma_controller.__Vcellout__dut__write_oa_granted)\n");
    }
    if ((0x80000ULL & vlSelfRef.__VobsTriggered.word(0U))) {
        VL_DBG_MSGF("         'obs' region trigger index 19 is active: @([changed] tb_mma_controller.ia_if.ia_sending_done)\n");
    }
    if ((0x100000ULL & vlSelfRef.__VobsTriggered.word(0U))) {
        VL_DBG_MSGF("         'obs' region trigger index 20 is active: @([changed] tb_mma_controller.oa_if.oa_calc_over)\n");
    }
    if ((0x200000ULL & vlSelfRef.__VobsTriggered.word(0U))) {
        VL_DBG_MSGF("         'obs' region trigger index 21 is active: @([changed] (4'h0 == tb_mma_controller.dut.current_state))\n");
    }
}
#endif  // VL_DEBUG

#ifdef VL_DEBUG
VL_ATTR_COLD void Vmma_controller_if___024root___dump_triggers__nba(Vmma_controller_if___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vmma_controller_if___024root___dump_triggers__nba\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    if ((1U & (~ vlSelfRef.__VnbaTriggered.any()))) {
        VL_DBG_MSGF("         No triggers active\n");
    }
    if ((1ULL & vlSelfRef.__VnbaTriggered.word(0U))) {
        VL_DBG_MSGF("         'nba' region trigger index 0 is active: @(posedge tb_mma_controller.clk or negedge tb_mma_controller.rst_n)\n");
    }
    if ((2ULL & vlSelfRef.__VnbaTriggered.word(0U))) {
        VL_DBG_MSGF("         'nba' region trigger index 1 is active: @(posedge tb_mma_controller.clk)\n");
    }
    if ((4ULL & vlSelfRef.__VnbaTriggered.word(0U))) {
        VL_DBG_MSGF("         'nba' region trigger index 2 is active: @([true] __VdlySched.awaitingCurrentTime())\n");
    }
    if ((8ULL & vlSelfRef.__VnbaTriggered.word(0U))) {
        VL_DBG_MSGF("         'nba' region trigger index 3 is active: @([event] tb_mma_controller.ctrl_if.cb)\n");
    }
    if ((0x10ULL & vlSelfRef.__VnbaTriggered.word(0U))) {
        VL_DBG_MSGF("         'nba' region trigger index 4 is active: @([event] tb_mma_controller.comp_if.cb)\n");
    }
    if ((0x20ULL & vlSelfRef.__VnbaTriggered.word(0U))) {
        VL_DBG_MSGF("         'nba' region trigger index 5 is active: @([event] tb_mma_controller.ia_if.cb)\n");
    }
    if ((0x40ULL & vlSelfRef.__VnbaTriggered.word(0U))) {
        VL_DBG_MSGF("         'nba' region trigger index 6 is active: @([event] tb_mma_controller.weight_if.cb)\n");
    }
    if ((0x80ULL & vlSelfRef.__VnbaTriggered.word(0U))) {
        VL_DBG_MSGF("         'nba' region trigger index 7 is active: @([event] tb_mma_controller.bias_if.cb)\n");
    }
    if ((0x100ULL & vlSelfRef.__VnbaTriggered.word(0U))) {
        VL_DBG_MSGF("         'nba' region trigger index 8 is active: @([event] tb_mma_controller.quant_if.cb)\n");
    }
    if ((0x200ULL & vlSelfRef.__VnbaTriggered.word(0U))) {
        VL_DBG_MSGF("         'nba' region trigger index 9 is active: @([event] tb_mma_controller.oa_if.cb)\n");
    }
    if ((0x400ULL & vlSelfRef.__VnbaTriggered.word(0U))) {
        VL_DBG_MSGF("         'nba' region trigger index 10 is active: @([changed] (tb_mma_controller.__Vcellout__dut__init_cfg_ia & tb_mma_controller.__Vcellout__dut__init_cfg_weight))\n");
    }
    if ((0x800ULL & vlSelfRef.__VnbaTriggered.word(0U))) {
        VL_DBG_MSGF("         'nba' region trigger index 11 is active: @([changed] tb_mma_controller.__Vcellout__dut__load_weight_granted)\n");
    }
    if ((0x1000ULL & vlSelfRef.__VnbaTriggered.word(0U))) {
        VL_DBG_MSGF("         'nba' region trigger index 12 is active: @([changed] tb_mma_controller.__Vcellout__dut__send_weight_trigger)\n");
    }
    if ((0x2000ULL & vlSelfRef.__VnbaTriggered.word(0U))) {
        VL_DBG_MSGF("         'nba' region trigger index 13 is active: @([changed] tb_mma_controller.__Vcellout__dut__load_ia_granted)\n");
    }
    if ((0x4000ULL & vlSelfRef.__VnbaTriggered.word(0U))) {
        VL_DBG_MSGF("         'nba' region trigger index 14 is active: @([changed] tb_mma_controller.__Vcellout__dut__send_ia_trigger)\n");
    }
    if ((0x8000ULL & vlSelfRef.__VnbaTriggered.word(0U))) {
        VL_DBG_MSGF("         'nba' region trigger index 15 is active: @([changed] tb_mma_controller.__Vcellout__dut__load_bias_granted)\n");
    }
    if ((0x10000ULL & vlSelfRef.__VnbaTriggered.word(0U))) {
        VL_DBG_MSGF("         'nba' region trigger index 16 is active: @([changed] tb_mma_controller.comp_if.tile_calc_over)\n");
    }
    if ((0x20000ULL & vlSelfRef.__VnbaTriggered.word(0U))) {
        VL_DBG_MSGF("         'nba' region trigger index 17 is active: @([changed] tb_mma_controller.__Vcellout__dut__load_quant_granted)\n");
    }
    if ((0x40000ULL & vlSelfRef.__VnbaTriggered.word(0U))) {
        VL_DBG_MSGF("         'nba' region trigger index 18 is active: @([changed] tb_mma_controller.__Vcellout__dut__write_oa_granted)\n");
    }
    if ((0x80000ULL & vlSelfRef.__VnbaTriggered.word(0U))) {
        VL_DBG_MSGF("         'nba' region trigger index 19 is active: @([changed] tb_mma_controller.ia_if.ia_sending_done)\n");
    }
    if ((0x100000ULL & vlSelfRef.__VnbaTriggered.word(0U))) {
        VL_DBG_MSGF("         'nba' region trigger index 20 is active: @([changed] tb_mma_controller.oa_if.oa_calc_over)\n");
    }
    if ((0x200000ULL & vlSelfRef.__VnbaTriggered.word(0U))) {
        VL_DBG_MSGF("         'nba' region trigger index 21 is active: @([changed] (4'h0 == tb_mma_controller.dut.current_state))\n");
    }
}
#endif  // VL_DEBUG

VL_ATTR_COLD void Vmma_controller_if___024root___ctor_var_reset(Vmma_controller_if___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vmma_controller_if___024root___ctor_var_reset\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    vlSelf->tb_mma_controller__DOT__clk = VL_RAND_RESET_I(1);
    vlSelf->tb_mma_controller__DOT__rst_n = VL_RAND_RESET_I(1);
    vlSelf->tb_mma_controller__DOT____Vcellout__dut__write_oa_granted = VL_RAND_RESET_I(1);
    vlSelf->tb_mma_controller__DOT____Vcellout__dut__load_quant_granted = VL_RAND_RESET_I(1);
    vlSelf->tb_mma_controller__DOT____Vcellout__dut__load_bias_granted = VL_RAND_RESET_I(1);
    vlSelf->tb_mma_controller__DOT____Vcellout__dut__send_weight_trigger = VL_RAND_RESET_I(1);
    vlSelf->tb_mma_controller__DOT____Vcellout__dut__load_weight_granted = VL_RAND_RESET_I(1);
    vlSelf->tb_mma_controller__DOT____Vcellout__dut__send_ia_trigger = VL_RAND_RESET_I(1);
    vlSelf->tb_mma_controller__DOT____Vcellout__dut__load_ia_granted = VL_RAND_RESET_I(1);
    vlSelf->tb_mma_controller__DOT____Vcellout__dut__tile_count = VL_RAND_RESET_I(32);
    vlSelf->tb_mma_controller__DOT____Vcellout__dut__use_16bits = VL_RAND_RESET_I(1);
    vlSelf->tb_mma_controller__DOT____Vcellout__dut__init_cfg_oa = VL_RAND_RESET_I(1);
    vlSelf->tb_mma_controller__DOT____Vcellout__dut__init_cfg_requant = VL_RAND_RESET_I(1);
    vlSelf->tb_mma_controller__DOT____Vcellout__dut__init_cfg_bias = VL_RAND_RESET_I(1);
    vlSelf->tb_mma_controller__DOT____Vcellout__dut__init_cfg_weight = VL_RAND_RESET_I(1);
    vlSelf->tb_mma_controller__DOT____Vcellout__dut__init_cfg_ia = VL_RAND_RESET_I(1);
    vlSelf->tb_mma_controller__DOT____Vcellout__dut__icb_sel = VL_RAND_RESET_I(3);
    vlSelf->tb_mma_controller__DOT__dut__DOT__lhs_base = VL_RAND_RESET_I(32);
    vlSelf->tb_mma_controller__DOT__dut__DOT__rhs_base = VL_RAND_RESET_I(32);
    vlSelf->tb_mma_controller__DOT__dut__DOT__dst_base = VL_RAND_RESET_I(32);
    vlSelf->tb_mma_controller__DOT__dut__DOT__bias_base = VL_RAND_RESET_I(32);
    vlSelf->tb_mma_controller__DOT__dut__DOT__q_mult_pt = VL_RAND_RESET_I(32);
    vlSelf->tb_mma_controller__DOT__dut__DOT__q_shift_pt = VL_RAND_RESET_I(32);
    vlSelf->tb_mma_controller__DOT__dut__DOT__use_per_channel = VL_RAND_RESET_I(1);
    vlSelf->tb_mma_controller__DOT__dut__DOT__k = VL_RAND_RESET_I(32);
    vlSelf->tb_mma_controller__DOT__dut__DOT__n = VL_RAND_RESET_I(32);
    vlSelf->tb_mma_controller__DOT__dut__DOT__m = VL_RAND_RESET_I(32);
    vlSelf->tb_mma_controller__DOT__dut__DOT__lhs_row_stride_b = VL_RAND_RESET_I(32);
    vlSelf->tb_mma_controller__DOT__dut__DOT__dst_row_stride_b = VL_RAND_RESET_I(32);
    vlSelf->tb_mma_controller__DOT__dut__DOT__rhs_row_stride_b = VL_RAND_RESET_I(32);
    vlSelf->tb_mma_controller__DOT__dut__DOT__wb_ready = VL_RAND_RESET_I(1);
    vlSelf->tb_mma_controller__DOT__dut__DOT__err_code = VL_RAND_RESET_I(2);
    vlSelf->tb_mma_controller__DOT__dut__DOT__current_state = VL_RAND_RESET_I(4);
    vlSelf->tb_mma_controller__DOT__dut__DOT__next_state = VL_RAND_RESET_I(4);
    vlSelf->tb_mma_controller__DOT__dut__DOT__cfg_16bits_ia_reg = VL_RAND_RESET_I(1);
    vlSelf->tb_mma_controller__DOT__dut__DOT__config_error = VL_RAND_RESET_I(1);
    vlSelf->tb_mma_controller__DOT__dut__DOT__error_type = VL_RAND_RESET_I(2);
    vlSelf->tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__current_master = VL_RAND_RESET_I(3);
    vlSelf->tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__bus_busy = VL_RAND_RESET_I(1);
    for (int __Vi0 = 0; __Vi0 < 4; ++__Vi0) {
        vlSelf->tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__priority_queue[__Vi0] = VL_RAND_RESET_I(3);
    }
    for (int __Vi0 = 0; __Vi0 < 4; ++__Vi0) {
        vlSelf->tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__next_priority_queue[__Vi0] = VL_RAND_RESET_I(3);
    }
    vlSelf->tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__bus_idle = VL_RAND_RESET_I(1);
    vlSelf->tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__current_done = VL_RAND_RESET_I(1);
    vlSelf->tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__unnamedblk1__DOT__next_device = VL_RAND_RESET_I(3);
    vlSelf->__Vfunc_tb_mma_controller__DOT__dut__DOT__check_config_valid__10__Vfuncout = VL_RAND_RESET_I(1);
    vlSelf->__Vfunc_tb_mma_controller__DOT__dut__DOT__check_config_valid__10__ptr_error = VL_RAND_RESET_I(1);
    vlSelf->__Vfunc_tb_mma_controller__DOT__dut__DOT__check_config_valid__10__dim_error = VL_RAND_RESET_I(1);
    vlSelf->__Vfunc_tb_mma_controller__DOT__dut__DOT__check_config_valid__10__stride_error = VL_RAND_RESET_I(1);
    vlSelf->__Vfunc_tb_mma_controller__DOT__dut__DOT__check_config_valid__10__quant_error = VL_RAND_RESET_I(1);
    vlSelf->__Vtrigprevexpr___TOP__tb_mma_controller__DOT__clk__0 = VL_RAND_RESET_I(1);
    vlSelf->__Vtrigprevexpr___TOP__tb_mma_controller__DOT__rst_n__0 = VL_RAND_RESET_I(1);
    vlSelf->__Vtrigprevexpr_he004758a__0 = VL_RAND_RESET_I(1);
    vlSelf->__Vtrigprevexpr___TOP__tb_mma_controller__DOT____Vcellout__dut__load_weight_granted__0 = VL_RAND_RESET_I(1);
    vlSelf->__Vtrigprevexpr___TOP__tb_mma_controller__DOT____Vcellout__dut__send_weight_trigger__0 = VL_RAND_RESET_I(1);
    vlSelf->__Vtrigprevexpr___TOP__tb_mma_controller__DOT____Vcellout__dut__load_ia_granted__0 = VL_RAND_RESET_I(1);
    vlSelf->__Vtrigprevexpr___TOP__tb_mma_controller__DOT____Vcellout__dut__send_ia_trigger__0 = VL_RAND_RESET_I(1);
    vlSelf->__Vtrigprevexpr___TOP__tb_mma_controller__DOT____Vcellout__dut__load_bias_granted__0 = VL_RAND_RESET_I(1);
    vlSelf->__Vtrigprevexpr___TOP__tb_mma_controller__DOT__comp_if__tile_calc_over__0 = VL_RAND_RESET_I(1);
    vlSelf->__Vtrigprevexpr___TOP__tb_mma_controller__DOT____Vcellout__dut__load_quant_granted__0 = VL_RAND_RESET_I(1);
    vlSelf->__Vtrigprevexpr___TOP__tb_mma_controller__DOT____Vcellout__dut__write_oa_granted__0 = VL_RAND_RESET_I(1);
    vlSelf->__Vtrigprevexpr___TOP__tb_mma_controller__DOT__ia_if__ia_sending_done__0 = VL_RAND_RESET_I(1);
    vlSelf->__Vtrigprevexpr___TOP__tb_mma_controller__DOT__oa_if__oa_calc_over__0 = VL_RAND_RESET_I(1);
    vlSelf->__Vtrigprevexpr_hbb0eeb4f__0 = VL_RAND_RESET_I(1);
    vlSelf->__VactDidInit = 0;
    for (int __Vi0 = 0; __Vi0 < 2; ++__Vi0) {
        vlSelf->__Vm_traceActivity[__Vi0] = 0;
    }
}
