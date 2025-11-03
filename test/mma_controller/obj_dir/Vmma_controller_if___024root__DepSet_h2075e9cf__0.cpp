// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Design implementation internals
// See Vmma_controller_if.h for the primary calling header

#include "Vmma_controller_if__pch.h"
#include "Vmma_controller_if__Syms.h"
#include "Vmma_controller_if___024root.h"

VL_ATTR_COLD void Vmma_controller_if___024root___eval_initial__TOP(Vmma_controller_if___024root* vlSelf);
VlCoroutine Vmma_controller_if___024root___eval_initial__TOP__Vtiming__0(Vmma_controller_if___024root* vlSelf);
VlCoroutine Vmma_controller_if___024root___eval_initial__TOP__Vtiming__1(Vmma_controller_if___024root* vlSelf);
VlCoroutine Vmma_controller_if___024root___eval_initial__TOP__Vtiming__2(Vmma_controller_if___024root* vlSelf);

void Vmma_controller_if___024root___eval_initial(Vmma_controller_if___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vmma_controller_if___024root___eval_initial\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    Vmma_controller_if___024root___eval_initial__TOP(vlSelf);
    Vmma_controller_if___024root___eval_initial__TOP__Vtiming__0(vlSelf);
    Vmma_controller_if___024root___eval_initial__TOP__Vtiming__1(vlSelf);
    Vmma_controller_if___024root___eval_initial__TOP__Vtiming__2(vlSelf);
    vlSelfRef.__Vtrigprevexpr___TOP__tb_mma_controller__DOT__clk__0 
        = vlSelfRef.tb_mma_controller__DOT__clk;
    vlSelfRef.__Vtrigprevexpr___TOP__tb_mma_controller__DOT__rst_n__0 
        = vlSelfRef.tb_mma_controller__DOT__rst_n;
    vlSelfRef.__Vtrigprevexpr_he004758a__0 = ((IData)(vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__init_cfg_ia) 
                                              & (IData)(vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__init_cfg_weight));
    vlSelfRef.__Vtrigprevexpr___TOP__tb_mma_controller__DOT____Vcellout__dut__load_weight_granted__0 
        = vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__load_weight_granted;
    vlSelfRef.__Vtrigprevexpr___TOP__tb_mma_controller__DOT____Vcellout__dut__send_weight_trigger__0 
        = vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__send_weight_trigger;
    vlSelfRef.__Vtrigprevexpr___TOP__tb_mma_controller__DOT____Vcellout__dut__load_ia_granted__0 
        = vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__load_ia_granted;
    vlSelfRef.__Vtrigprevexpr___TOP__tb_mma_controller__DOT____Vcellout__dut__send_ia_trigger__0 
        = vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__send_ia_trigger;
    vlSelfRef.__Vtrigprevexpr___TOP__tb_mma_controller__DOT____Vcellout__dut__load_bias_granted__0 
        = vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__load_bias_granted;
    vlSelfRef.__Vtrigprevexpr___TOP__tb_mma_controller__DOT__comp_if__tile_calc_over__0 
        = vlSymsp->TOP__tb_mma_controller__DOT__comp_if.tile_calc_over;
    vlSelfRef.__Vtrigprevexpr___TOP__tb_mma_controller__DOT____Vcellout__dut__load_quant_granted__0 
        = vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__load_quant_granted;
    vlSelfRef.__Vtrigprevexpr___TOP__tb_mma_controller__DOT____Vcellout__dut__write_oa_granted__0 
        = vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__write_oa_granted;
    vlSelfRef.__Vtrigprevexpr___TOP__tb_mma_controller__DOT__ia_if__ia_sending_done__0 
        = vlSymsp->TOP__tb_mma_controller__DOT__ia_if.ia_sending_done;
    vlSelfRef.__Vtrigprevexpr___TOP__tb_mma_controller__DOT__oa_if__oa_calc_over__0 
        = vlSymsp->TOP__tb_mma_controller__DOT__oa_if.oa_calc_over;
    vlSelfRef.__Vtrigprevexpr_hbb0eeb4f__0 = (0U == (IData)(vlSelfRef.tb_mma_controller__DOT__dut__DOT__current_state));
}

VlCoroutine Vmma_controller_if___024root___eval_initial__TOP__Vtiming__1____Vfork_1__0(Vmma_controller_if___024root* vlSelf);
VlCoroutine Vmma_controller_if___024root___eval_initial__TOP__Vtiming__1____Vfork_1__1(Vmma_controller_if___024root* vlSelf);
VlCoroutine Vmma_controller_if___024root___eval_initial__TOP__Vtiming__1____Vfork_1__2(Vmma_controller_if___024root* vlSelf);
VlCoroutine Vmma_controller_if___024root___eval_initial__TOP__Vtiming__1____Vfork_1__3(Vmma_controller_if___024root* vlSelf);
VlCoroutine Vmma_controller_if___024root___eval_initial__TOP__Vtiming__1____Vfork_1__4(Vmma_controller_if___024root* vlSelf);
VlCoroutine Vmma_controller_if___024root___eval_initial__TOP__Vtiming__1____Vfork_1__5(Vmma_controller_if___024root* vlSelf);

VL_INLINE_OPT VlCoroutine Vmma_controller_if___024root___eval_initial__TOP__Vtiming__1(Vmma_controller_if___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vmma_controller_if___024root___eval_initial__TOP__Vtiming__1\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Init
    CData/*0:0*/ __Vtask_tb_mma_controller__DOT__simulate_block_computation__0__cfg16;
    __Vtask_tb_mma_controller__DOT__simulate_block_computation__0__cfg16 = 0;
    // Body
    vlSelfRef.tb_mma_controller__DOT__rst_n = 0U;
    co_await vlSelfRef.__VtrigSched_hdac58424__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_mma_controller.clk)", 
                                                         "tb_mma_controller.sv", 
                                                         112);
    co_await vlSelfRef.__VtrigSched_h42ebdd83__0.trigger(0U, 
                                                         nullptr, 
                                                         "@([event] tb_mma_controller.ctrl_if.cb)", 
                                                         "tb_mma_controller.sv", 
                                                         113);
    vlSymsp->TOP__tb_mma_controller__DOT__ctrl_if.cb__DOT__calc_start = 0U;
    vlSymsp->TOP__tb_mma_controller__DOT__ctrl_if.cb__DOT__cfg_16bits_ia = 0U;
    vlSymsp->TOP__tb_mma_controller__DOT__ctrl_if.cb__DOT__fifo_full_flag = 0U;
    co_await vlSelfRef.__VtrigSched_h38e6f19c__0.trigger(0U, 
                                                         nullptr, 
                                                         "@([event] tb_mma_controller.comp_if.cb)", 
                                                         "tb_mma_controller.sv", 
                                                         118);
    vlSymsp->TOP__tb_mma_controller__DOT__comp_if.cb__DOT__partial_sum_calc_over = 0U;
    vlSymsp->TOP__tb_mma_controller__DOT__comp_if.cb__DOT__tile_calc_over = 0U;
    co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                         nullptr, 
                                                         "@([event] tb_mma_controller.ia_if.cb)", 
                                                         "tb_mma_controller.sv", 
                                                         122);
    vlSymsp->TOP__tb_mma_controller__DOT__ia_if.cb__DOT__load_ia_req = 0U;
    vlSymsp->TOP__tb_mma_controller__DOT__ia_if.cb__DOT__ia_sending_done = 0U;
    vlSymsp->TOP__tb_mma_controller__DOT__ia_if.cb__DOT__ia_calc_done = 0U;
    vlSymsp->TOP__tb_mma_controller__DOT__ia_if.cb__DOT__ia_data_valid = 0U;
    co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                         nullptr, 
                                                         "@([event] tb_mma_controller.weight_if.cb)", 
                                                         "tb_mma_controller.sv", 
                                                         128);
    vlSymsp->TOP__tb_mma_controller__DOT__weight_if.cb__DOT__load_weight_req = 0U;
    vlSymsp->TOP__tb_mma_controller__DOT__weight_if.cb__DOT__weight_sending_done = 0U;
    vlSymsp->TOP__tb_mma_controller__DOT__weight_if.cb__DOT__weight_data_valid = 0U;
    co_await vlSelfRef.__VtrigSched_h4c63e026__0.trigger(0U, 
                                                         nullptr, 
                                                         "@([event] tb_mma_controller.bias_if.cb)", 
                                                         "tb_mma_controller.sv", 
                                                         133);
    vlSymsp->TOP__tb_mma_controller__DOT__bias_if.cb__DOT__load_bias_req = 0U;
    vlSymsp->TOP__tb_mma_controller__DOT__bias_if.cb__DOT__bias_valid = 0U;
    co_await vlSelfRef.__VtrigSched_h66f97190__0.trigger(0U, 
                                                         nullptr, 
                                                         "@([event] tb_mma_controller.quant_if.cb)", 
                                                         "tb_mma_controller.sv", 
                                                         137);
    vlSymsp->TOP__tb_mma_controller__DOT__quant_if.cb__DOT__load_quant_req = 0U;
    vlSymsp->TOP__tb_mma_controller__DOT__quant_if.cb__DOT__quant_params_valid = 0U;
    co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                         nullptr, 
                                                         "@([event] tb_mma_controller.oa_if.cb)", 
                                                         "tb_mma_controller.sv", 
                                                         141);
    vlSymsp->TOP__tb_mma_controller__DOT__oa_if.cb__DOT__write_oa_req = 0U;
    vlSymsp->TOP__tb_mma_controller__DOT__oa_if.cb__DOT__write_done = 0U;
    vlSymsp->TOP__tb_mma_controller__DOT__oa_if.cb__DOT__oa_calc_over = 0U;
    co_await vlSelfRef.__VtrigSched_hdac58424__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_mma_controller.clk)", 
                                                         "tb_mma_controller.sv", 
                                                         147);
    co_await vlSelfRef.__VtrigSched_hdac58424__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_mma_controller.clk)", 
                                                         "tb_mma_controller.sv", 
                                                         147);
    co_await vlSelfRef.__VtrigSched_hdac58424__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_mma_controller.clk)", 
                                                         "tb_mma_controller.sv", 
                                                         147);
    co_await vlSelfRef.__VtrigSched_hdac58424__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_mma_controller.clk)", 
                                                         "tb_mma_controller.sv", 
                                                         147);
    co_await vlSelfRef.__VtrigSched_hdac58424__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_mma_controller.clk)", 
                                                         "tb_mma_controller.sv", 
                                                         147);
    vlSelfRef.tb_mma_controller__DOT__rst_n = 1U;
    co_await vlSelfRef.__VtrigSched_hdac58424__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_mma_controller.clk)", 
                                                         "tb_mma_controller.sv", 
                                                         149);
    co_await vlSelfRef.__VtrigSched_hdac58424__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_mma_controller.clk)", 
                                                         "tb_mma_controller.sv", 
                                                         149);
    VL_WRITEF_NX("\033[1;37m========== Test Start ==========\033[0m\n\n\033[1;36m[Test 1] Basic computation flow (8-bit mode) - task\033[0m\n",0);
    __Vtask_tb_mma_controller__DOT__simulate_block_computation__0__cfg16 = 0U;
    VL_WRITEF_NX("\n\033[1;34m  === Starting block computation (cfg16=%0b) ===\033[0m\n",0,
                 1,__Vtask_tb_mma_controller__DOT__simulate_block_computation__0__cfg16);
    co_await vlSelfRef.__VtrigSched_h42ebdd83__0.trigger(0U, 
                                                         nullptr, 
                                                         "@([event] tb_mma_controller.ctrl_if.cb)", 
                                                         "test_compute_tasks.svh", 
                                                         298);
    vlSymsp->TOP__tb_mma_controller__DOT__ctrl_if.cb__DOT__cfg_16bits_ia 
        = __Vtask_tb_mma_controller__DOT__simulate_block_computation__0__cfg16;
    vlSymsp->TOP__tb_mma_controller__DOT__ctrl_if.cb__DOT__calc_start = 1U;
    co_await vlSelfRef.__VtrigSched_h42ebdd83__0.trigger(0U, 
                                                         nullptr, 
                                                         "@([event] tb_mma_controller.ctrl_if.cb)", 
                                                         "test_compute_tasks.svh", 
                                                         301);
    co_await vlSelfRef.__VtrigSched_hdac58424__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_mma_controller.clk)", 
                                                         "test_compute_tasks.svh", 
                                                         302);
    vlSymsp->TOP__tb_mma_controller__DOT__ctrl_if.cb__DOT__calc_start = 0U;
    while ((1U & (~ ((IData)(vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__init_cfg_ia) 
                     & (IData)(vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__init_cfg_weight))))) {
        co_await vlSelfRef.__VtrigSched_h47b3a967__0.trigger(1U, 
                                                             nullptr, 
                                                             "@([changed] (tb_mma_controller.__Vcellout__dut__init_cfg_ia & tb_mma_controller.__Vcellout__dut__init_cfg_weight))", 
                                                             "test_compute_tasks.svh", 
                                                             306);
    }
    VL_WRITEF_NX("\033[34m  [%0t] Initialization completed (cfg16=%0b)\033[0m\n",0,
                 64,VL_TIME_UNITED_Q(1000),-9,1,(IData)(__Vtask_tb_mma_controller__DOT__simulate_block_computation__0__cfg16));
    vlSelfRef.__Vfork_1__sync.init(6U, nullptr);
    Vmma_controller_if___024root___eval_initial__TOP__Vtiming__1____Vfork_1__0(vlSelf);
    Vmma_controller_if___024root___eval_initial__TOP__Vtiming__1____Vfork_1__1(vlSelf);
    Vmma_controller_if___024root___eval_initial__TOP__Vtiming__1____Vfork_1__2(vlSelf);
    Vmma_controller_if___024root___eval_initial__TOP__Vtiming__1____Vfork_1__3(vlSelf);
    Vmma_controller_if___024root___eval_initial__TOP__Vtiming__1____Vfork_1__4(vlSelf);
    Vmma_controller_if___024root___eval_initial__TOP__Vtiming__1____Vfork_1__5(vlSelf);
    co_await vlSelfRef.__Vfork_1__sync.join(nullptr, 
                                            "test_compute_tasks.svh", 
                                            311);
    VL_WRITEF_NX("\033[34m  [%0t] All simulation tasks completed, waiting for oa_calc_over\033[0m\n",0,
                 64,VL_TIME_UNITED_Q(1000),-9);
    while ((1U & (~ (IData)(vlSymsp->TOP__tb_mma_controller__DOT__oa_if.oa_calc_over)))) {
        co_await vlSelfRef.__VtrigSched_hcbbc710c__0.trigger(1U, 
                                                             nullptr, 
                                                             "@([changed] tb_mma_controller.oa_if.oa_calc_over)", 
                                                             "test_compute_tasks.svh", 
                                                             323);
    }
    VL_WRITEF_NX("\033[34m  [%0t] OA calculation done (detected oa_calc_over)\033[0m\n",0,
                 64,VL_TIME_UNITED_Q(1000),-9);
    while ((0U != (IData)(vlSelfRef.tb_mma_controller__DOT__dut__DOT__current_state))) {
        co_await vlSelfRef.__VtrigSched_h2ab923a2__0.trigger(1U, 
                                                             nullptr, 
                                                             "@([changed] (4'h0 == tb_mma_controller.dut.current_state))", 
                                                             "test_compute_tasks.svh", 
                                                             328);
    }
    VL_WRITEF_NX("\033[34m  [%0t] Controller ready after block computation (cfg16=%0b)\033[0m\n\033[1;34m  === Block computation completed (cfg16=%0b) ===\033[0m\n\n",0,
                 64,VL_TIME_UNITED_Q(1000),-9,1,(IData)(__Vtask_tb_mma_controller__DOT__simulate_block_computation__0__cfg16),
                 1,__Vtask_tb_mma_controller__DOT__simulate_block_computation__0__cfg16);
    co_await vlSelfRef.__VtrigSched_hdac58424__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_mma_controller.clk)", 
                                                         "tb_mma_controller.sv", 
                                                         166);
    co_await vlSelfRef.__VtrigSched_hdac58424__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_mma_controller.clk)", 
                                                         "tb_mma_controller.sv", 
                                                         166);
    co_await vlSelfRef.__VtrigSched_hdac58424__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_mma_controller.clk)", 
                                                         "tb_mma_controller.sv", 
                                                         166);
    co_await vlSelfRef.__VtrigSched_hdac58424__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_mma_controller.clk)", 
                                                         "tb_mma_controller.sv", 
                                                         166);
    co_await vlSelfRef.__VtrigSched_hdac58424__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_mma_controller.clk)", 
                                                         "tb_mma_controller.sv", 
                                                         166);
    co_await vlSelfRef.__VtrigSched_hdac58424__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_mma_controller.clk)", 
                                                         "tb_mma_controller.sv", 
                                                         166);
    co_await vlSelfRef.__VtrigSched_hdac58424__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_mma_controller.clk)", 
                                                         "tb_mma_controller.sv", 
                                                         166);
    co_await vlSelfRef.__VtrigSched_hdac58424__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_mma_controller.clk)", 
                                                         "tb_mma_controller.sv", 
                                                         166);
    co_await vlSelfRef.__VtrigSched_hdac58424__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_mma_controller.clk)", 
                                                         "tb_mma_controller.sv", 
                                                         166);
    co_await vlSelfRef.__VtrigSched_hdac58424__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_mma_controller.clk)", 
                                                         "tb_mma_controller.sv", 
                                                         166);
    co_await vlSelfRef.__VtrigSched_hdac58424__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_mma_controller.clk)", 
                                                         "tb_mma_controller.sv", 
                                                         166);
    co_await vlSelfRef.__VtrigSched_hdac58424__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_mma_controller.clk)", 
                                                         "tb_mma_controller.sv", 
                                                         166);
    co_await vlSelfRef.__VtrigSched_hdac58424__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_mma_controller.clk)", 
                                                         "tb_mma_controller.sv", 
                                                         166);
    co_await vlSelfRef.__VtrigSched_hdac58424__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_mma_controller.clk)", 
                                                         "tb_mma_controller.sv", 
                                                         166);
    co_await vlSelfRef.__VtrigSched_hdac58424__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_mma_controller.clk)", 
                                                         "tb_mma_controller.sv", 
                                                         166);
    co_await vlSelfRef.__VtrigSched_hdac58424__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_mma_controller.clk)", 
                                                         "tb_mma_controller.sv", 
                                                         166);
    co_await vlSelfRef.__VtrigSched_hdac58424__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_mma_controller.clk)", 
                                                         "tb_mma_controller.sv", 
                                                         166);
    co_await vlSelfRef.__VtrigSched_hdac58424__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_mma_controller.clk)", 
                                                         "tb_mma_controller.sv", 
                                                         166);
    co_await vlSelfRef.__VtrigSched_hdac58424__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_mma_controller.clk)", 
                                                         "tb_mma_controller.sv", 
                                                         166);
    co_await vlSelfRef.__VtrigSched_hdac58424__0.trigger(0U, 
                                                         nullptr, 
                                                         "@(posedge tb_mma_controller.clk)", 
                                                         "tb_mma_controller.sv", 
                                                         166);
    VL_WRITEF_NX("\n\033[1;37m========== Test Completed ==========\033[0m\n\n\033[32m==========  Test  Passed  ==========\033[0m\n\033[32m       ***   ***   ****   ****      \033[0m\n\033[32m      *   * *   * *      *          \033[0m\n\033[32m      ****  *****  ****   ****      \033[0m\n\033[32m      *     *   *     *      *      \033[0m\n\033[32m      *     *   * ****   ****       \033[0m\n",0);
    VL_FINISH_MT("tb_mma_controller.sv", 175, "");
    co_return;
}

