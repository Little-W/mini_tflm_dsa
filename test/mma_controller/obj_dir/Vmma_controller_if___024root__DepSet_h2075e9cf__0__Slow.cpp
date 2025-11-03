// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Design implementation internals
// See Vmma_controller_if.h for the primary calling header

#include "Vmma_controller_if__pch.h"
#include "Vmma_controller_if__Syms.h"
#include "Vmma_controller_if___024root.h"

VL_ATTR_COLD void Vmma_controller_if_ia_loader_if___eval_static__TOP__tb_mma_controller__DOT__ia_if(Vmma_controller_if_ia_loader_if* vlSelf);
VL_ATTR_COLD void Vmma_controller_if_weight_loader_if___eval_static__TOP__tb_mma_controller__DOT__weight_if(Vmma_controller_if_weight_loader_if* vlSelf);
VL_ATTR_COLD void Vmma_controller_if_bias_loader_if___eval_static__TOP__tb_mma_controller__DOT__bias_if(Vmma_controller_if_bias_loader_if* vlSelf);
VL_ATTR_COLD void Vmma_controller_if_requant_if___eval_static__TOP__tb_mma_controller__DOT__quant_if(Vmma_controller_if_requant_if* vlSelf);
VL_ATTR_COLD void Vmma_controller_if_oa_writer_if___eval_static__TOP__tb_mma_controller__DOT__oa_if(Vmma_controller_if_oa_writer_if* vlSelf);
VL_ATTR_COLD void Vmma_controller_if_compute_core_if___eval_static__TOP__tb_mma_controller__DOT__comp_if(Vmma_controller_if_compute_core_if* vlSelf);
VL_ATTR_COLD void Vmma_controller_if_control_if__R20___eval_static__TOP__tb_mma_controller__DOT__ctrl_if(Vmma_controller_if_control_if__R20* vlSelf);

VL_ATTR_COLD void Vmma_controller_if___024root___eval_static(Vmma_controller_if___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vmma_controller_if___024root___eval_static\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    Vmma_controller_if_ia_loader_if___eval_static__TOP__tb_mma_controller__DOT__ia_if((&vlSymsp->TOP__tb_mma_controller__DOT__ia_if));
    Vmma_controller_if_weight_loader_if___eval_static__TOP__tb_mma_controller__DOT__weight_if((&vlSymsp->TOP__tb_mma_controller__DOT__weight_if));
    Vmma_controller_if_bias_loader_if___eval_static__TOP__tb_mma_controller__DOT__bias_if((&vlSymsp->TOP__tb_mma_controller__DOT__bias_if));
    Vmma_controller_if_requant_if___eval_static__TOP__tb_mma_controller__DOT__quant_if((&vlSymsp->TOP__tb_mma_controller__DOT__quant_if));
    Vmma_controller_if_oa_writer_if___eval_static__TOP__tb_mma_controller__DOT__oa_if((&vlSymsp->TOP__tb_mma_controller__DOT__oa_if));
    Vmma_controller_if_compute_core_if___eval_static__TOP__tb_mma_controller__DOT__comp_if((&vlSymsp->TOP__tb_mma_controller__DOT__comp_if));
    Vmma_controller_if_control_if__R20___eval_static__TOP__tb_mma_controller__DOT__ctrl_if((&vlSymsp->TOP__tb_mma_controller__DOT__ctrl_if));
}

VL_ATTR_COLD VlCoroutine Vmma_controller_if___024root___eval_initial__TOP____Vfork_2__0(Vmma_controller_if___024root* vlSelf);

VL_ATTR_COLD void Vmma_controller_if___024root___eval_initial__TOP(Vmma_controller_if___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vmma_controller_if___024root___eval_initial__TOP\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    vlSymsp->_vm_contextp__->dumpfile(std::string{"wave.vcd"});
    vlSymsp->_traceDumpOpen();
    Vmma_controller_if___024root___eval_initial__TOP____Vfork_2__0(vlSelf);
}

VL_ATTR_COLD VlCoroutine Vmma_controller_if___024root___eval_initial__TOP____Vfork_2__0(Vmma_controller_if___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vmma_controller_if___024root___eval_initial__TOP____Vfork_2__0\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    while (1U) {
        co_await vlSelfRef.__VtrigSched_hdac58424__0.trigger(0U, 
                                                             nullptr, 
                                                             "@(posedge tb_mma_controller.clk)", 
                                                             "test_monitor_tasks.svh", 
                                                             7);
        if (vlSymsp->TOP__tb_mma_controller__DOT__ia_if.load_ia_req) {
            if (VL_UNLIKELY(vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__load_ia_granted)) {
                VL_WRITEF_NX("\033[36m  [%0t] [GRANTED] IA Loader requesting and granted (icb_sel=%0#)\033[0m\n",0,
                             64,VL_TIME_UNITED_Q(1000),
                             -9,3,(IData)(vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__icb_sel));
            }
        }
        if (vlSymsp->TOP__tb_mma_controller__DOT__weight_if.load_weight_req) {
            if (VL_UNLIKELY(vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__load_weight_granted)) {
                VL_WRITEF_NX("\033[36m  [%0t] [GRANTED] Weight Loader requesting and granted (icb_sel=%0#)\033[0m\n",0,
                             64,VL_TIME_UNITED_Q(1000),
                             -9,3,(IData)(vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__icb_sel));
            }
        }
        if (vlSymsp->TOP__tb_mma_controller__DOT__bias_if.load_bias_req) {
            if (VL_UNLIKELY(vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__load_bias_granted)) {
                VL_WRITEF_NX("\033[36m  [%0t] [GRANTED] Bias Loader requesting and granted (icb_sel=%0#)\033[0m\n",0,
                             64,VL_TIME_UNITED_Q(1000),
                             -9,3,(IData)(vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__icb_sel));
            }
        }
        if (vlSymsp->TOP__tb_mma_controller__DOT__quant_if.load_quant_req) {
            if (VL_UNLIKELY(vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__load_quant_granted)) {
                VL_WRITEF_NX("\033[36m  [%0t] [GRANTED] Quant Loader requesting and granted (icb_sel=%0#)\033[0m\n",0,
                             64,VL_TIME_UNITED_Q(1000),
                             -9,3,(IData)(vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__icb_sel));
            }
        }
        if (vlSymsp->TOP__tb_mma_controller__DOT__oa_if.write_oa_req) {
            if (VL_UNLIKELY(vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__write_oa_granted)) {
                VL_WRITEF_NX("\033[36m  [%0t] [GRANTED] OA Writer requesting and granted (icb_sel=%0#)\033[0m\n",0,
                             64,VL_TIME_UNITED_Q(1000),
                             -9,3,(IData)(vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__icb_sel));
            }
        }
    }
}

#ifdef VL_DEBUG
VL_ATTR_COLD void Vmma_controller_if___024root___dump_triggers__stl(Vmma_controller_if___024root* vlSelf);
#endif  // VL_DEBUG

VL_ATTR_COLD void Vmma_controller_if___024root___eval_triggers__stl(Vmma_controller_if___024root* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vmma_controller_if___024root___eval_triggers__stl\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    vlSelfRef.__VstlTriggered.set(0U, (IData)(vlSelfRef.__VstlFirstIteration));
#ifdef VL_DEBUG
    if (VL_UNLIKELY(vlSymsp->_vm_contextp__->debug())) {
        Vmma_controller_if___024root___dump_triggers__stl(vlSelf);
    }
#endif
}
