// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Design implementation internals
// See Vtb_compute_core.h for the primary calling header

#include "Vtb_compute_core__pch.h"
#include "Vtb_compute_core___024root.h"

VL_ATTR_COLD void Vtb_compute_core___024root___eval_final(Vtb_compute_core___024root* vlSelf) {
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_compute_core___024root___eval_final\n"); );
    Vtb_compute_core__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    auto& vlSelfRef = std::ref(*vlSelf).get();
}

#ifdef VL_DEBUG
VL_ATTR_COLD void Vtb_compute_core___024root___dump_triggers__stl(Vtb_compute_core___024root* vlSelf);
#endif  // VL_DEBUG
VL_ATTR_COLD bool Vtb_compute_core___024root___eval_phase__stl(Vtb_compute_core___024root* vlSelf);

VL_ATTR_COLD void Vtb_compute_core___024root___eval_settle(Vtb_compute_core___024root* vlSelf) {
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_compute_core___024root___eval_settle\n"); );
    Vtb_compute_core__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    auto& vlSelfRef = std::ref(*vlSelf).get();
    // Init
    IData/*31:0*/ __VstlIterCount;
    CData/*0:0*/ __VstlContinue;
    // Body
    __VstlIterCount = 0U;
    vlSelfRef.__VstlFirstIteration = 1U;
    __VstlContinue = 1U;
    while (__VstlContinue) {
        if (VL_UNLIKELY(((0x64U < __VstlIterCount)))) {
#ifdef VL_DEBUG
            Vtb_compute_core___024root___dump_triggers__stl(vlSelf);
#endif
            VL_FATAL_MT("tb_compute_core.sv", 3, "", "Settle region did not converge.");
        }
        __VstlIterCount = ((IData)(1U) + __VstlIterCount);
        __VstlContinue = 0U;
        if (Vtb_compute_core___024root___eval_phase__stl(vlSelf)) {
            __VstlContinue = 1U;
        }
        vlSelfRef.__VstlFirstIteration = 0U;
    }
}

#ifdef VL_DEBUG
VL_ATTR_COLD void Vtb_compute_core___024root___dump_triggers__stl(Vtb_compute_core___024root* vlSelf) {
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_compute_core___024root___dump_triggers__stl\n"); );
    Vtb_compute_core__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    auto& vlSelfRef = std::ref(*vlSelf).get();
    // Body
    if ((1U & (~ vlSelfRef.__VstlTriggered.any()))) {
        VL_DBG_MSGF("         No triggers active\n");
    }
    if ((1ULL & vlSelfRef.__VstlTriggered.word(0U))) {
        VL_DBG_MSGF("         'stl' region trigger index 0 is active: Internal 'stl' trigger - first iteration\n");
    }
}
#endif  // VL_DEBUG

VL_ATTR_COLD void Vtb_compute_core___024root___eval_triggers__stl(Vtb_compute_core___024root* vlSelf);
VL_ATTR_COLD void Vtb_compute_core___024root___eval_stl(Vtb_compute_core___024root* vlSelf);

VL_ATTR_COLD bool Vtb_compute_core___024root___eval_phase__stl(Vtb_compute_core___024root* vlSelf) {
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_compute_core___024root___eval_phase__stl\n"); );
    Vtb_compute_core__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    auto& vlSelfRef = std::ref(*vlSelf).get();
    // Init
    CData/*0:0*/ __VstlExecute;
    // Body
    Vtb_compute_core___024root___eval_triggers__stl(vlSelf);
    __VstlExecute = vlSelfRef.__VstlTriggered.any();
    if (__VstlExecute) {
        Vtb_compute_core___024root___eval_stl(vlSelf);
    }
    return (__VstlExecute);
}

#ifdef VL_DEBUG
VL_ATTR_COLD void Vtb_compute_core___024root___dump_triggers__act(Vtb_compute_core___024root* vlSelf) {
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_compute_core___024root___dump_triggers__act\n"); );
    Vtb_compute_core__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    auto& vlSelfRef = std::ref(*vlSelf).get();
    // Body
    if ((1U & (~ vlSelfRef.__VactTriggered.any()))) {
        VL_DBG_MSGF("         No triggers active\n");
    }
    if ((1ULL & vlSelfRef.__VactTriggered.word(0U))) {
        VL_DBG_MSGF("         'act' region trigger index 0 is active: @(posedge tb_compute_core.clk)\n");
    }
    if ((2ULL & vlSelfRef.__VactTriggered.word(0U))) {
        VL_DBG_MSGF("         'act' region trigger index 1 is active: @([true] __VdlySched.awaitingCurrentTime())\n");
    }
    if ((4ULL & vlSelfRef.__VactTriggered.word(0U))) {
        VL_DBG_MSGF("         'act' region trigger index 2 is active: @( tb_compute_core.tb_if.cb.bias_in)\n");
    }
    if ((8ULL & vlSelfRef.__VactTriggered.word(0U))) {
        VL_DBG_MSGF("         'act' region trigger index 3 is active: @( tb_compute_core.tb_if.cb.ia_is_init_data)\n");
    }
    if ((0x10ULL & vlSelfRef.__VactTriggered.word(0U))) {
        VL_DBG_MSGF("         'act' region trigger index 4 is active: @( tb_compute_core.tb_if.cb.ia_calc_done)\n");
    }
    if ((0x20ULL & vlSelfRef.__VactTriggered.word(0U))) {
        VL_DBG_MSGF("         'act' region trigger index 5 is active: @( tb_compute_core.tb_if.cb.ia_row_valid)\n");
    }
    if ((0x40ULL & vlSelfRef.__VactTriggered.word(0U))) {
        VL_DBG_MSGF("         'act' region trigger index 6 is active: @( tb_compute_core.tb_if.cb.ia_vec_in)\n");
    }
    if ((0x80ULL & vlSelfRef.__VactTriggered.word(0U))) {
        VL_DBG_MSGF("         'act' region trigger index 7 is active: @( tb_compute_core.tb_if.cb.weight_in)\n");
    }
    if ((0x100ULL & vlSelfRef.__VactTriggered.word(0U))) {
        VL_DBG_MSGF("         'act' region trigger index 8 is active: @( tb_compute_core.tb_if.cb.store_weight_req)\n");
    }
    if ((0x200ULL & vlSelfRef.__VactTriggered.word(0U))) {
        VL_DBG_MSGF("         'act' region trigger index 9 is active: @([event] tb_compute_core.tb_if.cb)\n");
    }
    if ((0x400ULL & vlSelfRef.__VactTriggered.word(0U))) {
        VL_DBG_MSGF("         'act' region trigger index 10 is active: @( tb_compute_core.__Vcellout__u_dut__partial_sum_calc_over)\n");
    }
    if ((0x800ULL & vlSelfRef.__VactTriggered.word(0U))) {
        VL_DBG_MSGF("         'act' region trigger index 11 is active: @( tb_compute_core.__Vcellout__u_dut__tile_calc_over)\n");
    }
}
#endif  // VL_DEBUG