VL_INLINE_OPT VlCoroutine Vmma_controller_if___024root___eval_initial__TOP__Vtiming__1____Vfork_1__5(Vmma_controller_if___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vmma_controller_if___024root___eval_initial__TOP__Vtiming__1____Vfork_1__5\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Init
    IData/*31:0*/ __Vtask_tb_mma_controller__DOT__simulate_compute_core__6__partial_sum_count;
    __Vtask_tb_mma_controller__DOT__simulate_compute_core__6__partial_sum_count = 0;
    IData/*31:0*/ __Vtask_tb_mma_controller__DOT__simulate_compute_core__6__tile_idx;
    __Vtask_tb_mma_controller__DOT__simulate_compute_core__6__tile_idx = 0;
    // Body
    __Vtask_tb_mma_controller__DOT__simulate_compute_core__6__partial_sum_count = 0U;
    __Vtask_tb_mma_controller__DOT__simulate_compute_core__6__tile_idx = 0U;
    VL_WRITEF_NX("\033[1;37m  === Compute core simulator started ===\033[0m\n",0);
    while (VL_GTS_III(32, 0x10U, __Vtask_tb_mma_controller__DOT__simulate_compute_core__6__partial_sum_count)) {
        while ((1U & (~ (IData)(vlSymsp->TOP__tb_mma_controller__DOT__ia_if.ia_sending_done)))) {
            co_await vlSelfRef.__VtrigSched_h4463a28d__0.trigger(1U, 
                                                                 nullptr, 
                                                                 "@([changed] tb_mma_controller.ia_if.ia_sending_done)", 
                                                                 "test_compute_tasks.svh", 
                                                                 258);
        }
        VL_WRITEF_NX("\033[37m  [%0t] Compute: starting partial sum %0d (tile %0d, round %0d/4)\033[0m\n",0,
                     64,VL_TIME_UNITED_Q(1000),-9,32,
                     __Vtask_tb_mma_controller__DOT__simulate_compute_core__6__partial_sum_count,
                     32,__Vtask_tb_mma_controller__DOT__simulate_compute_core__6__tile_idx,
                     32,((IData)(1U) + VL_MODDIVS_III(32, __Vtask_tb_mma_controller__DOT__simulate_compute_core__6__partial_sum_count, (IData)(4U))));
        co_await vlSelfRef.__VtrigSched_h38e6f19c__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.comp_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             265);
        co_await vlSelfRef.__VtrigSched_h38e6f19c__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.comp_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             265);
        co_await vlSelfRef.__VtrigSched_h38e6f19c__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.comp_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             265);
        co_await vlSelfRef.__VtrigSched_h38e6f19c__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.comp_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             265);
        co_await vlSelfRef.__VtrigSched_h38e6f19c__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.comp_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             265);
        co_await vlSelfRef.__VtrigSched_h38e6f19c__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.comp_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             265);
        co_await vlSelfRef.__VtrigSched_h38e6f19c__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.comp_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             265);
        co_await vlSelfRef.__VtrigSched_h38e6f19c__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.comp_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             265);
        co_await vlSelfRef.__VtrigSched_h38e6f19c__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.comp_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             265);
        co_await vlSelfRef.__VtrigSched_h38e6f19c__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.comp_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             265);
        co_await vlSelfRef.__VtrigSched_h38e6f19c__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.comp_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             265);
        co_await vlSelfRef.__VtrigSched_h38e6f19c__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.comp_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             265);
        co_await vlSelfRef.__VtrigSched_h38e6f19c__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.comp_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             265);
        co_await vlSelfRef.__VtrigSched_h38e6f19c__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.comp_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             265);
        co_await vlSelfRef.__VtrigSched_h38e6f19c__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.comp_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             265);
        co_await vlSelfRef.__VtrigSched_h38e6f19c__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.comp_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             265);
        co_await vlSelfRef.__VtrigSched_h38e6f19c__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.comp_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             265);
        co_await vlSelfRef.__VtrigSched_h38e6f19c__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.comp_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             265);
        co_await vlSelfRef.__VtrigSched_h38e6f19c__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.comp_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             265);
        co_await vlSelfRef.__VtrigSched_h38e6f19c__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.comp_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             265);
        co_await vlSelfRef.__VtrigSched_h38e6f19c__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.comp_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             265);
        co_await vlSelfRef.__VtrigSched_h38e6f19c__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.comp_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             265);
        co_await vlSelfRef.__VtrigSched_h38e6f19c__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.comp_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             265);
        co_await vlSelfRef.__VtrigSched_h38e6f19c__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.comp_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             265);
        co_await vlSelfRef.__VtrigSched_h38e6f19c__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.comp_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             265);
        co_await vlSelfRef.__VtrigSched_h38e6f19c__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.comp_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             265);
        co_await vlSelfRef.__VtrigSched_h38e6f19c__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.comp_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             265);
        co_await vlSelfRef.__VtrigSched_h38e6f19c__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.comp_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             265);
        co_await vlSelfRef.__VtrigSched_h38e6f19c__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.comp_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             265);
        co_await vlSelfRef.__VtrigSched_h38e6f19c__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.comp_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             265);
        co_await vlSelfRef.__VtrigSched_h38e6f19c__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.comp_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             265);
        co_await vlSelfRef.__VtrigSched_h38e6f19c__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.comp_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             265);
        co_await vlSelfRef.__VtrigSched_h38e6f19c__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.comp_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             265);
        co_await vlSelfRef.__VtrigSched_h38e6f19c__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.comp_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             265);
        co_await vlSelfRef.__VtrigSched_h38e6f19c__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.comp_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             265);
        co_await vlSelfRef.__VtrigSched_h38e6f19c__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.comp_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             265);
        co_await vlSelfRef.__VtrigSched_h38e6f19c__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.comp_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             265);
        co_await vlSelfRef.__VtrigSched_h38e6f19c__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.comp_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             265);
        co_await vlSelfRef.__VtrigSched_h38e6f19c__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.comp_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             265);
        co_await vlSelfRef.__VtrigSched_h38e6f19c__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.comp_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             265);
        co_await vlSelfRef.__VtrigSched_h38e6f19c__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.comp_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             265);
        co_await vlSelfRef.__VtrigSched_h38e6f19c__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.comp_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             265);
        co_await vlSelfRef.__VtrigSched_h38e6f19c__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.comp_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             265);
        co_await vlSelfRef.__VtrigSched_h38e6f19c__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.comp_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             265);
        co_await vlSelfRef.__VtrigSched_h38e6f19c__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.comp_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             265);
        co_await vlSelfRef.__VtrigSched_h38e6f19c__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.comp_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             265);
        co_await vlSelfRef.__VtrigSched_h38e6f19c__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.comp_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             265);
        vlSymsp->TOP__tb_mma_controller__DOT__comp_if.cb__DOT__partial_sum_calc_over = 1U;
        VL_WRITEF_NX("\033[37m  [%0t] Compute: partial_sum_calc_over asserted (count=%0d)\033[0m\n",0,
                     64,VL_TIME_UNITED_Q(1000),-9,32,
                     __Vtask_tb_mma_controller__DOT__simulate_compute_core__6__partial_sum_count);
        if (VL_UNLIKELY((3U == VL_MODDIVS_III(32, __Vtask_tb_mma_controller__DOT__simulate_compute_core__6__partial_sum_count, (IData)(4U))))) {
            vlSymsp->TOP__tb_mma_controller__DOT__comp_if.cb__DOT__tile_calc_over = 1U;
            VL_WRITEF_NX("\033[37m  [%0t] Compute: tile_calc_over asserted (tile %0d completed)\033[0m\n",0,
                         64,VL_TIME_UNITED_Q(1000),
                         -9,32,__Vtask_tb_mma_controller__DOT__simulate_compute_core__6__tile_idx);
            __Vtask_tb_mma_controller__DOT__simulate_compute_core__6__tile_idx 
                = ((IData)(1U) + __Vtask_tb_mma_controller__DOT__simulate_compute_core__6__tile_idx);
        }
        co_await vlSelfRef.__VtrigSched_h38e6f19c__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.comp_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             280);
        co_await vlSelfRef.__VtrigSched_hdac58424__0.trigger(0U, 
                                                             nullptr, 
                                                             "@(posedge tb_mma_controller.clk)", 
                                                             "test_compute_tasks.svh", 
                                                             281);
        vlSymsp->TOP__tb_mma_controller__DOT__comp_if.cb__DOT__partial_sum_calc_over = 0U;
        vlSymsp->TOP__tb_mma_controller__DOT__comp_if.cb__DOT__tile_calc_over = 0U;
        __Vtask_tb_mma_controller__DOT__simulate_compute_core__6__partial_sum_count 
            = ((IData)(1U) + __Vtask_tb_mma_controller__DOT__simulate_compute_core__6__partial_sum_count);
    }
    VL_WRITEF_NX("\033[1;37m  === Compute core simulator finished (total=%0d partial sums, %0d tiles) ===\033[0m\n",0,
                 32,__Vtask_tb_mma_controller__DOT__simulate_compute_core__6__partial_sum_count,
                 32,__Vtask_tb_mma_controller__DOT__simulate_compute_core__6__tile_idx);
    vlSelfRef.__Vfork_1__sync.done("test_compute_tasks.svh", 
                                   317);
}

