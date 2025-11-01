// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Design implementation internals
// See Vtb_e203_nice.h for the primary calling header

#include "Vtb_e203_nice__pch.h"
#include "Vtb_e203_nice___024root.h"

VL_ATTR_COLD void Vtb_e203_nice___024root___eval_final(Vtb_e203_nice___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vtb_e203_nice__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_e203_nice___024root___eval_final\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
}

#ifdef VL_DEBUG
VL_ATTR_COLD void Vtb_e203_nice___024root___dump_triggers__stl(Vtb_e203_nice___024root* vlSelf);
#endif  // VL_DEBUG
VL_ATTR_COLD bool Vtb_e203_nice___024root___eval_phase__stl(Vtb_e203_nice___024root* vlSelf);

VL_ATTR_COLD void Vtb_e203_nice___024root___eval_settle(Vtb_e203_nice___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vtb_e203_nice__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_e203_nice___024root___eval_settle\n"); );
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
            Vtb_e203_nice___024root___dump_triggers__stl(vlSelf);
#endif
            VL_FATAL_MT("tb_e203_nice.sv", 5, "", "Settle region did not converge.");
        }
        __VstlIterCount = ((IData)(1U) + __VstlIterCount);
        __VstlContinue = 0U;
        if (Vtb_e203_nice___024root___eval_phase__stl(vlSelf)) {
            __VstlContinue = 1U;
        }
        vlSelfRef.__VstlFirstIteration = 0U;
    }
}