#ifdef VL_DEBUG
VL_ATTR_COLD void Vtb_compute_core___024root___dump_triggers__react(Vtb_compute_core___024root* vlSelf) {
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_compute_core___024root___dump_triggers__react\n"); );
    Vtb_compute_core__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    auto& vlSelfRef = std::ref(*vlSelf).get();
    // Body
    if ((1U & (~ vlSelfRef.__VreactTriggered.any()))) {
        VL_DBG_MSGF("         No triggers active\n");
    }
    if ((1ULL & vlSelfRef.__VreactTriggered.word(0U))) {
        VL_DBG_MSGF("         'react' region trigger index 0 is active: @(posedge tb_compute_core.clk)\n");
    }
    if ((2ULL & vlSelfRef.__VreactTriggered.word(0U))) {
        VL_DBG_MSGF("         'react' region trigger index 1 is active: @([true] __VdlySched.awaitingCurrentTime())\n");
    }
    if ((4ULL & vlSelfRef.__VreactTriggered.word(0U))) {
        VL_DBG_MSGF("         'react' region trigger index 2 is active: @( tb_compute_core.tb_if.cb.bias_in)\n");
    }
    if ((8ULL & vlSelfRef.__VreactTriggered.word(0U))) {
        VL_DBG_MSGF("         'react' region trigger index 3 is active: @( tb_compute_core.tb_if.cb.ia_is_init_data)\n");
    }
    if ((0x10ULL & vlSelfRef.__VreactTriggered.word(0U))) {
        VL_DBG_MSGF("         'react' region trigger index 4 is active: @( tb_compute_core.tb_if.cb.ia_calc_done)\n");
    }
    if ((0x20ULL & vlSelfRef.__VreactTriggered.word(0U))) {
        VL_DBG_MSGF("         'react' region trigger index 5 is active: @( tb_compute_core.tb_if.cb.ia_row_valid)\n");
    }
    if ((0x40ULL & vlSelfRef.__VreactTriggered.word(0U))) {
        VL_DBG_MSGF("         'react' region trigger index 6 is active: @( tb_compute_core.tb_if.cb.ia_vec_in)\n");
    }
    if ((0x80ULL & vlSelfRef.__VreactTriggered.word(0U))) {
        VL_DBG_MSGF("         'react' region trigger index 7 is active: @( tb_compute_core.tb_if.cb.weight_in)\n");
    }
    if ((0x100ULL & vlSelfRef.__VreactTriggered.word(0U))) {
        VL_DBG_MSGF("         'react' region trigger index 8 is active: @( tb_compute_core.tb_if.cb.store_weight_req)\n");
    }
    if ((0x200ULL & vlSelfRef.__VreactTriggered.word(0U))) {
        VL_DBG_MSGF("         'react' region trigger index 9 is active: @([event] tb_compute_core.tb_if.cb)\n");
    }
    if ((0x400ULL & vlSelfRef.__VreactTriggered.word(0U))) {
        VL_DBG_MSGF("         'react' region trigger index 10 is active: @( tb_compute_core.__Vcellout__u_dut__partial_sum_calc_over)\n");
    }
    if ((0x800ULL & vlSelfRef.__VreactTriggered.word(0U))) {
        VL_DBG_MSGF("         'react' region trigger index 11 is active: @( tb_compute_core.__Vcellout__u_dut__tile_calc_over)\n");
    }
}
#endif  // VL_DEBUG