VL_INLINE_OPT VlCoroutine Vmma_controller_if___024root___eval_initial__TOP__Vtiming__1____Vfork_1__4(Vmma_controller_if___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vmma_controller_if___024root___eval_initial__TOP__Vtiming__1____Vfork_1__4\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Init
    IData/*31:0*/ __Vtask_tb_mma_controller__DOT__simulate_oa_writer__5__write_count;
    __Vtask_tb_mma_controller__DOT__simulate_oa_writer__5__write_count = 0;
    // Body
    {
        __Vtask_tb_mma_controller__DOT__simulate_oa_writer__5__write_count = 0U;
        VL_WRITEF_NX("\033[1;34m  === OA writer started ===\033[0m\n",0);
        while (1U) {
            while ((1U & (~ (IData)(vlSymsp->TOP__tb_mma_controller__DOT__comp_if.tile_calc_over)))) {
                co_await vlSelfRef.__VtrigSched_ha535fff4__0.trigger(1U, 
                                                                     nullptr, 
                                                                     "@([changed] tb_mma_controller.comp_if.tile_calc_over)", 
                                                                     "test_compute_tasks.svh", 
                                                                     205);
            }
            VL_WRITEF_NX("\033[35m  [%0t] OA writer: detected tile_calc_over, requesting write (count=%0d)\033[0m\n",0,
                         64,VL_TIME_UNITED_Q(1000),
                         -9,32,__Vtask_tb_mma_controller__DOT__simulate_oa_writer__5__write_count);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 210);
            vlSymsp->TOP__tb_mma_controller__DOT__oa_if.cb__DOT__write_oa_req = 1U;
            while ((1U & (~ (IData)(vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__write_oa_granted)))) {
                co_await vlSelfRef.__VtrigSched_h28ec1f55__0.trigger(1U, 
                                                                     nullptr, 
                                                                     "@([changed] tb_mma_controller.__Vcellout__dut__write_oa_granted)", 
                                                                     "test_compute_tasks.svh", 
                                                                     214);
            }
            VL_WRITEF_NX("\033[35m  [%0t] OA writer: write granted\033[0m\n",0,
                         64,VL_TIME_UNITED_Q(1000),
                         -9);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 218);
            vlSymsp->TOP__tb_mma_controller__DOT__oa_if.cb__DOT__write_oa_req = 0U;
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 222);
            vlSymsp->TOP__tb_mma_controller__DOT__oa_if.cb__DOT__write_done = 1U;
            VL_WRITEF_NX("\033[35m  [%0t] OA writer: write_done asserted\033[0m\n",0,
                         64,VL_TIME_UNITED_Q(1000),
                         -9);
            __Vtask_tb_mma_controller__DOT__simulate_oa_writer__5__write_count 
                = ((IData)(1U) + __Vtask_tb_mma_controller__DOT__simulate_oa_writer__5__write_count);
            if (VL_UNLIKELY((4U == __Vtask_tb_mma_controller__DOT__simulate_oa_writer__5__write_count))) {
                vlSymsp->TOP__tb_mma_controller__DOT__oa_if.cb__DOT__oa_calc_over = 1U;
                VL_WRITEF_NX("\033[1;35m  [%0t] OA writer: all tiles written, oa_calc_over asserted\033[0m\n",0,
                             64,VL_TIME_UNITED_Q(1000),
                             -9);
            }
            co_await vlSelfRef.__VtrigSched_haadd1735__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@([event] tb_mma_controller.oa_if.cb)", 
                                                                 "test_compute_tasks.svh", 
                                                                 236);
            co_await vlSelfRef.__VtrigSched_hdac58424__0.trigger(0U, 
                                                                 nullptr, 
                                                                 "@(posedge tb_mma_controller.clk)", 
                                                                 "test_compute_tasks.svh", 
                                                                 237);
            vlSymsp->TOP__tb_mma_controller__DOT__oa_if.cb__DOT__write_done = 0U;
            if (VL_UNLIKELY((4U == __Vtask_tb_mma_controller__DOT__simulate_oa_writer__5__write_count))) {
                VL_WRITEF_NX("\033[1;34m  === OA writer finished ===\033[0m\n",0);
                vlSymsp->TOP__tb_mma_controller__DOT__oa_if.cb__DOT__oa_calc_over = 0U;
                goto __Vlabel1;
            }
        }
        __Vlabel1: ;
    }
    vlSelfRef.__Vfork_1__sync.done("test_compute_tasks.svh", 
                                   316);
}

VL_INLINE_OPT VlCoroutine Vmma_controller_if___024root___eval_initial__TOP__Vtiming__1____Vfork_1__3(Vmma_controller_if___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vmma_controller_if___024root___eval_initial__TOP__Vtiming__1____Vfork_1__3\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Init
    IData/*31:0*/ __Vtask_tb_mma_controller__DOT__simulate_quant_loader__4__load_count;
    __Vtask_tb_mma_controller__DOT__simulate_quant_loader__4__load_count = 0;
    // Body
    __Vtask_tb_mma_controller__DOT__simulate_quant_loader__4__load_count = 0U;
    VL_WRITEF_NX("\033[1;34m  === Quant loader started ===\033[0m\n",0);
    co_await vlSelfRef.__VtrigSched_h66f97190__0.trigger(0U, 
                                                         nullptr, 
                                                         "@([event] tb_mma_controller.quant_if.cb)", 
                                                         "test_compute_tasks.svh", 
                                                         167);
    while (VL_GTS_III(32, 4U, __Vtask_tb_mma_controller__DOT__simulate_quant_loader__4__load_count)) {
        vlSymsp->TOP__tb_mma_controller__DOT__quant_if.cb__DOT__load_quant_req = 1U;
        VL_WRITEF_NX("  [%0t] Quant loader: requesting load (tile=%0d)\n",0,
                     64,VL_TIME_UNITED_Q(1000),-9,32,
                     __Vtask_tb_mma_controller__DOT__simulate_quant_loader__4__load_count);
        while ((1U & (~ (IData)(vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__load_quant_granted)))) {
            co_await vlSelfRef.__VtrigSched_h4a02e0d9__0.trigger(1U, 
                                                                 nullptr, 
                                                                 "@([changed] tb_mma_controller.__Vcellout__dut__load_quant_granted)", 
                                                                 "test_compute_tasks.svh", 
                                                                 174);
        }
        VL_WRITEF_NX("  [%0t] Quant loader: granted (tile=%0d)\n",0,
                     64,VL_TIME_UNITED_Q(1000),-9,32,
                     __Vtask_tb_mma_controller__DOT__simulate_quant_loader__4__load_count);
        co_await vlSelfRef.__VtrigSched_h66f97190__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.quant_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             177);
        vlSymsp->TOP__tb_mma_controller__DOT__quant_if.cb__DOT__load_quant_req = 0U;
        co_await vlSelfRef.__VtrigSched_h66f97190__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.quant_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             181);
        co_await vlSelfRef.__VtrigSched_h66f97190__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.quant_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             181);
        co_await vlSelfRef.__VtrigSched_h66f97190__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.quant_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             181);
        co_await vlSelfRef.__VtrigSched_h66f97190__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.quant_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             181);
        co_await vlSelfRef.__VtrigSched_h66f97190__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.quant_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             181);
        co_await vlSelfRef.__VtrigSched_h66f97190__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.quant_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             181);
        co_await vlSelfRef.__VtrigSched_h66f97190__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.quant_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             181);
        co_await vlSelfRef.__VtrigSched_h66f97190__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.quant_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             181);
        co_await vlSelfRef.__VtrigSched_h66f97190__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.quant_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             181);
        co_await vlSelfRef.__VtrigSched_h66f97190__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.quant_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             181);
        co_await vlSelfRef.__VtrigSched_h66f97190__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.quant_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             181);
        co_await vlSelfRef.__VtrigSched_h66f97190__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.quant_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             181);
        co_await vlSelfRef.__VtrigSched_h66f97190__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.quant_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             181);
        co_await vlSelfRef.__VtrigSched_h66f97190__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.quant_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             181);
        co_await vlSelfRef.__VtrigSched_h66f97190__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.quant_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             181);
        co_await vlSelfRef.__VtrigSched_h66f97190__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.quant_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             181);
        vlSymsp->TOP__tb_mma_controller__DOT__quant_if.cb__DOT__quant_params_valid = 1U;
        VL_WRITEF_NX("  [%0t] Quant params valid (tile=%0d)\n",0,
                     64,VL_TIME_UNITED_Q(1000),-9,32,
                     __Vtask_tb_mma_controller__DOT__simulate_quant_loader__4__load_count);
        while ((1U & (~ (IData)(vlSymsp->TOP__tb_mma_controller__DOT__comp_if.tile_calc_over)))) {
            co_await vlSelfRef.__VtrigSched_ha535fff4__0.trigger(1U, 
                                                                 nullptr, 
                                                                 "@([changed] tb_mma_controller.comp_if.tile_calc_over)", 
                                                                 "test_compute_tasks.svh", 
                                                                 186);
        }
        VL_WRITEF_NX("  [%0t] Quant loader: tile done, clearing valid (tile=%0d)\n",0,
                     64,VL_TIME_UNITED_Q(1000),-9,32,
                     __Vtask_tb_mma_controller__DOT__simulate_quant_loader__4__load_count);
        vlSymsp->TOP__tb_mma_controller__DOT__quant_if.cb__DOT__quant_params_valid = 0U;
        __Vtask_tb_mma_controller__DOT__simulate_quant_loader__4__load_count 
            = ((IData)(1U) + __Vtask_tb_mma_controller__DOT__simulate_quant_loader__4__load_count);
    }
    VL_WRITEF_NX("\033[1;34m  === Quant loader finished (total=%0d tiles) ===\033[0m\n",0,
                 32,__Vtask_tb_mma_controller__DOT__simulate_quant_loader__4__load_count);
    vlSelfRef.__Vfork_1__sync.done("test_compute_tasks.svh", 
                                   315);
}