#ifdef VL_DEBUG
VL_ATTR_COLD void Vtb_e203_nice___024root___dump_triggers__stl(Vtb_e203_nice___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vtb_e203_nice__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_e203_nice___024root___dump_triggers__stl\n"); );
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

VL_ATTR_COLD void Vtb_e203_nice___024root___stl_sequent__TOP__0(Vtb_e203_nice___024root* vlSelf);

VL_ATTR_COLD void Vtb_e203_nice___024root___eval_stl(Vtb_e203_nice___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vtb_e203_nice__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_e203_nice___024root___eval_stl\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    if ((1ULL & vlSelfRef.__VstlTriggered.word(0U))) {
        Vtb_e203_nice___024root___stl_sequent__TOP__0(vlSelf);
        vlSelfRef.__Vm_traceActivity[2U] = 1U;
        vlSelfRef.__Vm_traceActivity[1U] = 1U;
        vlSelfRef.__Vm_traceActivity[0U] = 1U;
    }
}

VL_ATTR_COLD void Vtb_e203_nice___024root___eval_triggers__stl(Vtb_e203_nice___024root* vlSelf);

VL_ATTR_COLD bool Vtb_e203_nice___024root___eval_phase__stl(Vtb_e203_nice___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vtb_e203_nice__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_e203_nice___024root___eval_phase__stl\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Init
    CData/*0:0*/ __VstlExecute;
    // Body
    Vtb_e203_nice___024root___eval_triggers__stl(vlSelf);
    __VstlExecute = vlSelfRef.__VstlTriggered.any();
    if (__VstlExecute) {
        Vtb_e203_nice___024root___eval_stl(vlSelf);
    }
    return (__VstlExecute);
}

#ifdef VL_DEBUG
VL_ATTR_COLD void Vtb_e203_nice___024root___dump_triggers__act(Vtb_e203_nice___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vtb_e203_nice__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_e203_nice___024root___dump_triggers__act\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    if ((1U & (~ vlSelfRef.__VactTriggered.any()))) {
        VL_DBG_MSGF("         No triggers active\n");
    }
    if ((1ULL & vlSelfRef.__VactTriggered.word(0U))) {
        VL_DBG_MSGF("         'act' region trigger index 0 is active: @(posedge tb_e203_nice.clk or negedge tb_e203_nice.rst_n)\n");
    }
    if ((2ULL & vlSelfRef.__VactTriggered.word(0U))) {
        VL_DBG_MSGF("         'act' region trigger index 1 is active: @([true] __VdlySched.awaitingCurrentTime())\n");
    }
    if ((4ULL & vlSelfRef.__VactTriggered.word(0U))) {
        VL_DBG_MSGF("         'act' region trigger index 2 is active: @(posedge tb_e203_nice.clk)\n");
    }
    if ((8ULL & vlSelfRef.__VactTriggered.word(0U))) {
        VL_DBG_MSGF("         'act' region trigger index 3 is active: @([event] tb_e203_nice.nice_if_inst.cb)\n");
    }
    if ((0x10ULL & vlSelfRef.__VactTriggered.word(0U))) {
        VL_DBG_MSGF("         'act' region trigger index 4 is active: @([changed] (tb_e203_nice.u_nice_core.u_decode_dispatch.is_csr_inst ? tb_e203_nice.u_nice_core.csr_ready : (2'h0 == tb_e203_nice.u_nice_core.u_mma_top.state)))\n");
    }
    if ((0x20ULL & vlSelfRef.__VactTriggered.word(0U))) {
        VL_DBG_MSGF("         'act' region trigger index 5 is active: @([changed] (tb_e203_nice.u_nice_core.u_wbu.csr_buf_rd_valid | tb_e203_nice.u_nice_core.u_wbu.mma_buf_rd_valid))\n");
    }
}
#endif  // VL_DEBUG

#ifdef VL_DEBUG
VL_ATTR_COLD void Vtb_e203_nice___024root___dump_triggers__react(Vtb_e203_nice___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vtb_e203_nice__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_e203_nice___024root___dump_triggers__react\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    if ((1U & (~ vlSelfRef.__VreactTriggered.any()))) {
        VL_DBG_MSGF("         No triggers active\n");
    }
    if ((1ULL & vlSelfRef.__VreactTriggered.word(0U))) {
        VL_DBG_MSGF("         'react' region trigger index 0 is active: @(posedge tb_e203_nice.clk or negedge tb_e203_nice.rst_n)\n");
    }
    if ((2ULL & vlSelfRef.__VreactTriggered.word(0U))) {
        VL_DBG_MSGF("         'react' region trigger index 1 is active: @([true] __VdlySched.awaitingCurrentTime())\n");
    }
    if ((4ULL & vlSelfRef.__VreactTriggered.word(0U))) {
        VL_DBG_MSGF("         'react' region trigger index 2 is active: @(posedge tb_e203_nice.clk)\n");
    }
    if ((8ULL & vlSelfRef.__VreactTriggered.word(0U))) {
        VL_DBG_MSGF("         'react' region trigger index 3 is active: @([event] tb_e203_nice.nice_if_inst.cb)\n");
    }
    if ((0x10ULL & vlSelfRef.__VreactTriggered.word(0U))) {
        VL_DBG_MSGF("         'react' region trigger index 4 is active: @([changed] (tb_e203_nice.u_nice_core.u_decode_dispatch.is_csr_inst ? tb_e203_nice.u_nice_core.csr_ready : (2'h0 == tb_e203_nice.u_nice_core.u_mma_top.state)))\n");
    }
    if ((0x20ULL & vlSelfRef.__VreactTriggered.word(0U))) {
        VL_DBG_MSGF("         'react' region trigger index 5 is active: @([changed] (tb_e203_nice.u_nice_core.u_wbu.csr_buf_rd_valid | tb_e203_nice.u_nice_core.u_wbu.mma_buf_rd_valid))\n");
    }
}
#endif  // VL_DEBUG

#ifdef VL_DEBUG
VL_ATTR_COLD void Vtb_e203_nice___024root___dump_triggers__obs(Vtb_e203_nice___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vtb_e203_nice__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_e203_nice___024root___dump_triggers__obs\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    if ((1U & (~ vlSelfRef.__VobsTriggered.any()))) {
        VL_DBG_MSGF("         No triggers active\n");
    }
    if ((1ULL & vlSelfRef.__VobsTriggered.word(0U))) {
        VL_DBG_MSGF("         'obs' region trigger index 0 is active: @(posedge tb_e203_nice.clk or negedge tb_e203_nice.rst_n)\n");
    }
    if ((2ULL & vlSelfRef.__VobsTriggered.word(0U))) {
        VL_DBG_MSGF("         'obs' region trigger index 1 is active: @([true] __VdlySched.awaitingCurrentTime())\n");
    }
    if ((4ULL & vlSelfRef.__VobsTriggered.word(0U))) {
        VL_DBG_MSGF("         'obs' region trigger index 2 is active: @(posedge tb_e203_nice.clk)\n");
    }
    if ((8ULL & vlSelfRef.__VobsTriggered.word(0U))) {
        VL_DBG_MSGF("         'obs' region trigger index 3 is active: @([event] tb_e203_nice.nice_if_inst.cb)\n");
    }
    if ((0x10ULL & vlSelfRef.__VobsTriggered.word(0U))) {
        VL_DBG_MSGF("         'obs' region trigger index 4 is active: @([changed] (tb_e203_nice.u_nice_core.u_decode_dispatch.is_csr_inst ? tb_e203_nice.u_nice_core.csr_ready : (2'h0 == tb_e203_nice.u_nice_core.u_mma_top.state)))\n");
    }
    if ((0x20ULL & vlSelfRef.__VobsTriggered.word(0U))) {
        VL_DBG_MSGF("         'obs' region trigger index 5 is active: @([changed] (tb_e203_nice.u_nice_core.u_wbu.csr_buf_rd_valid | tb_e203_nice.u_nice_core.u_wbu.mma_buf_rd_valid))\n");
    }
}
#endif  // VL_DEBUG

#ifdef VL_DEBUG
VL_ATTR_COLD void Vtb_e203_nice___024root___dump_triggers__nba(Vtb_e203_nice___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vtb_e203_nice__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_e203_nice___024root___dump_triggers__nba\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    if ((1U & (~ vlSelfRef.__VnbaTriggered.any()))) {
        VL_DBG_MSGF("         No triggers active\n");
    }
    if ((1ULL & vlSelfRef.__VnbaTriggered.word(0U))) {
        VL_DBG_MSGF("         'nba' region trigger index 0 is active: @(posedge tb_e203_nice.clk or negedge tb_e203_nice.rst_n)\n");
    }
    if ((2ULL & vlSelfRef.__VnbaTriggered.word(0U))) {
        VL_DBG_MSGF("         'nba' region trigger index 1 is active: @([true] __VdlySched.awaitingCurrentTime())\n");
    }
    if ((4ULL & vlSelfRef.__VnbaTriggered.word(0U))) {
        VL_DBG_MSGF("         'nba' region trigger index 2 is active: @(posedge tb_e203_nice.clk)\n");
    }
    if ((8ULL & vlSelfRef.__VnbaTriggered.word(0U))) {
        VL_DBG_MSGF("         'nba' region trigger index 3 is active: @([event] tb_e203_nice.nice_if_inst.cb)\n");
    }
    if ((0x10ULL & vlSelfRef.__VnbaTriggered.word(0U))) {
        VL_DBG_MSGF("         'nba' region trigger index 4 is active: @([changed] (tb_e203_nice.u_nice_core.u_decode_dispatch.is_csr_inst ? tb_e203_nice.u_nice_core.csr_ready : (2'h0 == tb_e203_nice.u_nice_core.u_mma_top.state)))\n");
    }
    if ((0x20ULL & vlSelfRef.__VnbaTriggered.word(0U))) {
        VL_DBG_MSGF("         'nba' region trigger index 5 is active: @([changed] (tb_e203_nice.u_nice_core.u_wbu.csr_buf_rd_valid | tb_e203_nice.u_nice_core.u_wbu.mma_buf_rd_valid))\n");
    }
}
#endif  // VL_DEBUG

VL_ATTR_COLD void Vtb_e203_nice___024root___ctor_var_reset(Vtb_e203_nice___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vtb_e203_nice__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_e203_nice___024root___ctor_var_reset\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    vlSelf->tb_e203_nice__DOT__clk = VL_RAND_RESET_I(1);
    vlSelf->tb_e203_nice__DOT__rst_n = VL_RAND_RESET_I(1);
    vlSelf->tb_e203_nice__DOT____Vcellout__u_nice_core__nice_icb_cmd_valid = VL_RAND_RESET_I(1);
    vlSelf->tb_e203_nice__DOT__send_csr_read__Vstatic__read_value = VL_RAND_RESET_I(32);
    vlSelf->tb_e203_nice__DOT__test_response_backpressure__Vstatic__read_value = VL_RAND_RESET_I(32);
    vlSelf->tb_e203_nice__DOT__test_request_backpressure__Vstatic__read_value = VL_RAND_RESET_I(32);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__calc_start = VL_RAND_RESET_I(1);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__cfg_16bits_ia = VL_RAND_RESET_I(1);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__use_per_channel = VL_RAND_RESET_I(1);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__dst_base = VL_RAND_RESET_I(32);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__csr_wdata = VL_RAND_RESET_I(32);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__csr_req = VL_RAND_RESET_I(1);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__is_csr_read = VL_RAND_RESET_I(1);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__csr_addr = VL_RAND_RESET_I(12);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__csr_ready = VL_RAND_RESET_I(1);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__csr_rdata = VL_RAND_RESET_I(32);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__mma_wb_valid = VL_RAND_RESET_I(1);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__mma_wb_ready = VL_RAND_RESET_I(1);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__csr_wb_data = VL_RAND_RESET_I(32);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__retire_mem_holdup = VL_RAND_RESET_I(1);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_decode_dispatch__DOT__is_mat_mult_t = VL_RAND_RESET_I(1);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_decode_dispatch__DOT__is_csr_wr = VL_RAND_RESET_I(1);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_decode_dispatch__DOT__is_csr_rd = VL_RAND_RESET_I(1);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_decode_dispatch__DOT__is_csr_inst = VL_RAND_RESET_I(1);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_decode_dispatch__DOT__inst_handshake = VL_RAND_RESET_I(1);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_mma_top__DOT__state = VL_RAND_RESET_I(2);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_mma_top__DOT__cycle_cnt = VL_RAND_RESET_I(8);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_ren = VL_RAND_RESET_I(1);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_wptr = VL_RAND_RESET_I(5);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_rptr = VL_RAND_RESET_I(5);
    for (int __Vi0 = 0; __Vi0 < 16; ++__Vi0) {
        vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_mem[__Vi0] = VL_RAND_RESET_Q(37);
    }
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__burst_cycle_1start = VL_RAND_RESET_I(5);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_burst_cnt = VL_RAND_RESET_I(5);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__burst_cnt_nxt = VL_RAND_RESET_I(5);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__fifo_is_read = VL_RAND_RESET_I(1);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__fifo_addr = VL_RAND_RESET_I(32);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__fifo_len = VL_RAND_RESET_I(4);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_is_read = VL_RAND_RESET_I(1);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_addr = VL_RAND_RESET_I(32);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_len_0start = VL_RAND_RESET_I(4);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rsp_burst_cnt = VL_RAND_RESET_I(5);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rsp_burst_cnt_nxt = VL_RAND_RESET_I(5);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__wdata_buf = VL_RAND_RESET_I(32);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__wmask_buf = VL_RAND_RESET_I(4);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__wdata_buf_valid = VL_RAND_RESET_I(1);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__wdata_aligned = VL_RAND_RESET_I(32);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__wmask_aligned = VL_RAND_RESET_I(4);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rdata_buf = VL_RAND_RESET_I(32);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rdata_buf_valid = VL_RAND_RESET_I(1);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rdata_aligned = VL_RAND_RESET_I(32);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_state = VL_RAND_RESET_I(2);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_state_nxt = VL_RAND_RESET_I(2);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rsp_state = VL_RAND_RESET_I(2);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rsp_state_nxt = VL_RAND_RESET_I(2);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fire = VL_RAND_RESET_I(1);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__is_last_burst = VL_RAND_RESET_I(1);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rd_last_burst = VL_RAND_RESET_I(1);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__last_beat_sent = VL_RAND_RESET_I(1);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_is_read_comb = VL_RAND_RESET_I(1);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_addr_comb = VL_RAND_RESET_I(32);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__sa_rsp_ready_comb = VL_RAND_RESET_I(1);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT____VdfgRegularize_hc6488b08_0_5 = VL_RAND_RESET_I(1);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_lhs_base = VL_RAND_RESET_I(32);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_rhs_base = VL_RAND_RESET_I(32);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_dst_base = VL_RAND_RESET_I(32);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_bias_base = VL_RAND_RESET_I(32);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_k = VL_RAND_RESET_I(32);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_n = VL_RAND_RESET_I(32);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_m = VL_RAND_RESET_I(32);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_dst_row_stride_b = VL_RAND_RESET_I(32);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_lhs_row_stride_b = VL_RAND_RESET_I(32);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_rhs_row_stride_b = VL_RAND_RESET_I(32);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_lhs_zp = VL_RAND_RESET_I(32);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_rhs_zp = VL_RAND_RESET_I(32);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_dst_zp = VL_RAND_RESET_I(32);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_q_mult_pt = VL_RAND_RESET_I(32);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_q_shift_pt = VL_RAND_RESET_I(32);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_act_min = VL_RAND_RESET_I(32);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_act_max = VL_RAND_RESET_I(32);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__csr_buf_rd_valid = VL_RAND_RESET_I(1);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__mma_buf_rd_valid = VL_RAND_RESET_I(1);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__wb_data_ping = VL_RAND_RESET_I(32);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__wb_data_pong = VL_RAND_RESET_I(32);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__ping_full = VL_RAND_RESET_I(1);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__pong_full = VL_RAND_RESET_I(1);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__wr_sel = VL_RAND_RESET_I(1);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__rd_sel = VL_RAND_RESET_I(1);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__wr_hsked = VL_RAND_RESET_I(1);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__rd_hsked = VL_RAND_RESET_I(1);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__wb_data_ping = VL_RAND_RESET_I(32);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__wb_data_pong = VL_RAND_RESET_I(32);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__ping_full = VL_RAND_RESET_I(1);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__pong_full = VL_RAND_RESET_I(1);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__wr_sel = VL_RAND_RESET_I(1);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__rd_sel = VL_RAND_RESET_I(1);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__rd_hsked = VL_RAND_RESET_I(1);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_inst_tracker__DOT__state = VL_RAND_RESET_I(1);
    vlSelf->tb_e203_nice__DOT__u_nice_core__DOT__u_inst_tracker__DOT__wb_handshake = VL_RAND_RESET_I(1);
    vlSelf->__VdlyVal__tb_e203_nice__DOT__clk__v0 = VL_RAND_RESET_I(1);
    vlSelf->__VdlySet__tb_e203_nice__DOT__clk__v0 = 0;
    vlSelf->__Vtrigprevexpr___TOP__tb_e203_nice__DOT__clk__0 = VL_RAND_RESET_I(1);
    vlSelf->__Vtrigprevexpr___TOP__tb_e203_nice__DOT__rst_n__0 = VL_RAND_RESET_I(1);
    vlSelf->__Vtrigprevexpr_haaedec92__0 = VL_RAND_RESET_I(1);
    vlSelf->__Vtrigprevexpr_h57ac893f__0 = VL_RAND_RESET_I(1);
    vlSelf->__VactDidInit = 0;
    for (int __Vi0 = 0; __Vi0 < 3; ++__Vi0) {
        vlSelf->__Vm_traceActivity[__Vi0] = 0;
    }
}