#ifdef VL_DEBUG
VL_ATTR_COLD void Vtb_compute_core___024root___dump_triggers__obs(Vtb_compute_core___024root* vlSelf) {
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_compute_core___024root___dump_triggers__obs\n"); );
    Vtb_compute_core__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    auto& vlSelfRef = std::ref(*vlSelf).get();
    // Body
    if ((1U & (~ vlSelfRef.__VobsTriggered.any()))) {
        VL_DBG_MSGF("         No triggers active\n");
    }
    if ((1ULL & vlSelfRef.__VobsTriggered.word(0U))) {
        VL_DBG_MSGF("         'obs' region trigger index 0 is active: @(posedge tb_compute_core.clk)\n");
    }
    if ((2ULL & vlSelfRef.__VobsTriggered.word(0U))) {
        VL_DBG_MSGF("         'obs' region trigger index 1 is active: @([true] __VdlySched.awaitingCurrentTime())\n");
    }
    if ((4ULL & vlSelfRef.__VobsTriggered.word(0U))) {
        VL_DBG_MSGF("         'obs' region trigger index 2 is active: @( tb_compute_core.tb_if.cb.bias_in)\n");
    }
    if ((8ULL & vlSelfRef.__VobsTriggered.word(0U))) {
        VL_DBG_MSGF("         'obs' region trigger index 3 is active: @( tb_compute_core.tb_if.cb.ia_is_init_data)\n");
    }
    if ((0x10ULL & vlSelfRef.__VobsTriggered.word(0U))) {
        VL_DBG_MSGF("         'obs' region trigger index 4 is active: @( tb_compute_core.tb_if.cb.ia_calc_done)\n");
    }
    if ((0x20ULL & vlSelfRef.__VobsTriggered.word(0U))) {
        VL_DBG_MSGF("         'obs' region trigger index 5 is active: @( tb_compute_core.tb_if.cb.ia_row_valid)\n");
    }
    if ((0x40ULL & vlSelfRef.__VobsTriggered.word(0U))) {
        VL_DBG_MSGF("         'obs' region trigger index 6 is active: @( tb_compute_core.tb_if.cb.ia_vec_in)\n");
    }
    if ((0x80ULL & vlSelfRef.__VobsTriggered.word(0U))) {
        VL_DBG_MSGF("         'obs' region trigger index 7 is active: @( tb_compute_core.tb_if.cb.weight_in)\n");
    }
    if ((0x100ULL & vlSelfRef.__VobsTriggered.word(0U))) {
        VL_DBG_MSGF("         'obs' region trigger index 8 is active: @( tb_compute_core.tb_if.cb.store_weight_req)\n");
    }
    if ((0x200ULL & vlSelfRef.__VobsTriggered.word(0U))) {
        VL_DBG_MSGF("         'obs' region trigger index 9 is active: @([event] tb_compute_core.tb_if.cb)\n");
    }
    if ((0x400ULL & vlSelfRef.__VobsTriggered.word(0U))) {
        VL_DBG_MSGF("         'obs' region trigger index 10 is active: @( tb_compute_core.__Vcellout__u_dut__partial_sum_calc_over)\n");
    }
    if ((0x800ULL & vlSelfRef.__VobsTriggered.word(0U))) {
        VL_DBG_MSGF("         'obs' region trigger index 11 is active: @( tb_compute_core.__Vcellout__u_dut__tile_calc_over)\n");
    }
}
#endif  // VL_DEBUG

#ifdef VL_DEBUG
VL_ATTR_COLD void Vtb_compute_core___024root___dump_triggers__nba(Vtb_compute_core___024root* vlSelf) {
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_compute_core___024root___dump_triggers__nba\n"); );
    Vtb_compute_core__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    auto& vlSelfRef = std::ref(*vlSelf).get();
    // Body
    if ((1U & (~ vlSelfRef.__VnbaTriggered.any()))) {
        VL_DBG_MSGF("         No triggers active\n");
    }
    if ((1ULL & vlSelfRef.__VnbaTriggered.word(0U))) {
        VL_DBG_MSGF("         'nba' region trigger index 0 is active: @(posedge tb_compute_core.clk)\n");
    }
    if ((2ULL & vlSelfRef.__VnbaTriggered.word(0U))) {
        VL_DBG_MSGF("         'nba' region trigger index 1 is active: @([true] __VdlySched.awaitingCurrentTime())\n");
    }
    if ((4ULL & vlSelfRef.__VnbaTriggered.word(0U))) {
        VL_DBG_MSGF("         'nba' region trigger index 2 is active: @( tb_compute_core.tb_if.cb.bias_in)\n");
    }
    if ((8ULL & vlSelfRef.__VnbaTriggered.word(0U))) {
        VL_DBG_MSGF("         'nba' region trigger index 3 is active: @( tb_compute_core.tb_if.cb.ia_is_init_data)\n");
    }
    if ((0x10ULL & vlSelfRef.__VnbaTriggered.word(0U))) {
        VL_DBG_MSGF("         'nba' region trigger index 4 is active: @( tb_compute_core.tb_if.cb.ia_calc_done)\n");
    }
    if ((0x20ULL & vlSelfRef.__VnbaTriggered.word(0U))) {
        VL_DBG_MSGF("         'nba' region trigger index 5 is active: @( tb_compute_core.tb_if.cb.ia_row_valid)\n");
    }
    if ((0x40ULL & vlSelfRef.__VnbaTriggered.word(0U))) {
        VL_DBG_MSGF("         'nba' region trigger index 6 is active: @( tb_compute_core.tb_if.cb.ia_vec_in)\n");
    }
    if ((0x80ULL & vlSelfRef.__VnbaTriggered.word(0U))) {
        VL_DBG_MSGF("         'nba' region trigger index 7 is active: @( tb_compute_core.tb_if.cb.weight_in)\n");
    }
    if ((0x100ULL & vlSelfRef.__VnbaTriggered.word(0U))) {
        VL_DBG_MSGF("         'nba' region trigger index 8 is active: @( tb_compute_core.tb_if.cb.store_weight_req)\n");
    }
    if ((0x200ULL & vlSelfRef.__VnbaTriggered.word(0U))) {
        VL_DBG_MSGF("         'nba' region trigger index 9 is active: @([event] tb_compute_core.tb_if.cb)\n");
    }
    if ((0x400ULL & vlSelfRef.__VnbaTriggered.word(0U))) {
        VL_DBG_MSGF("         'nba' region trigger index 10 is active: @( tb_compute_core.__Vcellout__u_dut__partial_sum_calc_over)\n");
    }
    if ((0x800ULL & vlSelfRef.__VnbaTriggered.word(0U))) {
        VL_DBG_MSGF("         'nba' region trigger index 11 is active: @( tb_compute_core.__Vcellout__u_dut__tile_calc_over)\n");
    }
}
#endif  // VL_DEBUG