VL_INLINE_OPT VlCoroutine Vmma_controller_if___024root___eval_initial__TOP__Vtiming__1____Vfork_1__2(Vmma_controller_if___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vmma_controller_if___024root___eval_initial__TOP__Vtiming__1____Vfork_1__2\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Init
    IData/*31:0*/ __Vtask_tb_mma_controller__DOT__simulate_bias_loader__3__load_count;
    __Vtask_tb_mma_controller__DOT__simulate_bias_loader__3__load_count = 0;
    // Body
    __Vtask_tb_mma_controller__DOT__simulate_bias_loader__3__load_count = 0U;
    VL_WRITEF_NX("\033[1;34m  === Bias loader started ===\033[0m\n",0);
    co_await vlSelfRef.__VtrigSched_h4c63e026__0.trigger(0U, 
                                                         nullptr, 
                                                         "@([event] tb_mma_controller.bias_if.cb)", 
                                                         "test_compute_tasks.svh", 
                                                         129);
    while (VL_GTS_III(32, 4U, __Vtask_tb_mma_controller__DOT__simulate_bias_loader__3__load_count)) {
        vlSymsp->TOP__tb_mma_controller__DOT__bias_if.cb__DOT__load_bias_req = 1U;
        VL_WRITEF_NX("  [%0t] Bias loader: requesting load (tile=%0d)\n",0,
                     64,VL_TIME_UNITED_Q(1000),-9,32,
                     __Vtask_tb_mma_controller__DOT__simulate_bias_loader__3__load_count);
        while ((1U & (~ (IData)(vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__load_bias_granted)))) {
            co_await vlSelfRef.__VtrigSched_h90096cfe__0.trigger(1U, 
                                                                 nullptr, 
                                                                 "@([changed] tb_mma_controller.__Vcellout__dut__load_bias_granted)", 
                                                                 "test_compute_tasks.svh", 
                                                                 136);
        }
        VL_WRITEF_NX("  [%0t] Bias loader: granted (tile=%0d)\n",0,
                     64,VL_TIME_UNITED_Q(1000),-9,32,
                     __Vtask_tb_mma_controller__DOT__simulate_bias_loader__3__load_count);
        co_await vlSelfRef.__VtrigSched_h4c63e026__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.bias_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             139);
        vlSymsp->TOP__tb_mma_controller__DOT__bias_if.cb__DOT__load_bias_req = 0U;
        co_await vlSelfRef.__VtrigSched_h4c63e026__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.bias_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             143);
        co_await vlSelfRef.__VtrigSched_h4c63e026__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.bias_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             143);
        co_await vlSelfRef.__VtrigSched_h4c63e026__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.bias_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             143);
        co_await vlSelfRef.__VtrigSched_h4c63e026__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.bias_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             143);
        co_await vlSelfRef.__VtrigSched_h4c63e026__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.bias_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             143);
        co_await vlSelfRef.__VtrigSched_h4c63e026__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.bias_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             143);
        co_await vlSelfRef.__VtrigSched_h4c63e026__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.bias_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             143);
        co_await vlSelfRef.__VtrigSched_h4c63e026__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.bias_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             143);
        co_await vlSelfRef.__VtrigSched_h4c63e026__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.bias_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             143);
        co_await vlSelfRef.__VtrigSched_h4c63e026__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.bias_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             143);
        co_await vlSelfRef.__VtrigSched_h4c63e026__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.bias_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             143);
        co_await vlSelfRef.__VtrigSched_h4c63e026__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.bias_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             143);
        co_await vlSelfRef.__VtrigSched_h4c63e026__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.bias_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             143);
        co_await vlSelfRef.__VtrigSched_h4c63e026__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.bias_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             143);
        co_await vlSelfRef.__VtrigSched_h4c63e026__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.bias_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             143);
        co_await vlSelfRef.__VtrigSched_h4c63e026__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.bias_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             143);
        vlSymsp->TOP__tb_mma_controller__DOT__bias_if.cb__DOT__bias_valid = 1U;
        VL_WRITEF_NX("  [%0t] Bias data valid (tile=%0d)\n",0,
                     64,VL_TIME_UNITED_Q(1000),-9,32,
                     __Vtask_tb_mma_controller__DOT__simulate_bias_loader__3__load_count);
        while ((1U & (~ (IData)(vlSymsp->TOP__tb_mma_controller__DOT__comp_if.tile_calc_over)))) {
            co_await vlSelfRef.__VtrigSched_ha535fff4__0.trigger(1U, 
                                                                 nullptr, 
                                                                 "@([changed] tb_mma_controller.comp_if.tile_calc_over)", 
                                                                 "test_compute_tasks.svh", 
                                                                 148);
        }
        VL_WRITEF_NX("  [%0t] Bias loader: tile done, clearing valid (tile=%0d)\n",0,
                     64,VL_TIME_UNITED_Q(1000),-9,32,
                     __Vtask_tb_mma_controller__DOT__simulate_bias_loader__3__load_count);
        vlSymsp->TOP__tb_mma_controller__DOT__bias_if.cb__DOT__bias_valid = 0U;
        __Vtask_tb_mma_controller__DOT__simulate_bias_loader__3__load_count 
            = ((IData)(1U) + __Vtask_tb_mma_controller__DOT__simulate_bias_loader__3__load_count);
    }
    VL_WRITEF_NX("\033[1;34m  === Bias loader finished (total=%0d tiles) ===\033[0m\n",0,
                 32,__Vtask_tb_mma_controller__DOT__simulate_bias_loader__3__load_count);
    vlSelfRef.__Vfork_1__sync.done("test_compute_tasks.svh", 
                                   314);
}

VL_INLINE_OPT VlCoroutine Vmma_controller_if___024root___eval_initial__TOP__Vtiming__1____Vfork_1__1(Vmma_controller_if___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vmma_controller_if___024root___eval_initial__TOP__Vtiming__1____Vfork_1__1\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Init
    IData/*31:0*/ __Vtask_tb_mma_controller__DOT__simulate_ia_loader__2__load_count;
    __Vtask_tb_mma_controller__DOT__simulate_ia_loader__2__load_count = 0;
    // Body
    __Vtask_tb_mma_controller__DOT__simulate_ia_loader__2__load_count = 0U;
    VL_WRITEF_NX("\033[1;34m  === IA loader started ===\033[0m\n",0);
    co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                         nullptr, 
                                                         "@([event] tb_mma_controller.ia_if.cb)", 
                                                         "test_compute_tasks.svh", 
                                                         69);
    vlSymsp->TOP__tb_mma_controller__DOT__ia_if.cb__DOT__load_ia_req = 1U;
    while (VL_GTS_III(32, 0x10U, __Vtask_tb_mma_controller__DOT__simulate_ia_loader__2__load_count)) {
        VL_WRITEF_NX("  [%0t] IA loader: requesting load (count=%0d)\n",0,
                     64,VL_TIME_UNITED_Q(1000),-9,32,
                     __Vtask_tb_mma_controller__DOT__simulate_ia_loader__2__load_count);
        while ((1U & (~ (IData)(vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__load_ia_granted)))) {
            co_await vlSelfRef.__VtrigSched_h41abe5e7__0.trigger(1U, 
                                                                 nullptr, 
                                                                 "@([changed] tb_mma_controller.__Vcellout__dut__load_ia_granted)", 
                                                                 "test_compute_tasks.svh", 
                                                                 77);
        }
        VL_WRITEF_NX("  [%0t] IA loader: granted\n",0,
                     64,VL_TIME_UNITED_Q(1000),-9);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             81);
        vlSymsp->TOP__tb_mma_controller__DOT__ia_if.cb__DOT__ia_sending_done = 0U;
        vlSymsp->TOP__tb_mma_controller__DOT__ia_if.cb__DOT__load_ia_req = 0U;
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             86);
        vlSymsp->TOP__tb_mma_controller__DOT__ia_if.cb__DOT__ia_data_valid = 1U;
        VL_WRITEF_NX("  [%0t] IA data valid (count=%0d)\n",0,
                     64,VL_TIME_UNITED_Q(1000),-9,32,
                     __Vtask_tb_mma_controller__DOT__simulate_ia_loader__2__load_count);
        while ((1U & (~ (IData)(vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__send_ia_trigger)))) {
            co_await vlSelfRef.__VtrigSched_h8b2b3151__0.trigger(1U, 
                                                                 nullptr, 
                                                                 "@([changed] tb_mma_controller.__Vcellout__dut__send_ia_trigger)", 
                                                                 "test_compute_tasks.svh", 
                                                                 91);
        }
        VL_WRITEF_NX("  [%0t] IA send triggered (count=%0d)\n",0,
                     64,VL_TIME_UNITED_Q(1000),-9,32,
                     __Vtask_tb_mma_controller__DOT__simulate_ia_loader__2__load_count);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             95);
        vlSymsp->TOP__tb_mma_controller__DOT__ia_if.cb__DOT__ia_data_valid = 0U;
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             99);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             99);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             99);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             99);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             99);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             99);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             99);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             99);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             99);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             99);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             99);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             99);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             99);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             99);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             99);
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             99);
        vlSymsp->TOP__tb_mma_controller__DOT__ia_if.cb__DOT__ia_sending_done = 1U;
        VL_WRITEF_NX("  [%0t] IA sending done (count=%0d)\n",0,
                     64,VL_TIME_UNITED_Q(1000),-9,32,
                     __Vtask_tb_mma_controller__DOT__simulate_ia_loader__2__load_count);
        __Vtask_tb_mma_controller__DOT__simulate_ia_loader__2__load_count 
            = ((IData)(1U) + __Vtask_tb_mma_controller__DOT__simulate_ia_loader__2__load_count);
        if (VL_GTS_III(32, 0x10U, __Vtask_tb_mma_controller__DOT__simulate_ia_loader__2__load_count)) {
            vlSymsp->TOP__tb_mma_controller__DOT__ia_if.cb__DOT__load_ia_req = 1U;
        }
        co_await vlSelfRef.__VtrigSched_h742f9b30__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.ia_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             110);
        co_await vlSelfRef.__VtrigSched_hdac58424__0.trigger(0U, 
                                                             nullptr, 
                                                             "@(posedge tb_mma_controller.clk)", 
                                                             "test_compute_tasks.svh", 
                                                             111);
        vlSymsp->TOP__tb_mma_controller__DOT__ia_if.cb__DOT__ia_sending_done = 0U;
        if (vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__load_ia_granted) {
            vlSymsp->TOP__tb_mma_controller__DOT__ia_if.cb__DOT__load_ia_req = 0U;
        }
    }
    VL_WRITEF_NX("\033[1;34m  === IA loader finished (total=%0d) ===\033[0m\n",0,
                 32,__Vtask_tb_mma_controller__DOT__simulate_ia_loader__2__load_count);
    vlSelfRef.__Vfork_1__sync.done("test_compute_tasks.svh", 
                                   313);
}

VL_INLINE_OPT VlCoroutine Vmma_controller_if___024root___eval_initial__TOP__Vtiming__1____Vfork_1__0(Vmma_controller_if___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vmma_controller_if___024root___eval_initial__TOP__Vtiming__1____Vfork_1__0\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Init
    IData/*31:0*/ __Vtask_tb_mma_controller__DOT__simulate_weight_loader__1__load_count;
    __Vtask_tb_mma_controller__DOT__simulate_weight_loader__1__load_count = 0;
    // Body
    __Vtask_tb_mma_controller__DOT__simulate_weight_loader__1__load_count = 0U;
    VL_WRITEF_NX("\033[1;34m  === Weight loader started ===\033[0m\n",0);
    co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                         nullptr, 
                                                         "@([event] tb_mma_controller.weight_if.cb)", 
                                                         "test_compute_tasks.svh", 
                                                         11);
    vlSymsp->TOP__tb_mma_controller__DOT__weight_if.cb__DOT__load_weight_req = 1U;
    while (VL_GTS_III(32, 0x10U, __Vtask_tb_mma_controller__DOT__simulate_weight_loader__1__load_count)) {
        VL_WRITEF_NX("  [%0t] Weight loader: requesting load (count=%0d)\n",0,
                     64,VL_TIME_UNITED_Q(1000),-9,32,
                     __Vtask_tb_mma_controller__DOT__simulate_weight_loader__1__load_count);
        while ((1U & (~ (IData)(vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__load_weight_granted)))) {
            co_await vlSelfRef.__VtrigSched_hb997b169__0.trigger(1U, 
                                                                 nullptr, 
                                                                 "@([changed] tb_mma_controller.__Vcellout__dut__load_weight_granted)", 
                                                                 "test_compute_tasks.svh", 
                                                                 18);
        }
        VL_WRITEF_NX("  [%0t] Weight loader: granted\n",0,
                     64,VL_TIME_UNITED_Q(1000),-9);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             22);
        vlSymsp->TOP__tb_mma_controller__DOT__weight_if.cb__DOT__weight_sending_done = 0U;
        vlSymsp->TOP__tb_mma_controller__DOT__weight_if.cb__DOT__load_weight_req = 0U;
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             27);
        vlSymsp->TOP__tb_mma_controller__DOT__weight_if.cb__DOT__weight_data_valid = 1U;
        VL_WRITEF_NX("  [%0t] Weight data valid (count=%0d)\n",0,
                     64,VL_TIME_UNITED_Q(1000),-9,32,
                     __Vtask_tb_mma_controller__DOT__simulate_weight_loader__1__load_count);
        while ((1U & (~ (IData)(vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__send_weight_trigger)))) {
            co_await vlSelfRef.__VtrigSched_hf7995922__0.trigger(1U, 
                                                                 nullptr, 
                                                                 "@([changed] tb_mma_controller.__Vcellout__dut__send_weight_trigger)", 
                                                                 "test_compute_tasks.svh", 
                                                                 32);
        }
        VL_WRITEF_NX("  [%0t] Weight send triggered (count=%0d)\n",0,
                     64,VL_TIME_UNITED_Q(1000),-9,32,
                     __Vtask_tb_mma_controller__DOT__simulate_weight_loader__1__load_count);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             36);
        vlSymsp->TOP__tb_mma_controller__DOT__weight_if.cb__DOT__weight_data_valid = 0U;
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             40);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             40);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             40);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             40);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             40);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             40);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             40);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             40);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             40);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             40);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             40);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             40);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             40);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             40);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             40);
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             40);
        vlSymsp->TOP__tb_mma_controller__DOT__weight_if.cb__DOT__weight_sending_done = 1U;
        VL_WRITEF_NX("  [%0t] Weight sending done (count=%0d)\n",0,
                     64,VL_TIME_UNITED_Q(1000),-9,32,
                     __Vtask_tb_mma_controller__DOT__simulate_weight_loader__1__load_count);
        __Vtask_tb_mma_controller__DOT__simulate_weight_loader__1__load_count 
            = ((IData)(1U) + __Vtask_tb_mma_controller__DOT__simulate_weight_loader__1__load_count);
        if (VL_GTS_III(32, 0x10U, __Vtask_tb_mma_controller__DOT__simulate_weight_loader__1__load_count)) {
            vlSymsp->TOP__tb_mma_controller__DOT__weight_if.cb__DOT__load_weight_req = 1U;
        }
        co_await vlSelfRef.__VtrigSched_h9cd046e4__0.trigger(0U, 
                                                             nullptr, 
                                                             "@([event] tb_mma_controller.weight_if.cb)", 
                                                             "test_compute_tasks.svh", 
                                                             50);
        co_await vlSelfRef.__VtrigSched_hdac58424__0.trigger(0U, 
                                                             nullptr, 
                                                             "@(posedge tb_mma_controller.clk)", 
                                                             "test_compute_tasks.svh", 
                                                             51);
        vlSymsp->TOP__tb_mma_controller__DOT__weight_if.cb__DOT__weight_sending_done = 0U;
        if (vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__load_weight_granted) {
            vlSymsp->TOP__tb_mma_controller__DOT__weight_if.cb__DOT__load_weight_req = 0U;
        }
    }
    VL_WRITEF_NX("\033[1;34m  === Weight loader finished (total=%0d) ===\033[0m\n",0,
                 32,__Vtask_tb_mma_controller__DOT__simulate_weight_loader__1__load_count);
    vlSelfRef.__Vfork_1__sync.done("test_compute_tasks.svh", 
                                   312);
}

#ifdef VL_DEBUG
VL_ATTR_COLD void Vmma_controller_if___024root___dump_triggers__act(Vmma_controller_if___024root* vlSelf);
#endif  // VL_DEBUG

void Vmma_controller_if___024root___eval_triggers__act(Vmma_controller_if___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vmma_controller_if___024root___eval_triggers__act\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    CData/*0:0*/ __Vtrigcurrexpr_he004758a__0;
    __Vtrigcurrexpr_he004758a__0 = 0;
    CData/*0:0*/ __Vtrigcurrexpr_hbb0eeb4f__0;
    __Vtrigcurrexpr_hbb0eeb4f__0 = 0;
    __Vtrigcurrexpr_he004758a__0 = ((IData)(vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__init_cfg_ia) 
                                    & (IData)(vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__init_cfg_weight));
    __Vtrigcurrexpr_hbb0eeb4f__0 = (0U == (IData)(vlSelfRef.tb_mma_controller__DOT__dut__DOT__current_state));
    vlSelfRef.__VactTriggered.set(0U, (((IData)(vlSelfRef.tb_mma_controller__DOT__clk) 
                                        & (~ (IData)(vlSelfRef.__Vtrigprevexpr___TOP__tb_mma_controller__DOT__clk__0))) 
                                       | ((~ (IData)(vlSelfRef.tb_mma_controller__DOT__rst_n)) 
                                          & (IData)(vlSelfRef.__Vtrigprevexpr___TOP__tb_mma_controller__DOT__rst_n__0))));
    vlSelfRef.__VactTriggered.set(1U, ((IData)(vlSelfRef.tb_mma_controller__DOT__clk) 
                                       & (~ (IData)(vlSelfRef.__Vtrigprevexpr___TOP__tb_mma_controller__DOT__clk__0))));
    vlSelfRef.__VactTriggered.set(2U, vlSelfRef.__VdlySched.awaitingCurrentTime());
    vlSelfRef.__VactTriggered.set(3U, vlSymsp->TOP__tb_mma_controller__DOT__ctrl_if.cb.isFired());
    vlSelfRef.__VactTriggered.set(4U, vlSymsp->TOP__tb_mma_controller__DOT__comp_if.cb.isFired());
    vlSelfRef.__VactTriggered.set(5U, vlSymsp->TOP__tb_mma_controller__DOT__ia_if.cb.isFired());
    vlSelfRef.__VactTriggered.set(6U, vlSymsp->TOP__tb_mma_controller__DOT__weight_if.cb.isFired());
    vlSelfRef.__VactTriggered.set(7U, vlSymsp->TOP__tb_mma_controller__DOT__bias_if.cb.isFired());
    vlSelfRef.__VactTriggered.set(8U, vlSymsp->TOP__tb_mma_controller__DOT__quant_if.cb.isFired());
    vlSelfRef.__VactTriggered.set(9U, vlSymsp->TOP__tb_mma_controller__DOT__oa_if.cb.isFired());
    vlSelfRef.__VactTriggered.set(0xaU, ((IData)(__Vtrigcurrexpr_he004758a__0) 
                                         != (IData)(vlSelfRef.__Vtrigprevexpr_he004758a__0)));
    vlSelfRef.__VactTriggered.set(0xbU, ((IData)(vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__load_weight_granted) 
                                         != (IData)(vlSelfRef.__Vtrigprevexpr___TOP__tb_mma_controller__DOT____Vcellout__dut__load_weight_granted__0)));
    vlSelfRef.__VactTriggered.set(0xcU, ((IData)(vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__send_weight_trigger) 
                                         != (IData)(vlSelfRef.__Vtrigprevexpr___TOP__tb_mma_controller__DOT____Vcellout__dut__send_weight_trigger__0)));
    vlSelfRef.__VactTriggered.set(0xdU, ((IData)(vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__load_ia_granted) 
                                         != (IData)(vlSelfRef.__Vtrigprevexpr___TOP__tb_mma_controller__DOT____Vcellout__dut__load_ia_granted__0)));
    vlSelfRef.__VactTriggered.set(0xeU, ((IData)(vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__send_ia_trigger) 
                                         != (IData)(vlSelfRef.__Vtrigprevexpr___TOP__tb_mma_controller__DOT____Vcellout__dut__send_ia_trigger__0)));
    vlSelfRef.__VactTriggered.set(0xfU, ((IData)(vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__load_bias_granted) 
                                         != (IData)(vlSelfRef.__Vtrigprevexpr___TOP__tb_mma_controller__DOT____Vcellout__dut__load_bias_granted__0)));
    vlSelfRef.__VactTriggered.set(0x10U, ((IData)(vlSymsp->TOP__tb_mma_controller__DOT__comp_if.tile_calc_over) 
                                          != (IData)(vlSelfRef.__Vtrigprevexpr___TOP__tb_mma_controller__DOT__comp_if__tile_calc_over__0)));
    vlSelfRef.__VactTriggered.set(0x11U, ((IData)(vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__load_quant_granted) 
                                          != (IData)(vlSelfRef.__Vtrigprevexpr___TOP__tb_mma_controller__DOT____Vcellout__dut__load_quant_granted__0)));
    vlSelfRef.__VactTriggered.set(0x12U, ((IData)(vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__write_oa_granted) 
                                          != (IData)(vlSelfRef.__Vtrigprevexpr___TOP__tb_mma_controller__DOT____Vcellout__dut__write_oa_granted__0)));
    vlSelfRef.__VactTriggered.set(0x13U, ((IData)(vlSymsp->TOP__tb_mma_controller__DOT__ia_if.ia_sending_done) 
                                          != (IData)(vlSelfRef.__Vtrigprevexpr___TOP__tb_mma_controller__DOT__ia_if__ia_sending_done__0)));
    vlSelfRef.__VactTriggered.set(0x14U, ((IData)(vlSymsp->TOP__tb_mma_controller__DOT__oa_if.oa_calc_over) 
                                          != (IData)(vlSelfRef.__Vtrigprevexpr___TOP__tb_mma_controller__DOT__oa_if__oa_calc_over__0)));
    vlSelfRef.__VactTriggered.set(0x15U, ((IData)(__Vtrigcurrexpr_hbb0eeb4f__0) 
                                          != (IData)(vlSelfRef.__Vtrigprevexpr_hbb0eeb4f__0)));
    vlSelfRef.__Vtrigprevexpr___TOP__tb_mma_controller__DOT__clk__0 
        = vlSelfRef.tb_mma_controller__DOT__clk;
    vlSelfRef.__Vtrigprevexpr___TOP__tb_mma_controller__DOT__rst_n__0 
        = vlSelfRef.tb_mma_controller__DOT__rst_n;
    if (vlSymsp->TOP__tb_mma_controller__DOT__ctrl_if.cb.isFired()) {
        vlSymsp->TOP__tb_mma_controller__DOT__ctrl_if.cb.clearFired();
        vlSymsp->enqueueTriggeredEventForClearing(vlSymsp->TOP__tb_mma_controller__DOT__ctrl_if.cb);
    }
    if (vlSymsp->TOP__tb_mma_controller__DOT__comp_if.cb.isFired()) {
        vlSymsp->TOP__tb_mma_controller__DOT__comp_if.cb.clearFired();
        vlSymsp->enqueueTriggeredEventForClearing(vlSymsp->TOP__tb_mma_controller__DOT__comp_if.cb);
    }
    if (vlSymsp->TOP__tb_mma_controller__DOT__ia_if.cb.isFired()) {
        vlSymsp->TOP__tb_mma_controller__DOT__ia_if.cb.clearFired();
        vlSymsp->enqueueTriggeredEventForClearing(vlSymsp->TOP__tb_mma_controller__DOT__ia_if.cb);
    }
    if (vlSymsp->TOP__tb_mma_controller__DOT__weight_if.cb.isFired()) {
        vlSymsp->TOP__tb_mma_controller__DOT__weight_if.cb.clearFired();
        vlSymsp->enqueueTriggeredEventForClearing(vlSymsp->TOP__tb_mma_controller__DOT__weight_if.cb);
    }
    if (vlSymsp->TOP__tb_mma_controller__DOT__bias_if.cb.isFired()) {
        vlSymsp->TOP__tb_mma_controller__DOT__bias_if.cb.clearFired();
        vlSymsp->enqueueTriggeredEventForClearing(vlSymsp->TOP__tb_mma_controller__DOT__bias_if.cb);
    }
    if (vlSymsp->TOP__tb_mma_controller__DOT__quant_if.cb.isFired()) {
        vlSymsp->TOP__tb_mma_controller__DOT__quant_if.cb.clearFired();
        vlSymsp->enqueueTriggeredEventForClearing(vlSymsp->TOP__tb_mma_controller__DOT__quant_if.cb);
    }
    if (vlSymsp->TOP__tb_mma_controller__DOT__oa_if.cb.isFired()) {
        vlSymsp->TOP__tb_mma_controller__DOT__oa_if.cb.clearFired();
        vlSymsp->enqueueTriggeredEventForClearing(vlSymsp->TOP__tb_mma_controller__DOT__oa_if.cb);
    }
    vlSelfRef.__Vtrigprevexpr_he004758a__0 = __Vtrigcurrexpr_he004758a__0;
    vlSelfRef.__Vtrigprevexpr___TOP__tb_mma_controller__DOT____Vcellout__dut__load_weight_granted__0 
        = vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__load_weight_granted;
    vlSelfRef.__Vtrigprevexpr___TOP__tb_mma_controller__DOT____Vcellout__dut__send_weight_trigger__0 
        = vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__send_weight_trigger;
    vlSelfRef.__Vtrigprevexpr___TOP__tb_mma_controller__DOT____Vcellout__dut__load_ia_granted__0 
        = vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__load_ia_granted;
    vlSelfRef.__Vtrigprevexpr___TOP__tb_mma_controller__DOT____Vcellout__dut__send_ia_trigger__0 
        = vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__send_ia_trigger;
    vlSelfRef.__Vtrigprevexpr___TOP__tb_mma_controller__DOT____Vcellout__dut__load_bias_granted__0 
        = vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__load_bias_granted;
    vlSelfRef.__Vtrigprevexpr___TOP__tb_mma_controller__DOT__comp_if__tile_calc_over__0 
        = vlSymsp->TOP__tb_mma_controller__DOT__comp_if.tile_calc_over;
    vlSelfRef.__Vtrigprevexpr___TOP__tb_mma_controller__DOT____Vcellout__dut__load_quant_granted__0 
        = vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__load_quant_granted;
    vlSelfRef.__Vtrigprevexpr___TOP__tb_mma_controller__DOT____Vcellout__dut__write_oa_granted__0 
        = vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__write_oa_granted;
    vlSelfRef.__Vtrigprevexpr___TOP__tb_mma_controller__DOT__ia_if__ia_sending_done__0 
        = vlSymsp->TOP__tb_mma_controller__DOT__ia_if.ia_sending_done;
    vlSelfRef.__Vtrigprevexpr___TOP__tb_mma_controller__DOT__oa_if__oa_calc_over__0 
        = vlSymsp->TOP__tb_mma_controller__DOT__oa_if.oa_calc_over;
    vlSelfRef.__Vtrigprevexpr_hbb0eeb4f__0 = __Vtrigcurrexpr_hbb0eeb4f__0;
    if (VL_UNLIKELY((1U & (~ (IData)(vlSelfRef.__VactDidInit))))) {
        vlSelfRef.__VactDidInit = 1U;
        vlSelfRef.__VactTriggered.set(0xaU, 1U);
        vlSelfRef.__VactTriggered.set(0xbU, 1U);
        vlSelfRef.__VactTriggered.set(0xcU, 1U);
        vlSelfRef.__VactTriggered.set(0xdU, 1U);
        vlSelfRef.__VactTriggered.set(0xeU, 1U);
        vlSelfRef.__VactTriggered.set(0xfU, 1U);
        vlSelfRef.__VactTriggered.set(0x10U, 1U);
        vlSelfRef.__VactTriggered.set(0x11U, 1U);
        vlSelfRef.__VactTriggered.set(0x12U, 1U);
        vlSelfRef.__VactTriggered.set(0x13U, 1U);
        vlSelfRef.__VactTriggered.set(0x14U, 1U);
        vlSelfRef.__VactTriggered.set(0x15U, 1U);
    }
#ifdef VL_DEBUG
    if (VL_UNLIKELY(vlSymsp->_vm_contextp__->debug())) {
        Vmma_controller_if___024root___dump_triggers__act(vlSelf);
    }
#endif
}