VL_ATTR_COLD void Vtb_compute_core___024root____Vm_traceActivitySetAll(Vtb_compute_core___024root* vlSelf) {
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_compute_core___024root____Vm_traceActivitySetAll\n"); );
    Vtb_compute_core__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    auto& vlSelfRef = std::ref(*vlSelf).get();
    // Body
    vlSelfRef.__Vm_traceActivity[0U] = 1U;
    vlSelfRef.__Vm_traceActivity[1U] = 1U;
    vlSelfRef.__Vm_traceActivity[2U] = 1U;
    vlSelfRef.__Vm_traceActivity[3U] = 1U;
    vlSelfRef.__Vm_traceActivity[4U] = 1U;
    vlSelfRef.__Vm_traceActivity[5U] = 1U;
    vlSelfRef.__Vm_traceActivity[6U] = 1U;
}

VL_ATTR_COLD void Vtb_compute_core___024root___ctor_var_reset(Vtb_compute_core___024root* vlSelf) {
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_compute_core___024root___ctor_var_reset\n"); );
    Vtb_compute_core__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    auto& vlSelfRef = std::ref(*vlSelf).get();
    // Body
    const uint64_t __VscopeHash = VL_MURMUR64_HASH(vlSelf->name());
    vlSelf->tb_compute_core__DOT__clk = VL_SCOPED_RAND_RESET_I(1, __VscopeHash, 3008233840291440629ull);
    for (int __Vi0 = 0; __Vi0 < 64; ++__Vi0) {
        vlSelf->tb_compute_core__DOT__weight_mem_raw[__Vi0] = VL_SCOPED_RAND_RESET_I(8, __VscopeHash, 13212004506727082141ull);
    }
    for (int __Vi0 = 0; __Vi0 < 64; ++__Vi0) {
        vlSelf->tb_compute_core__DOT__ia_mem_raw[__Vi0] = VL_SCOPED_RAND_RESET_I(16, __VscopeHash, 17784400868873886019ull);
    }
    for (int __Vi0 = 0; __Vi0 < 16; ++__Vi0) {
        vlSelf->tb_compute_core__DOT__weight_mem[__Vi0] = VL_SCOPED_RAND_RESET_I(32, __VscopeHash, 13345723773575052832ull);
    }
    for (int __Vi0 = 0; __Vi0 < 32; ++__Vi0) {
        vlSelf->tb_compute_core__DOT__ia_mem[__Vi0] = VL_SCOPED_RAND_RESET_I(32, __VscopeHash, 2254803621887296302ull);
    }
    for (int __Vi0 = 0; __Vi0 < 16; ++__Vi0) {
        vlSelf->tb_compute_core__DOT__exp_mem[__Vi0] = VL_SCOPED_RAND_RESET_I(32, __VscopeHash, 16325810077441829882ull);
    }
    for (int __Vi0 = 0; __Vi0 < 4; ++__Vi0) {
        vlSelf->tb_compute_core__DOT__bias_mem[__Vi0] = VL_SCOPED_RAND_RESET_I(32, __VscopeHash, 16887546368901734913ull);
    }
    for (int __Vi0 = 0; __Vi0 < 16; ++__Vi0) {
        vlSelf->tb_compute_core__DOT__out_buf[__Vi0] = VL_SCOPED_RAND_RESET_I(32, __VscopeHash, 16169257389629790421ull);
    }
    vlSelf->tb_compute_core__DOT__out_rows = VL_SCOPED_RAND_RESET_I(32, __VscopeHash, 7505720726963422351ull);
    vlSelf->tb_compute_core__DOT__errors = VL_SCOPED_RAND_RESET_I(32, __VscopeHash, 668102754838806306ull);
    vlSelf->tb_compute_core__DOT__idx = VL_SCOPED_RAND_RESET_I(32, __VscopeHash, 4772398467622943913ull);
    vlSelf->tb_compute_core__DOT__NUM_K = VL_SCOPED_RAND_RESET_I(32, __VscopeHash, 3874279796466784080ull);
    vlSelf->tb_compute_core__DOT__NUM_SEG = VL_SCOPED_RAND_RESET_I(32, __VscopeHash, 15251466288565413844ull);
    for (int __Vi0 = 0; __Vi0 < 4; ++__Vi0) {
        for (int __Vi1 = 0; __Vi1 < 4; ++__Vi1) {
            vlSelf->tb_compute_core__DOT__tile_buf[__Vi0][__Vi1] = VL_SCOPED_RAND_RESET_I(8, __VscopeHash, 8834556232330383813ull);
        }
    }
    vlSelf->tb_compute_core__DOT____Vcellout__u_dut__partial_sum_calc_over = VL_SCOPED_RAND_RESET_I(1, __VscopeHash, 15485831409604102769ull);
    vlSelf->tb_compute_core__DOT____Vcellout__u_dut__tile_calc_over = VL_SCOPED_RAND_RESET_I(1, __VscopeHash, 1972685353935560543ull);
    for (int __Vi0 = 0; __Vi0 < 4; ++__Vi0) {
        vlSelf->tb_compute_core__DOT____Vcellout__u_dut__acc_data_out[__Vi0] = VL_SCOPED_RAND_RESET_I(32, __VscopeHash, 462896708855343240ull);
    }
    for (int __Vi0 = 0; __Vi0 < 4; ++__Vi0) {
        vlSelf->tb_compute_core__DOT____Vcellinp__u_dut__bias_in[__Vi0] = VL_SCOPED_RAND_RESET_I(32, __VscopeHash, 6684179211972959500ull);
    }
    for (int __Vi0 = 0; __Vi0 < 4; ++__Vi0) {
        vlSelf->tb_compute_core__DOT____Vcellinp__u_dut__ia_vec_in[__Vi0] = VL_SCOPED_RAND_RESET_I(16, __VscopeHash, 6907417860760638304ull);
    }
    for (int __Vi0 = 0; __Vi0 < 4; ++__Vi0) {
        vlSelf->tb_compute_core__DOT____Vcellinp__u_dut__weight_in[__Vi0] = VL_SCOPED_RAND_RESET_I(8, __VscopeHash, 18276564111606777796ull);
    }
    vlSelf->tb_compute_core__DOT__unnamedblk1__DOT__c = 0;
    vlSelf->tb_compute_core__DOT__unnamedblk2__DOT__i = 0;
    vlSelf->tb_compute_core__DOT__unnamedblk3__DOT__i = 0;
    vlSelf->tb_compute_core__DOT__unnamedblk4__DOT__seg = 0;
    vlSelf->tb_compute_core__DOT__unnamedblk5__DOT__r = 0;
    vlSelf->tb_compute_core__DOT__unnamedblk5__DOT__unnamedblk6__DOT__c = 0;
    for (int __Vi0 = 0; __Vi0 < 4; ++__Vi0) {
        vlSelf->tb_compute_core__DOT__u_dut__DOT__data_setup_out[__Vi0] = VL_SCOPED_RAND_RESET_I(16, __VscopeHash, 12880077240975690982ull);
    }
    for (int __Vi0 = 0; __Vi0 < 4; ++__Vi0) {
        vlSelf->tb_compute_core__DOT__u_dut__DOT__sa_sum_out[__Vi0] = VL_SCOPED_RAND_RESET_I(32, __VscopeHash, 7749723435644852928ull);
    }
    for (int __Vi0 = 0; __Vi0 < 4; ++__Vi0) {
        vlSelf->tb_compute_core__DOT__u_dut__DOT____Vcellout__u_data_setup__data_out[__Vi0] = VL_SCOPED_RAND_RESET_I(16, __VscopeHash, 11632625748989352478ull);
    }
    for (int __Vi0 = 0; __Vi0 < 4; ++__Vi0) {
        vlSelf->tb_compute_core__DOT__u_dut__DOT____Vcellinp__u_data_setup__data_in[__Vi0] = VL_SCOPED_RAND_RESET_I(16, __VscopeHash, 3271519290780348152ull);
    }
    for (int __Vi0 = 0; __Vi0 < 4; ++__Vi0) {
        vlSelf->tb_compute_core__DOT__u_dut__DOT____Vcellout__u_accumulator_array__data_out[__Vi0] = VL_SCOPED_RAND_RESET_I(32, __VscopeHash, 14141371653490395189ull);
    }
    for (int __Vi0 = 0; __Vi0 < 4; ++__Vi0) {
        vlSelf->tb_compute_core__DOT__u_dut__DOT____Vcellinp__u_accumulator_array__data_in[__Vi0] = VL_SCOPED_RAND_RESET_I(32, __VscopeHash, 15362772233420499040ull);
    }
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__1__KET____DOT__gen_delay_1__DOT__shift_reg = VL_SCOPED_RAND_RESET_I(16, __VscopeHash, 10399882893538057956ull);
    for (int __Vi0 = 0; __Vi0 < 2; ++__Vi0) {
        vlSelf->tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__2__KET____DOT__gen_delay_n__DOT__shift_reg[__Vi0] = VL_SCOPED_RAND_RESET_I(16, __VscopeHash, 10340075116611813390ull);
    }
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__2__KET____DOT__gen_delay_n__DOT__k = VL_SCOPED_RAND_RESET_I(32, __VscopeHash, 5106532661152884150ull);
    for (int __Vi0 = 0; __Vi0 < 3; ++__Vi0) {
        vlSelf->tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__3__KET____DOT__gen_delay_n__DOT__shift_reg[__Vi0] = VL_SCOPED_RAND_RESET_I(16, __VscopeHash, 3095717098072568262ull);
    }
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__3__KET____DOT__gen_delay_n__DOT__k = VL_SCOPED_RAND_RESET_I(32, __VscopeHash, 2671547605936672812ull);
    for (int __Vi0 = 0; __Vi0 < 4; ++__Vi0) {
        vlSelf->tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__input_valid_shift[__Vi0] = VL_SCOPED_RAND_RESET_I(1, __VscopeHash, 17974273758562885256ull);
    }
    for (int __Vi0 = 0; __Vi0 < 4; ++__Vi0) {
        vlSelf->tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__calc_done_shift[__Vi0] = VL_SCOPED_RAND_RESET_I(1, __VscopeHash, 2976663038305601270ull);
    }
    for (int __Vi0 = 0; __Vi0 < 4; ++__Vi0) {
        vlSelf->tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__is_init_data_shift[__Vi0] = VL_SCOPED_RAND_RESET_I(1, __VscopeHash, 15909434001524804436ull);
    }
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__unnamedblk1__DOT__m = VL_SCOPED_RAND_RESET_I(32, __VscopeHash, 12639404308949724015ull);
    for (int __Vi0 = 0; __Vi0 < 4; ++__Vi0) {
        for (int __Vi1 = 0; __Vi1 < 4; ++__Vi1) {
            vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe[__Vi0][__Vi1] = VL_SCOPED_RAND_RESET_I(16, __VscopeHash, 6849073285075590770ull);
        }
    }
    for (int __Vi0 = 0; __Vi0 < 4; ++__Vi0) {
        for (int __Vi1 = 0; __Vi1 < 4; ++__Vi1) {
            vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe[__Vi0][__Vi1] = VL_SCOPED_RAND_RESET_I(8, __VscopeHash, 10249430091499433921ull);
        }
    }
    for (int __Vi0 = 0; __Vi0 < 4; ++__Vi0) {
        for (int __Vi1 = 0; __Vi1 < 4; ++__Vi1) {
            vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe[__Vi0][__Vi1] = VL_SCOPED_RAND_RESET_I(32, __VscopeHash, 493349923477663358ull);
        }
    }
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__data_reg = VL_SCOPED_RAND_RESET_I(16, __VscopeHash, 17026158353486610667ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__weight_reg = VL_SCOPED_RAND_RESET_I(8, __VscopeHash, 6712734520370873761ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_reg = VL_SCOPED_RAND_RESET_I(32, __VscopeHash, 3025636422634284660ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__mult_result = VL_SCOPED_RAND_RESET_I(32, __VscopeHash, 601163693388884071ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext = VL_SCOPED_RAND_RESET_Q(33, __VscopeHash, 17861144491458261364ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__data_reg = VL_SCOPED_RAND_RESET_I(16, __VscopeHash, 2753924428690799451ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__weight_reg = VL_SCOPED_RAND_RESET_I(8, __VscopeHash, 4687892208853095252ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_reg = VL_SCOPED_RAND_RESET_I(32, __VscopeHash, 3602168954167771267ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__mult_result = VL_SCOPED_RAND_RESET_I(32, __VscopeHash, 3769894376635056182ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext = VL_SCOPED_RAND_RESET_Q(33, __VscopeHash, 11348381960284461642ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__data_reg = VL_SCOPED_RAND_RESET_I(16, __VscopeHash, 13739076793364030336ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__weight_reg = VL_SCOPED_RAND_RESET_I(8, __VscopeHash, 12753994117727297194ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_reg = VL_SCOPED_RAND_RESET_I(32, __VscopeHash, 6814114351036984680ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__mult_result = VL_SCOPED_RAND_RESET_I(32, __VscopeHash, 1215308912924174992ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext = VL_SCOPED_RAND_RESET_Q(33, __VscopeHash, 15369428932722236711ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__data_reg = VL_SCOPED_RAND_RESET_I(16, __VscopeHash, 16793162835011830020ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__weight_reg = VL_SCOPED_RAND_RESET_I(8, __VscopeHash, 8946403661324468343ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_reg = VL_SCOPED_RAND_RESET_I(32, __VscopeHash, 2234803026141020474ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__mult_result = VL_SCOPED_RAND_RESET_I(32, __VscopeHash, 7224640844628219705ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext = VL_SCOPED_RAND_RESET_Q(33, __VscopeHash, 9795780690890011336ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__data_reg = VL_SCOPED_RAND_RESET_I(16, __VscopeHash, 15732306190975439124ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__weight_reg = VL_SCOPED_RAND_RESET_I(8, __VscopeHash, 16086456301692710504ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_reg = VL_SCOPED_RAND_RESET_I(32, __VscopeHash, 6916626623590639602ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__mult_result = VL_SCOPED_RAND_RESET_I(32, __VscopeHash, 5723539025205535652ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext = VL_SCOPED_RAND_RESET_Q(33, __VscopeHash, 13732843597636812177ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__data_reg = VL_SCOPED_RAND_RESET_I(16, __VscopeHash, 9207416852153404409ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__weight_reg = VL_SCOPED_RAND_RESET_I(8, __VscopeHash, 840731767863618328ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_reg = VL_SCOPED_RAND_RESET_I(32, __VscopeHash, 6690938864187654952ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__mult_result = VL_SCOPED_RAND_RESET_I(32, __VscopeHash, 7904386560561384714ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext = VL_SCOPED_RAND_RESET_Q(33, __VscopeHash, 11698828890232744046ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__data_reg = VL_SCOPED_RAND_RESET_I(16, __VscopeHash, 6350956685427503872ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__weight_reg = VL_SCOPED_RAND_RESET_I(8, __VscopeHash, 6577305386908043509ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_reg = VL_SCOPED_RAND_RESET_I(32, __VscopeHash, 10845156711485658835ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__mult_result = VL_SCOPED_RAND_RESET_I(32, __VscopeHash, 5388289591552067380ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext = VL_SCOPED_RAND_RESET_Q(33, __VscopeHash, 2723031841868927345ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__data_reg = VL_SCOPED_RAND_RESET_I(16, __VscopeHash, 17500209262182815241ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__weight_reg = VL_SCOPED_RAND_RESET_I(8, __VscopeHash, 6989012152686223071ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_reg = VL_SCOPED_RAND_RESET_I(32, __VscopeHash, 7808735559784586855ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__mult_result = VL_SCOPED_RAND_RESET_I(32, __VscopeHash, 7095968387638005528ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext = VL_SCOPED_RAND_RESET_Q(33, __VscopeHash, 2459188547683024328ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__data_reg = VL_SCOPED_RAND_RESET_I(16, __VscopeHash, 13792465747035905770ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__weight_reg = VL_SCOPED_RAND_RESET_I(8, __VscopeHash, 16280055125710487916ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_reg = VL_SCOPED_RAND_RESET_I(32, __VscopeHash, 13414554312040353153ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__mult_result = VL_SCOPED_RAND_RESET_I(32, __VscopeHash, 10882314423405295435ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext = VL_SCOPED_RAND_RESET_Q(33, __VscopeHash, 6571425496986590038ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__data_reg = VL_SCOPED_RAND_RESET_I(16, __VscopeHash, 10497777253043466782ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__weight_reg = VL_SCOPED_RAND_RESET_I(8, __VscopeHash, 5506812677280555585ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_reg = VL_SCOPED_RAND_RESET_I(32, __VscopeHash, 5832982941373111059ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__mult_result = VL_SCOPED_RAND_RESET_I(32, __VscopeHash, 2691685112042559025ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext = VL_SCOPED_RAND_RESET_Q(33, __VscopeHash, 8648034592834583983ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__data_reg = VL_SCOPED_RAND_RESET_I(16, __VscopeHash, 4253401650265767039ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__weight_reg = VL_SCOPED_RAND_RESET_I(8, __VscopeHash, 10192791613953222142ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_reg = VL_SCOPED_RAND_RESET_I(32, __VscopeHash, 4803474301668147704ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__mult_result = VL_SCOPED_RAND_RESET_I(32, __VscopeHash, 662132880609574183ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext = VL_SCOPED_RAND_RESET_Q(33, __VscopeHash, 720218564898114665ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__data_reg = VL_SCOPED_RAND_RESET_I(16, __VscopeHash, 10925270043957231388ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__weight_reg = VL_SCOPED_RAND_RESET_I(8, __VscopeHash, 10975547538558572007ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_reg = VL_SCOPED_RAND_RESET_I(32, __VscopeHash, 8777116780795452872ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__mult_result = VL_SCOPED_RAND_RESET_I(32, __VscopeHash, 13644039093407942504ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext = VL_SCOPED_RAND_RESET_Q(33, __VscopeHash, 17322688552591225692ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__data_reg = VL_SCOPED_RAND_RESET_I(16, __VscopeHash, 16625138798652212639ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__weight_reg = VL_SCOPED_RAND_RESET_I(8, __VscopeHash, 10641517472557895418ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_reg = VL_SCOPED_RAND_RESET_I(32, __VscopeHash, 4655346737156802779ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__mult_result = VL_SCOPED_RAND_RESET_I(32, __VscopeHash, 16021881523611922293ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext = VL_SCOPED_RAND_RESET_Q(33, __VscopeHash, 12883776747187520737ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__data_reg = VL_SCOPED_RAND_RESET_I(16, __VscopeHash, 9636042465385978987ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__weight_reg = VL_SCOPED_RAND_RESET_I(8, __VscopeHash, 14851683660587310380ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_reg = VL_SCOPED_RAND_RESET_I(32, __VscopeHash, 13256718424113526471ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__mult_result = VL_SCOPED_RAND_RESET_I(32, __VscopeHash, 8676511150695241497ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext = VL_SCOPED_RAND_RESET_Q(33, __VscopeHash, 12474310497247363058ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__data_reg = VL_SCOPED_RAND_RESET_I(16, __VscopeHash, 8155530755143592898ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__weight_reg = VL_SCOPED_RAND_RESET_I(8, __VscopeHash, 15948726088652990243ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_reg = VL_SCOPED_RAND_RESET_I(32, __VscopeHash, 3435194936279981120ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__mult_result = VL_SCOPED_RAND_RESET_I(32, __VscopeHash, 4888800724482263937ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext = VL_SCOPED_RAND_RESET_Q(33, __VscopeHash, 8422800023704077526ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__data_reg = VL_SCOPED_RAND_RESET_I(16, __VscopeHash, 6762170240796719017ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__weight_reg = VL_SCOPED_RAND_RESET_I(8, __VscopeHash, 7388953042970645241ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_reg = VL_SCOPED_RAND_RESET_I(32, __VscopeHash, 16315649293169532202ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__mult_result = VL_SCOPED_RAND_RESET_I(32, __VscopeHash, 6143262181640363310ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext = VL_SCOPED_RAND_RESET_Q(33, __VscopeHash, 12690166941960967461ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__calc_done_o_d = VL_SCOPED_RAND_RESET_I(1, __VscopeHash, 16823226549118674879ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__input_valid_chain_d = VL_SCOPED_RAND_RESET_I(1, __VscopeHash, 248945846112988988ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__input_valid_i_d = VL_SCOPED_RAND_RESET_I(1, __VscopeHash, 15801482778557498427ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__read_ptr = VL_SCOPED_RAND_RESET_I(2, __VscopeHash, 7145911758002848105ull);
    for (int __Vi0 = 0; __Vi0 < 4; ++__Vi0) {
        vlSelf->tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__acc_fifo[__Vi0] = VL_SCOPED_RAND_RESET_I(32, __VscopeHash, 3821604106544576971ull);
    }
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__is_init_data_reg = VL_SCOPED_RAND_RESET_I(1, __VscopeHash, 1206523116772710114ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__input_valid_reg = VL_SCOPED_RAND_RESET_I(1, __VscopeHash, 8039812740316469735ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__calc_done_reg = VL_SCOPED_RAND_RESET_I(1, __VscopeHash, 9472005379051292734ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__write_ptr = VL_SCOPED_RAND_RESET_I(2, __VscopeHash, 451429466490320794ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__input_valid_i_d = VL_SCOPED_RAND_RESET_I(1, __VscopeHash, 808238721867857440ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__unnamedblk1__DOT__sum = VL_SCOPED_RAND_RESET_Q(33, __VscopeHash, 9325984966184665165ull);
    for (int __Vi0 = 0; __Vi0 < 4; ++__Vi0) {
        vlSelf->tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__acc_fifo[__Vi0] = VL_SCOPED_RAND_RESET_I(32, __VscopeHash, 14106903939113362591ull);
    }
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__is_init_data_reg = VL_SCOPED_RAND_RESET_I(1, __VscopeHash, 16971657149709605336ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__input_valid_reg = VL_SCOPED_RAND_RESET_I(1, __VscopeHash, 8930876224087578286ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__calc_done_reg = VL_SCOPED_RAND_RESET_I(1, __VscopeHash, 98195352030974478ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__write_ptr = VL_SCOPED_RAND_RESET_I(2, __VscopeHash, 8901191838207054332ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__input_valid_i_d = VL_SCOPED_RAND_RESET_I(1, __VscopeHash, 13994602900769770453ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__unnamedblk1__DOT__sum = VL_SCOPED_RAND_RESET_Q(33, __VscopeHash, 10086011207239431616ull);
    for (int __Vi0 = 0; __Vi0 < 4; ++__Vi0) {
        vlSelf->tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__acc_fifo[__Vi0] = VL_SCOPED_RAND_RESET_I(32, __VscopeHash, 13444753272140500190ull);
    }
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__is_init_data_reg = VL_SCOPED_RAND_RESET_I(1, __VscopeHash, 6463338832613450041ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__input_valid_reg = VL_SCOPED_RAND_RESET_I(1, __VscopeHash, 10227731210138800064ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__calc_done_reg = VL_SCOPED_RAND_RESET_I(1, __VscopeHash, 16547441503447602870ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__write_ptr = VL_SCOPED_RAND_RESET_I(2, __VscopeHash, 10966747434314342186ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__input_valid_i_d = VL_SCOPED_RAND_RESET_I(1, __VscopeHash, 981852242387379901ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__unnamedblk1__DOT__sum = VL_SCOPED_RAND_RESET_Q(33, __VscopeHash, 5699495203873442191ull);
    for (int __Vi0 = 0; __Vi0 < 4; ++__Vi0) {
        vlSelf->tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__acc_fifo[__Vi0] = VL_SCOPED_RAND_RESET_I(32, __VscopeHash, 13127666345938879537ull);
    }
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__is_init_data_reg = VL_SCOPED_RAND_RESET_I(1, __VscopeHash, 3804703034569313782ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__input_valid_reg = VL_SCOPED_RAND_RESET_I(1, __VscopeHash, 3932517534363276495ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__calc_done_reg = VL_SCOPED_RAND_RESET_I(1, __VscopeHash, 1494491248549580644ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__write_ptr = VL_SCOPED_RAND_RESET_I(2, __VscopeHash, 6092157857812469819ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__input_valid_i_d = VL_SCOPED_RAND_RESET_I(1, __VscopeHash, 3219736094602285717ull);
    vlSelf->tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__unnamedblk1__DOT__sum = VL_SCOPED_RAND_RESET_Q(33, __VscopeHash, 16643763060136214564ull);
    vlSelf->__VdlyVal__tb_compute_core__DOT__clk__v0 = VL_SCOPED_RAND_RESET_I(1, __VscopeHash, 1539191537266059751ull);
    vlSelf->__VdlySet__tb_compute_core__DOT__clk__v0 = 0;
    vlSelf->__Vtrigprevexpr___TOP__tb_compute_core__DOT__clk__0 = VL_SCOPED_RAND_RESET_I(1, __VscopeHash, 11116629276636599471ull);
    for (int __Vi0 = 0; __Vi0 < 4; ++__Vi0) {
        vlSelf->__Vtrigprevexpr___TOP__tb_compute_core__DOT__tb_if__cb__DOT__bias_in__0[__Vi0] = VL_SCOPED_RAND_RESET_I(32, __VscopeHash, 1495510069430112818ull);
    }
    vlSelf->__Vtrigprevexpr___TOP__tb_compute_core__DOT__tb_if__cb__DOT__ia_is_init_data__0 = VL_SCOPED_RAND_RESET_I(1, __VscopeHash, 16393603258328758503ull);
    vlSelf->__Vtrigprevexpr___TOP__tb_compute_core__DOT__tb_if__cb__DOT__ia_calc_done__0 = VL_SCOPED_RAND_RESET_I(1, __VscopeHash, 15257523313110195845ull);
    vlSelf->__Vtrigprevexpr___TOP__tb_compute_core__DOT__tb_if__cb__DOT__ia_row_valid__0 = VL_SCOPED_RAND_RESET_I(1, __VscopeHash, 1157575082884574563ull);
    for (int __Vi0 = 0; __Vi0 < 4; ++__Vi0) {
        vlSelf->__Vtrigprevexpr___TOP__tb_compute_core__DOT__tb_if__cb__DOT__ia_vec_in__0[__Vi0] = VL_SCOPED_RAND_RESET_I(16, __VscopeHash, 18079083184495877299ull);
    }
    for (int __Vi0 = 0; __Vi0 < 4; ++__Vi0) {
        vlSelf->__Vtrigprevexpr___TOP__tb_compute_core__DOT__tb_if__cb__DOT__weight_in__0[__Vi0] = VL_SCOPED_RAND_RESET_I(8, __VscopeHash, 531439087738759050ull);
    }
    vlSelf->__Vtrigprevexpr___TOP__tb_compute_core__DOT__tb_if__cb__DOT__store_weight_req__0 = VL_SCOPED_RAND_RESET_I(1, __VscopeHash, 10453543510182837146ull);
    vlSelf->__Vtrigprevexpr___TOP__tb_compute_core__DOT____Vcellout__u_dut__partial_sum_calc_over__0 = VL_SCOPED_RAND_RESET_I(1, __VscopeHash, 14181940856513691038ull);
    vlSelf->__Vtrigprevexpr___TOP__tb_compute_core__DOT____Vcellout__u_dut__tile_calc_over__0 = VL_SCOPED_RAND_RESET_I(1, __VscopeHash, 9459348403977042922ull);
    vlSelf->__VactDidInit = 0;
    for (int __Vi0 = 0; __Vi0 < 7; ++__Vi0) {
        vlSelf->__Vm_traceActivity[__Vi0] = 0;
    }
}