VL_INLINE_OPT void Vmma_controller_if___024root___act_sequent__TOP__0(Vmma_controller_if___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vmma_controller_if___024root___act_sequent__TOP__0\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__current_done 
        = (((0U == (IData)(vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__current_master)) 
            & (IData)(vlSymsp->TOP__tb_mma_controller__DOT__ia_if.ia_data_valid)) 
           | (((1U == (IData)(vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__current_master)) 
               & (IData)(vlSymsp->TOP__tb_mma_controller__DOT__weight_if.weight_data_valid)) 
              | (((2U == (IData)(vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__current_master)) 
                  & (IData)(vlSymsp->TOP__tb_mma_controller__DOT__bias_if.bias_valid)) 
                 | (((3U == (IData)(vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__current_master)) 
                     & (IData)(vlSymsp->TOP__tb_mma_controller__DOT__quant_if.quant_params_valid)) 
                    | ((4U == (IData)(vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__current_master)) 
                       & (IData)(vlSymsp->TOP__tb_mma_controller__DOT__oa_if.write_done))))));
    vlSelfRef.tb_mma_controller__DOT__dut__DOT__next_state 
        = vlSelfRef.tb_mma_controller__DOT__dut__DOT__current_state;
    if ((8U & (IData)(vlSelfRef.tb_mma_controller__DOT__dut__DOT__current_state))) {
        if ((4U & (IData)(vlSelfRef.tb_mma_controller__DOT__dut__DOT__current_state))) {
            vlSelfRef.tb_mma_controller__DOT__dut__DOT__next_state = 0U;
        } else if ((2U & (IData)(vlSelfRef.tb_mma_controller__DOT__dut__DOT__current_state))) {
            vlSelfRef.tb_mma_controller__DOT__dut__DOT__next_state = 0U;
        } else if ((1U & (IData)(vlSelfRef.tb_mma_controller__DOT__dut__DOT__current_state))) {
            vlSelfRef.tb_mma_controller__DOT__dut__DOT__next_state = 0U;
        } else if (vlSelfRef.tb_mma_controller__DOT__dut__DOT__wb_ready) {
            vlSelfRef.tb_mma_controller__DOT__dut__DOT__next_state = 0U;
        }
    } else if ((4U & (IData)(vlSelfRef.tb_mma_controller__DOT__dut__DOT__current_state))) {
        if ((2U & (IData)(vlSelfRef.tb_mma_controller__DOT__dut__DOT__current_state))) {
            if ((1U & (IData)(vlSelfRef.tb_mma_controller__DOT__dut__DOT__current_state))) {
                if (vlSelfRef.tb_mma_controller__DOT__dut__DOT__wb_ready) {
                    vlSelfRef.tb_mma_controller__DOT__dut__DOT__next_state = 0U;
                }
            } else if (vlSymsp->TOP__tb_mma_controller__DOT__ia_if.ia_sending_done) {
                vlSelfRef.tb_mma_controller__DOT__dut__DOT__next_state = 4U;
            }
        } else if ((1U & (IData)(vlSelfRef.tb_mma_controller__DOT__dut__DOT__current_state))) {
            if (vlSymsp->TOP__tb_mma_controller__DOT__oa_if.oa_calc_over) {
                vlSelfRef.tb_mma_controller__DOT__dut__DOT__next_state 
                    = ((IData)(vlSelfRef.tb_mma_controller__DOT__dut__DOT__wb_ready)
                        ? 0U : 7U);
            } else if (vlSymsp->TOP__tb_mma_controller__DOT__weight_if.weight_sending_done) {
                vlSelfRef.tb_mma_controller__DOT__dut__DOT__next_state = 3U;
            }
        } else if (vlSymsp->TOP__tb_mma_controller__DOT__comp_if.partial_sum_calc_over) {
            vlSelfRef.tb_mma_controller__DOT__dut__DOT__next_state = 2U;
        }
    } else if ((2U & (IData)(vlSelfRef.tb_mma_controller__DOT__dut__DOT__current_state))) {
        if ((1U & (IData)(vlSelfRef.tb_mma_controller__DOT__dut__DOT__current_state))) {
            if ((((((IData)(vlSymsp->TOP__tb_mma_controller__DOT__ia_if.ia_data_valid) 
                    & (IData)(vlSymsp->TOP__tb_mma_controller__DOT__bias_if.bias_valid)) 
                   & (IData)(vlSymsp->TOP__tb_mma_controller__DOT__quant_if.quant_params_valid)) 
                  & (~ (IData)(vlSymsp->TOP__tb_mma_controller__DOT__ctrl_if.fifo_full_flag))) 
                 & (~ (IData)(vlSymsp->TOP__tb_mma_controller__DOT__ia_if.ia_sending_done)))) {
                vlSelfRef.tb_mma_controller__DOT__dut__DOT__next_state = 6U;
            }
        } else if (vlSymsp->TOP__tb_mma_controller__DOT__oa_if.oa_calc_over) {
            vlSelfRef.tb_mma_controller__DOT__dut__DOT__next_state 
                = ((IData)(vlSelfRef.tb_mma_controller__DOT__dut__DOT__wb_ready)
                    ? 0U : 7U);
        } else if (((IData)(vlSymsp->TOP__tb_mma_controller__DOT__weight_if.weight_data_valid) 
                    & (~ (IData)(vlSymsp->TOP__tb_mma_controller__DOT__weight_if.weight_sending_done)))) {
            vlSelfRef.tb_mma_controller__DOT__dut__DOT__next_state = 5U;
        }
    } else if ((1U & (IData)(vlSelfRef.tb_mma_controller__DOT__dut__DOT__current_state))) {
        vlSelfRef.tb_mma_controller__DOT__dut__DOT__next_state = 2U;
    } else if (vlSymsp->TOP__tb_mma_controller__DOT__ctrl_if.calc_start) {
        vlSelfRef.tb_mma_controller__DOT__dut__DOT__next_state 
            = (([&]() {
                    vlSelfRef.__Vfunc_tb_mma_controller__DOT__dut__DOT__check_config_valid__10__ptr_error 
                        = (((0U == vlSelfRef.tb_mma_controller__DOT__dut__DOT__lhs_base) 
                            | (0U == vlSelfRef.tb_mma_controller__DOT__dut__DOT__rhs_base)) 
                           | (0U == vlSelfRef.tb_mma_controller__DOT__dut__DOT__dst_base));
                    vlSelfRef.__Vfunc_tb_mma_controller__DOT__dut__DOT__check_config_valid__10__dim_error 
                        = (((0U == vlSelfRef.tb_mma_controller__DOT__dut__DOT__k) 
                            | (0U == vlSelfRef.tb_mma_controller__DOT__dut__DOT__n)) 
                           | (0U == vlSelfRef.tb_mma_controller__DOT__dut__DOT__m));
                    vlSelfRef.__Vfunc_tb_mma_controller__DOT__dut__DOT__check_config_valid__10__stride_error 
                        = (((0U == vlSelfRef.tb_mma_controller__DOT__dut__DOT__lhs_row_stride_b) 
                            | (0U == vlSelfRef.tb_mma_controller__DOT__dut__DOT__rhs_row_stride_b)) 
                           | (0U == vlSelfRef.tb_mma_controller__DOT__dut__DOT__dst_row_stride_b));
                    vlSelfRef.__Vfunc_tb_mma_controller__DOT__dut__DOT__check_config_valid__10__quant_error 
                        = (((IData)(vlSelfRef.tb_mma_controller__DOT__dut__DOT__use_per_channel) 
                            & (0U == vlSelfRef.tb_mma_controller__DOT__dut__DOT__q_mult_pt)) 
                           & (0U == vlSelfRef.tb_mma_controller__DOT__dut__DOT__q_shift_pt));
                    vlSelfRef.__Vfunc_tb_mma_controller__DOT__dut__DOT__check_config_valid__10__Vfuncout 
                        = ((((IData)(vlSelfRef.__Vfunc_tb_mma_controller__DOT__dut__DOT__check_config_valid__10__ptr_error) 
                             | (IData)(vlSelfRef.__Vfunc_tb_mma_controller__DOT__dut__DOT__check_config_valid__10__dim_error)) 
                            | (IData)(vlSelfRef.__Vfunc_tb_mma_controller__DOT__dut__DOT__check_config_valid__10__stride_error)) 
                           | (IData)(vlSelfRef.__Vfunc_tb_mma_controller__DOT__dut__DOT__check_config_valid__10__quant_error));
                }(), (IData)(vlSelfRef.__Vfunc_tb_mma_controller__DOT__dut__DOT__check_config_valid__10__Vfuncout))
                ? 8U : 1U);
    }
    vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__bus_idle 
        = (1U & ((~ (IData)(vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__bus_busy)) 
                 | ((IData)(vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__bus_busy) 
                    & (IData)(vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__current_done))));
}

VL_INLINE_OPT void Vmma_controller_if___024root___nba_sequent__TOP__0(Vmma_controller_if___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vmma_controller_if___024root___nba_sequent__TOP__0\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Init
    CData/*0:0*/ __Vfunc_tb_mma_controller__DOT__dut__DOT__check_config_valid__8__Vfuncout;
    __Vfunc_tb_mma_controller__DOT__dut__DOT__check_config_valid__8__Vfuncout = 0;
    CData/*0:0*/ __Vfunc_tb_mma_controller__DOT__dut__DOT__check_config_valid__8__ptr_error;
    __Vfunc_tb_mma_controller__DOT__dut__DOT__check_config_valid__8__ptr_error = 0;
    CData/*0:0*/ __Vfunc_tb_mma_controller__DOT__dut__DOT__check_config_valid__8__dim_error;
    __Vfunc_tb_mma_controller__DOT__dut__DOT__check_config_valid__8__dim_error = 0;
    CData/*0:0*/ __Vfunc_tb_mma_controller__DOT__dut__DOT__check_config_valid__8__stride_error;
    __Vfunc_tb_mma_controller__DOT__dut__DOT__check_config_valid__8__stride_error = 0;
    CData/*0:0*/ __Vfunc_tb_mma_controller__DOT__dut__DOT__check_config_valid__8__quant_error;
    __Vfunc_tb_mma_controller__DOT__dut__DOT__check_config_valid__8__quant_error = 0;
    CData/*1:0*/ __Vfunc_tb_mma_controller__DOT__dut__DOT__get_error_type__9__Vfuncout;
    __Vfunc_tb_mma_controller__DOT__dut__DOT__get_error_type__9__Vfuncout = 0;
    CData/*0:0*/ __Vfunc_tb_mma_controller__DOT__dut__DOT__get_error_type__9__ptr_error;
    __Vfunc_tb_mma_controller__DOT__dut__DOT__get_error_type__9__ptr_error = 0;
    CData/*0:0*/ __Vfunc_tb_mma_controller__DOT__dut__DOT__get_error_type__9__config_err;
    __Vfunc_tb_mma_controller__DOT__dut__DOT__get_error_type__9__config_err = 0;
    CData/*2:0*/ __Vtask_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__calc_updated_priority__11__granted_device;
    __Vtask_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__calc_updated_priority__11__granted_device = 0;
    VlUnpacked<CData/*2:0*/, 4> __Vtask_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__calc_updated_priority__11__curr_queue;
    for (int __Vi0 = 0; __Vi0 < 4; ++__Vi0) {
        __Vtask_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__calc_updated_priority__11__curr_queue[__Vi0] = 0;
    }
    VlUnpacked<CData/*2:0*/, 4> __Vtask_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__calc_updated_priority__11__new_queue;
    for (int __Vi0 = 0; __Vi0 < 4; ++__Vi0) {
        __Vtask_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__calc_updated_priority__11__new_queue[__Vi0] = 0;
    }
    IData/*31:0*/ __Vtask_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__calc_updated_priority__11__j;
    __Vtask_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__calc_updated_priority__11__j = 0;
    CData/*2:0*/ __Vfunc_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__arbitrate__12__Vfuncout;
    __Vfunc_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__arbitrate__12__Vfuncout = 0;
    CData/*2:0*/ __Vfunc_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__arbitrate__12__device_id;
    __Vfunc_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__arbitrate__12__device_id = 0;
    CData/*3:0*/ __Vdly__tb_mma_controller__DOT__dut__DOT__current_state;
    __Vdly__tb_mma_controller__DOT__dut__DOT__current_state = 0;
    CData/*2:0*/ __VdlyVal__tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__priority_queue__v0;
    __VdlyVal__tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__priority_queue__v0 = 0;
    CData/*2:0*/ __VdlyVal__tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__priority_queue__v1;
    __VdlyVal__tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__priority_queue__v1 = 0;
    CData/*2:0*/ __VdlyVal__tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__priority_queue__v2;
    __VdlyVal__tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__priority_queue__v2 = 0;
    CData/*2:0*/ __VdlyVal__tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__priority_queue__v3;
    __VdlyVal__tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__priority_queue__v3 = 0;
    CData/*0:0*/ __VdlySet__tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__priority_queue__v0;
    __VdlySet__tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__priority_queue__v0 = 0;
    CData/*0:0*/ __VdlySet__tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__priority_queue__v4;
    __VdlySet__tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__priority_queue__v4 = 0;
    // Body
    __VdlySet__tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__priority_queue__v0 = 0U;
    __VdlySet__tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__priority_queue__v4 = 0U;
    __Vdly__tb_mma_controller__DOT__dut__DOT__current_state 
        = vlSelfRef.tb_mma_controller__DOT__dut__DOT__current_state;
    if (vlSelfRef.tb_mma_controller__DOT__rst_n) {
        vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__init_cfg_ia = 0U;
        vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__init_cfg_weight = 0U;
        vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__init_cfg_bias = 0U;
        vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__init_cfg_requant = 0U;
        vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__init_cfg_oa = 0U;
        vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__send_weight_trigger = 0U;
        vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__send_ia_trigger = 0U;
        if ((1U & (~ ((IData)(vlSelfRef.tb_mma_controller__DOT__dut__DOT__current_state) 
                      >> 3U)))) {
            if ((1U & (~ ((IData)(vlSelfRef.tb_mma_controller__DOT__dut__DOT__current_state) 
                          >> 2U)))) {
                if ((1U & (~ ((IData)(vlSelfRef.tb_mma_controller__DOT__dut__DOT__current_state) 
                              >> 1U)))) {
                    if ((1U & (IData)(vlSelfRef.tb_mma_controller__DOT__dut__DOT__current_state))) {
                        vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__init_cfg_ia = 1U;
                        vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__init_cfg_weight = 1U;
                        vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__init_cfg_bias = 1U;
                        vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__init_cfg_requant = 1U;
                        vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__init_cfg_oa = 1U;
                        vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__use_16bits 
                            = vlSelfRef.tb_mma_controller__DOT__dut__DOT__cfg_16bits_ia_reg;
                    }
                }
                if ((2U & (IData)(vlSelfRef.tb_mma_controller__DOT__dut__DOT__current_state))) {
                    if ((1U & (~ (IData)(vlSelfRef.tb_mma_controller__DOT__dut__DOT__current_state)))) {
                        if (((IData)(vlSymsp->TOP__tb_mma_controller__DOT__weight_if.weight_data_valid) 
                             & (~ (IData)(vlSymsp->TOP__tb_mma_controller__DOT__weight_if.weight_sending_done)))) {
                            vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__send_weight_trigger = 1U;
                        }
                    }
                    if ((1U & (IData)(vlSelfRef.tb_mma_controller__DOT__dut__DOT__current_state))) {
                        if ((((((IData)(vlSymsp->TOP__tb_mma_controller__DOT__ia_if.ia_data_valid) 
                                & (IData)(vlSymsp->TOP__tb_mma_controller__DOT__bias_if.bias_valid)) 
                               & (IData)(vlSymsp->TOP__tb_mma_controller__DOT__quant_if.quant_params_valid)) 
                              & (~ (IData)(vlSymsp->TOP__tb_mma_controller__DOT__ctrl_if.fifo_full_flag))) 
                             & (~ (IData)(vlSymsp->TOP__tb_mma_controller__DOT__ia_if.ia_sending_done)))) {
                            vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__send_ia_trigger = 1U;
                        }
                    }
                }
            }
        }
        if (((IData)(vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__bus_busy) 
             & (IData)(vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__current_done))) {
            if ((4U != (IData)(vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__current_master))) {
                __Vtask_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__calc_updated_priority__11__curr_queue[3U] 
                    = vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__priority_queue
                    [3U];
                __Vtask_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__calc_updated_priority__11__curr_queue[2U] 
                    = vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__priority_queue
                    [2U];
                __Vtask_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__calc_updated_priority__11__curr_queue[1U] 
                    = vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__priority_queue
                    [1U];
                __Vtask_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__calc_updated_priority__11__curr_queue[0U] 
                    = vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__priority_queue
                    [0U];
                __Vtask_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__calc_updated_priority__11__granted_device 
                    = vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__current_master;
                __Vtask_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__calc_updated_priority__11__j = 0U;
                if ((__Vtask_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__calc_updated_priority__11__curr_queue
                     [0U] != (IData)(__Vtask_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__calc_updated_priority__11__granted_device))) {
                    __Vtask_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__calc_updated_priority__11__new_queue[(3U 
                                                                                & __Vtask_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__calc_updated_priority__11__j)] 
                        = __Vtask_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__calc_updated_priority__11__curr_queue
                        [0U];
                    __Vtask_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__calc_updated_priority__11__j 
                        = ((IData)(1U) + __Vtask_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__calc_updated_priority__11__j);
                }
                if ((__Vtask_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__calc_updated_priority__11__curr_queue
                     [1U] != (IData)(__Vtask_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__calc_updated_priority__11__granted_device))) {
                    __Vtask_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__calc_updated_priority__11__new_queue[(3U 
                                                                                & __Vtask_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__calc_updated_priority__11__j)] 
                        = __Vtask_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__calc_updated_priority__11__curr_queue
                        [1U];
                    __Vtask_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__calc_updated_priority__11__j 
                        = ((IData)(1U) + __Vtask_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__calc_updated_priority__11__j);
                }
                if ((__Vtask_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__calc_updated_priority__11__curr_queue
                     [2U] != (IData)(__Vtask_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__calc_updated_priority__11__granted_device))) {
                    __Vtask_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__calc_updated_priority__11__new_queue[(3U 
                                                                                & __Vtask_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__calc_updated_priority__11__j)] 
                        = __Vtask_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__calc_updated_priority__11__curr_queue
                        [2U];
                    __Vtask_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__calc_updated_priority__11__j 
                        = ((IData)(1U) + __Vtask_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__calc_updated_priority__11__j);
                }
                if ((__Vtask_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__calc_updated_priority__11__curr_queue
                     [3U] != (IData)(__Vtask_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__calc_updated_priority__11__granted_device))) {
                    __Vtask_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__calc_updated_priority__11__new_queue[(3U 
                                                                                & __Vtask_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__calc_updated_priority__11__j)] 
                        = __Vtask_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__calc_updated_priority__11__curr_queue
                        [3U];
                    __Vtask_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__calc_updated_priority__11__j 
                        = ((IData)(1U) + __Vtask_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__calc_updated_priority__11__j);
                }
                __Vtask_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__calc_updated_priority__11__new_queue[3U] 
                    = __Vtask_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__calc_updated_priority__11__granted_device;
                vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__next_priority_queue[3U] 
                    = __Vtask_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__calc_updated_priority__11__new_queue
                    [3U];
                vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__next_priority_queue[2U] 
                    = __Vtask_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__calc_updated_priority__11__new_queue
                    [2U];
                vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__next_priority_queue[1U] 
                    = __Vtask_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__calc_updated_priority__11__new_queue
                    [1U];
                vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__next_priority_queue[0U] 
                    = __Vtask_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__calc_updated_priority__11__new_queue
                    [0U];
                __VdlyVal__tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__priority_queue__v0 
                    = vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__next_priority_queue
                    [0U];
                __VdlySet__tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__priority_queue__v0 = 1U;
                __VdlyVal__tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__priority_queue__v1 
                    = vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__next_priority_queue
                    [1U];
                __VdlyVal__tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__priority_queue__v2 
                    = vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__next_priority_queue
                    [2U];
                __VdlyVal__tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__priority_queue__v3 
                    = vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__next_priority_queue
                    [3U];
            }
            vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__load_ia_granted = 0U;
            vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__load_weight_granted = 0U;
            vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__load_bias_granted = 0U;
            vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__load_quant_granted = 0U;
            vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__write_oa_granted = 0U;
            vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__bus_busy = 0U;
        }
        if (vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__bus_idle) {
            if (vlSymsp->TOP__tb_mma_controller__DOT__oa_if.write_oa_req) {
                vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__write_oa_granted = 1U;
                vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__icb_sel = 4U;
                vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__current_master = 4U;
                vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__bus_busy = 1U;
            } else {
                {
                    __Vfunc_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__arbitrate__12__device_id 
                        = vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__priority_queue
                        [0U];
                    if ((0U == (IData)(__Vfunc_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__arbitrate__12__device_id))) {
                        if (vlSymsp->TOP__tb_mma_controller__DOT__ia_if.load_ia_req) {
                            __Vfunc_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__arbitrate__12__Vfuncout = 0U;
                            goto __Vlabel2;
                        }
                    } else if ((1U == (IData)(__Vfunc_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__arbitrate__12__device_id))) {
                        if (vlSymsp->TOP__tb_mma_controller__DOT__weight_if.load_weight_req) {
                            __Vfunc_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__arbitrate__12__Vfuncout = 1U;
                            goto __Vlabel2;
                        }
                    } else if ((2U == (IData)(__Vfunc_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__arbitrate__12__device_id))) {
                        if (vlSymsp->TOP__tb_mma_controller__DOT__bias_if.load_bias_req) {
                            __Vfunc_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__arbitrate__12__Vfuncout = 2U;
                            goto __Vlabel2;
                        }
                    } else if ((3U == (IData)(__Vfunc_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__arbitrate__12__device_id))) {
                        if (vlSymsp->TOP__tb_mma_controller__DOT__quant_if.load_quant_req) {
                            __Vfunc_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__arbitrate__12__Vfuncout = 3U;
                            goto __Vlabel2;
                        }
                    }
                    __Vfunc_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__arbitrate__12__device_id 
                        = vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__priority_queue
                        [1U];
                    if ((0U == (IData)(__Vfunc_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__arbitrate__12__device_id))) {
                        if (vlSymsp->TOP__tb_mma_controller__DOT__ia_if.load_ia_req) {
                            __Vfunc_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__arbitrate__12__Vfuncout = 0U;
                            goto __Vlabel2;
                        }
                    } else if ((1U == (IData)(__Vfunc_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__arbitrate__12__device_id))) {
                        if (vlSymsp->TOP__tb_mma_controller__DOT__weight_if.load_weight_req) {
                            __Vfunc_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__arbitrate__12__Vfuncout = 1U;
                            goto __Vlabel2;
                        }
                    } else if ((2U == (IData)(__Vfunc_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__arbitrate__12__device_id))) {
                        if (vlSymsp->TOP__tb_mma_controller__DOT__bias_if.load_bias_req) {
                            __Vfunc_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__arbitrate__12__Vfuncout = 2U;
                            goto __Vlabel2;
                        }
                    } else if ((3U == (IData)(__Vfunc_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__arbitrate__12__device_id))) {
                        if (vlSymsp->TOP__tb_mma_controller__DOT__quant_if.load_quant_req) {
                            __Vfunc_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__arbitrate__12__Vfuncout = 3U;
                            goto __Vlabel2;
                        }
                    }
                    __Vfunc_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__arbitrate__12__device_id 
                        = vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__priority_queue
                        [2U];
                    if ((0U == (IData)(__Vfunc_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__arbitrate__12__device_id))) {
                        if (vlSymsp->TOP__tb_mma_controller__DOT__ia_if.load_ia_req) {
                            __Vfunc_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__arbitrate__12__Vfuncout = 0U;
                            goto __Vlabel2;
                        }
                    } else if ((1U == (IData)(__Vfunc_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__arbitrate__12__device_id))) {
                        if (vlSymsp->TOP__tb_mma_controller__DOT__weight_if.load_weight_req) {
                            __Vfunc_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__arbitrate__12__Vfuncout = 1U;
                            goto __Vlabel2;
                        }
                    } else if ((2U == (IData)(__Vfunc_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__arbitrate__12__device_id))) {
                        if (vlSymsp->TOP__tb_mma_controller__DOT__bias_if.load_bias_req) {
                            __Vfunc_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__arbitrate__12__Vfuncout = 2U;
                            goto __Vlabel2;
                        }
                    } else if ((3U == (IData)(__Vfunc_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__arbitrate__12__device_id))) {
                        if (vlSymsp->TOP__tb_mma_controller__DOT__quant_if.load_quant_req) {
                            __Vfunc_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__arbitrate__12__Vfuncout = 3U;
                            goto __Vlabel2;
                        }
                    }
                    __Vfunc_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__arbitrate__12__device_id 
                        = vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__priority_queue
                        [3U];
                    if ((0U == (IData)(__Vfunc_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__arbitrate__12__device_id))) {
                        if (vlSymsp->TOP__tb_mma_controller__DOT__ia_if.load_ia_req) {
                            __Vfunc_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__arbitrate__12__Vfuncout = 0U;
                            goto __Vlabel2;
                        }
                    } else if ((1U == (IData)(__Vfunc_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__arbitrate__12__device_id))) {
                        if (vlSymsp->TOP__tb_mma_controller__DOT__weight_if.load_weight_req) {
                            __Vfunc_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__arbitrate__12__Vfuncout = 1U;
                            goto __Vlabel2;
                        }
                    } else if ((2U == (IData)(__Vfunc_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__arbitrate__12__device_id))) {
                        if (vlSymsp->TOP__tb_mma_controller__DOT__bias_if.load_bias_req) {
                            __Vfunc_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__arbitrate__12__Vfuncout = 2U;
                            goto __Vlabel2;
                        }
                    } else if ((3U == (IData)(__Vfunc_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__arbitrate__12__device_id))) {
                        if (vlSymsp->TOP__tb_mma_controller__DOT__quant_if.load_quant_req) {
                            __Vfunc_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__arbitrate__12__Vfuncout = 3U;
                            goto __Vlabel2;
                        }
                    }
                    __Vfunc_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__arbitrate__12__Vfuncout = 7U;
                    __Vlabel2: ;
                }
                vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__unnamedblk1__DOT__next_device 
                    = __Vfunc_tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__arbitrate__12__Vfuncout;
                if ((1U & (~ ((IData)(vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__unnamedblk1__DOT__next_device) 
                              >> 2U)))) {
                    if ((2U & (IData)(vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__unnamedblk1__DOT__next_device))) {
                        if ((1U & (IData)(vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__unnamedblk1__DOT__next_device))) {
                            vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__load_quant_granted = 1U;
                            vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__icb_sel = 3U;
                            vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__current_master = 3U;
                            vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__bus_busy = 1U;
                        } else {
                            vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__load_bias_granted = 1U;
                            vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__icb_sel = 2U;
                            vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__current_master = 2U;
                            vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__bus_busy = 1U;
                        }
                    } else if ((1U & (IData)(vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__unnamedblk1__DOT__next_device))) {
                        vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__load_weight_granted = 1U;
                        vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__icb_sel = 1U;
                        vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__current_master = 1U;
                        vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__bus_busy = 1U;
                    } else {
                        vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__load_ia_granted = 1U;
                        vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__icb_sel = 0U;
                        vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__current_master = 0U;
                        vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__bus_busy = 1U;
                    }
                }
            }
        }
        if ((8U & (IData)(vlSelfRef.tb_mma_controller__DOT__dut__DOT__current_state))) {
            if ((1U & (~ ((IData)(vlSelfRef.tb_mma_controller__DOT__dut__DOT__current_state) 
                          >> 2U)))) {
                if ((1U & (~ ((IData)(vlSelfRef.tb_mma_controller__DOT__dut__DOT__current_state) 
                              >> 1U)))) {
                    if ((1U & (~ (IData)(vlSelfRef.tb_mma_controller__DOT__dut__DOT__current_state)))) {
                        vlSelfRef.tb_mma_controller__DOT__dut__DOT__err_code 
                            = vlSelfRef.tb_mma_controller__DOT__dut__DOT__error_type;
                    }
                }
            }
        } else if ((1U & (~ ((IData)(vlSelfRef.tb_mma_controller__DOT__dut__DOT__current_state) 
                             >> 2U)))) {
            if ((1U & (~ ((IData)(vlSelfRef.tb_mma_controller__DOT__dut__DOT__current_state) 
                          >> 1U)))) {
                if ((1U & (~ (IData)(vlSelfRef.tb_mma_controller__DOT__dut__DOT__current_state)))) {
                    vlSelfRef.tb_mma_controller__DOT__dut__DOT__err_code = 0U;
                }
            }
        }
        __Vdly__tb_mma_controller__DOT__dut__DOT__current_state 
            = vlSelfRef.tb_mma_controller__DOT__dut__DOT__next_state;
        if (((0U == (IData)(vlSelfRef.tb_mma_controller__DOT__dut__DOT__current_state)) 
             & (IData)(vlSymsp->TOP__tb_mma_controller__DOT__ctrl_if.calc_start))) {
            vlSelfRef.tb_mma_controller__DOT__dut__DOT__cfg_16bits_ia_reg 
                = vlSymsp->TOP__tb_mma_controller__DOT__ctrl_if.cfg_16bits_ia;
            __Vfunc_tb_mma_controller__DOT__dut__DOT__check_config_valid__8__ptr_error 
                = (((0U == vlSelfRef.tb_mma_controller__DOT__dut__DOT__lhs_base) 
                    | (0U == vlSelfRef.tb_mma_controller__DOT__dut__DOT__rhs_base)) 
                   | (0U == vlSelfRef.tb_mma_controller__DOT__dut__DOT__dst_base));
            __Vfunc_tb_mma_controller__DOT__dut__DOT__check_config_valid__8__dim_error 
                = (((0U == vlSelfRef.tb_mma_controller__DOT__dut__DOT__k) 
                    | (0U == vlSelfRef.tb_mma_controller__DOT__dut__DOT__n)) 
                   | (0U == vlSelfRef.tb_mma_controller__DOT__dut__DOT__m));
            __Vfunc_tb_mma_controller__DOT__dut__DOT__check_config_valid__8__stride_error 
                = (((0U == vlSelfRef.tb_mma_controller__DOT__dut__DOT__lhs_row_stride_b) 
                    | (0U == vlSelfRef.tb_mma_controller__DOT__dut__DOT__rhs_row_stride_b)) 
                   | (0U == vlSelfRef.tb_mma_controller__DOT__dut__DOT__dst_row_stride_b));
            __Vfunc_tb_mma_controller__DOT__dut__DOT__check_config_valid__8__quant_error 
                = (((IData)(vlSelfRef.tb_mma_controller__DOT__dut__DOT__use_per_channel) 
                    & (0U == vlSelfRef.tb_mma_controller__DOT__dut__DOT__q_mult_pt)) 
                   & (0U == vlSelfRef.tb_mma_controller__DOT__dut__DOT__q_shift_pt));
            __Vfunc_tb_mma_controller__DOT__dut__DOT__check_config_valid__8__Vfuncout 
                = ((((IData)(__Vfunc_tb_mma_controller__DOT__dut__DOT__check_config_valid__8__ptr_error) 
                     | (IData)(__Vfunc_tb_mma_controller__DOT__dut__DOT__check_config_valid__8__dim_error)) 
                    | (IData)(__Vfunc_tb_mma_controller__DOT__dut__DOT__check_config_valid__8__stride_error)) 
                   | (IData)(__Vfunc_tb_mma_controller__DOT__dut__DOT__check_config_valid__8__quant_error));
            vlSelfRef.tb_mma_controller__DOT__dut__DOT__config_error 
                = __Vfunc_tb_mma_controller__DOT__dut__DOT__check_config_valid__8__Vfuncout;
            {
                __Vfunc_tb_mma_controller__DOT__dut__DOT__get_error_type__9__ptr_error 
                    = (((0U == vlSelfRef.tb_mma_controller__DOT__dut__DOT__lhs_base) 
                        | (0U == vlSelfRef.tb_mma_controller__DOT__dut__DOT__rhs_base)) 
                       | (0U == vlSelfRef.tb_mma_controller__DOT__dut__DOT__dst_base));
                __Vfunc_tb_mma_controller__DOT__dut__DOT__get_error_type__9__config_err 
                    = (((((((0U == vlSelfRef.tb_mma_controller__DOT__dut__DOT__k) 
                            | (0U == vlSelfRef.tb_mma_controller__DOT__dut__DOT__n)) 
                           | (0U == vlSelfRef.tb_mma_controller__DOT__dut__DOT__m)) 
                          | (0U == vlSelfRef.tb_mma_controller__DOT__dut__DOT__lhs_row_stride_b)) 
                         | (0U == vlSelfRef.tb_mma_controller__DOT__dut__DOT__rhs_row_stride_b)) 
                        | (0U == vlSelfRef.tb_mma_controller__DOT__dut__DOT__dst_row_stride_b)) 
                       | ((IData)(vlSelfRef.tb_mma_controller__DOT__dut__DOT__use_per_channel) 
                          & ((0U == vlSelfRef.tb_mma_controller__DOT__dut__DOT__q_mult_pt) 
                             | (0U == vlSelfRef.tb_mma_controller__DOT__dut__DOT__q_shift_pt))));
                if (__Vfunc_tb_mma_controller__DOT__dut__DOT__get_error_type__9__ptr_error) {
                    __Vfunc_tb_mma_controller__DOT__dut__DOT__get_error_type__9__Vfuncout = 2U;
                    goto __Vlabel3;
                } else if (__Vfunc_tb_mma_controller__DOT__dut__DOT__get_error_type__9__config_err) {
                    __Vfunc_tb_mma_controller__DOT__dut__DOT__get_error_type__9__Vfuncout = 1U;
                    goto __Vlabel3;
                } else {
                    __Vfunc_tb_mma_controller__DOT__dut__DOT__get_error_type__9__Vfuncout = 0U;
                    goto __Vlabel3;
                }
                __Vlabel3: ;
            }
            vlSelfRef.tb_mma_controller__DOT__dut__DOT__error_type 
                = __Vfunc_tb_mma_controller__DOT__dut__DOT__get_error_type__9__Vfuncout;
        }
    } else {
        vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__init_cfg_ia = 0U;
        vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__init_cfg_weight = 0U;
        vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__init_cfg_bias = 0U;
        vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__init_cfg_requant = 0U;
        vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__init_cfg_oa = 0U;
        vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__send_weight_trigger = 0U;
        vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__send_ia_trigger = 0U;
        vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__load_ia_granted = 0U;
        vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__load_weight_granted = 0U;
        vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__load_bias_granted = 0U;
        vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__load_quant_granted = 0U;
        vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__write_oa_granted = 0U;
        vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__icb_sel = 0U;
        vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__current_master = 0U;
        vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__bus_busy = 0U;
        __VdlySet__tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__priority_queue__v4 = 1U;
        vlSelfRef.tb_mma_controller__DOT__dut__DOT__err_code = 0U;
        vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__use_16bits = 0U;
        __Vdly__tb_mma_controller__DOT__dut__DOT__current_state = 0U;
        vlSelfRef.tb_mma_controller__DOT__dut__DOT__cfg_16bits_ia_reg = 0U;
        vlSelfRef.tb_mma_controller__DOT__dut__DOT__config_error = 0U;
        vlSelfRef.tb_mma_controller__DOT__dut__DOT__error_type = 0U;
    }
    if (__VdlySet__tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__priority_queue__v0) {
        vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__priority_queue[0U] 
            = __VdlyVal__tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__priority_queue__v0;
        vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__priority_queue[1U] 
            = __VdlyVal__tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__priority_queue__v1;
        vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__priority_queue[2U] 
            = __VdlyVal__tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__priority_queue__v2;
        vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__priority_queue[3U] 
            = __VdlyVal__tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__priority_queue__v3;
    }
    if (__VdlySet__tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__priority_queue__v4) {
        vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__priority_queue[0U] = 1U;
        vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__priority_queue[1U] = 0U;
        vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__priority_queue[2U] = 3U;
        vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__priority_queue[3U] = 2U;
    }
    vlSelfRef.tb_mma_controller__DOT__dut__DOT__current_state 
        = __Vdly__tb_mma_controller__DOT__dut__DOT__current_state;
}

void Vmma_controller_if_ia_loader_if___obs_sequent__TOP__tb_mma_controller__DOT__ia_if__0(Vmma_controller_if_ia_loader_if* vlSelf);
void Vmma_controller_if_weight_loader_if___obs_sequent__TOP__tb_mma_controller__DOT__weight_if__0(Vmma_controller_if_weight_loader_if* vlSelf);
void Vmma_controller_if_bias_loader_if___obs_sequent__TOP__tb_mma_controller__DOT__bias_if__0(Vmma_controller_if_bias_loader_if* vlSelf);
void Vmma_controller_if_requant_if___obs_sequent__TOP__tb_mma_controller__DOT__quant_if__0(Vmma_controller_if_requant_if* vlSelf);
void Vmma_controller_if_oa_writer_if___obs_sequent__TOP__tb_mma_controller__DOT__oa_if__0(Vmma_controller_if_oa_writer_if* vlSelf);
void Vmma_controller_if_compute_core_if___obs_sequent__TOP__tb_mma_controller__DOT__comp_if__0(Vmma_controller_if_compute_core_if* vlSelf);
void Vmma_controller_if_control_if__R20___obs_sequent__TOP__tb_mma_controller__DOT__ctrl_if__0(Vmma_controller_if_control_if__R20* vlSelf);

void Vmma_controller_if___024root___eval_obs(Vmma_controller_if___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vmma_controller_if___024root___eval_obs\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    if ((2ULL & vlSelfRef.__VobsTriggered.word(0U))) {
        Vmma_controller_if_ia_loader_if___obs_sequent__TOP__tb_mma_controller__DOT__ia_if__0((&vlSymsp->TOP__tb_mma_controller__DOT__ia_if));
        Vmma_controller_if_weight_loader_if___obs_sequent__TOP__tb_mma_controller__DOT__weight_if__0((&vlSymsp->TOP__tb_mma_controller__DOT__weight_if));
        Vmma_controller_if_bias_loader_if___obs_sequent__TOP__tb_mma_controller__DOT__bias_if__0((&vlSymsp->TOP__tb_mma_controller__DOT__bias_if));
        Vmma_controller_if_requant_if___obs_sequent__TOP__tb_mma_controller__DOT__quant_if__0((&vlSymsp->TOP__tb_mma_controller__DOT__quant_if));
        Vmma_controller_if_oa_writer_if___obs_sequent__TOP__tb_mma_controller__DOT__oa_if__0((&vlSymsp->TOP__tb_mma_controller__DOT__oa_if));
        Vmma_controller_if_compute_core_if___obs_sequent__TOP__tb_mma_controller__DOT__comp_if__0((&vlSymsp->TOP__tb_mma_controller__DOT__comp_if));
        Vmma_controller_if_control_if__R20___obs_sequent__TOP__tb_mma_controller__DOT__ctrl_if__0((&vlSymsp->TOP__tb_mma_controller__DOT__ctrl_if));
    }
    if ((6ULL & vlSelfRef.__VobsTriggered.word(0U))) {
        Vmma_controller_if___024root___act_sequent__TOP__0(vlSelf);
    }
}
