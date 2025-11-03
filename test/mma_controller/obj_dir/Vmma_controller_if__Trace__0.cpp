// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Tracing implementation internals
#include "verilated_vcd_c.h"
#include "Vmma_controller_if__Syms.h"


void Vmma_controller_if___024root__trace_chg_0_sub_0(Vmma_controller_if___024root* vlSelf, VerilatedVcd::Buffer* bufp);

void Vmma_controller_if___024root__trace_chg_0(void* voidSelf, VerilatedVcd::Buffer* bufp) {
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vmma_controller_if___024root__trace_chg_0\n"); );
    // Init
    Vmma_controller_if___024root* const __restrict vlSelf VL_ATTR_UNUSED = static_cast<Vmma_controller_if___024root*>(voidSelf);
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    if (VL_UNLIKELY(!vlSymsp->__Vm_activity)) return;
    // Body
    Vmma_controller_if___024root__trace_chg_0_sub_0((&vlSymsp->TOP), bufp);
}

void Vmma_controller_if___024root__trace_chg_0_sub_0(Vmma_controller_if___024root* vlSelf, VerilatedVcd::Buffer* bufp) {
    (void)vlSelf;  // Prevent unused variable warning
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vmma_controller_if___024root__trace_chg_0_sub_0\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Init
    uint32_t* const oldp VL_ATTR_UNUSED = bufp->oldp(vlSymsp->__Vm_baseCode + 1);
    // Body
    if (VL_UNLIKELY(vlSelfRef.__Vm_traceActivity[1U])) {
        bufp->chgBit(oldp+0,((0U == (IData)(vlSelfRef.tb_mma_controller__DOT__dut__DOT__current_state))));
        bufp->chgCData(oldp+1,(vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__icb_sel),3);
        bufp->chgBit(oldp+2,(vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__init_cfg_ia));
        bufp->chgBit(oldp+3,(vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__init_cfg_weight));
        bufp->chgBit(oldp+4,(vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__init_cfg_bias));
        bufp->chgBit(oldp+5,(vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__init_cfg_requant));
        bufp->chgBit(oldp+6,(vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__init_cfg_oa));
        bufp->chgBit(oldp+7,(vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__use_16bits));
        bufp->chgBit(oldp+8,(vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__load_ia_granted));
        bufp->chgBit(oldp+9,(vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__send_ia_trigger));
        bufp->chgBit(oldp+10,(vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__load_weight_granted));
        bufp->chgBit(oldp+11,(vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__send_weight_trigger));
        bufp->chgBit(oldp+12,(vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__load_bias_granted));
        bufp->chgBit(oldp+13,(vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__load_quant_granted));
        bufp->chgBit(oldp+14,(vlSelfRef.tb_mma_controller__DOT____Vcellout__dut__write_oa_granted));
        bufp->chgCData(oldp+15,(vlSelfRef.tb_mma_controller__DOT__dut__DOT__err_code),2);
        bufp->chgCData(oldp+16,(vlSelfRef.tb_mma_controller__DOT__dut__DOT__current_state),4);
        bufp->chgBit(oldp+17,(vlSelfRef.tb_mma_controller__DOT__dut__DOT__cfg_16bits_ia_reg));
        bufp->chgBit(oldp+18,(vlSelfRef.tb_mma_controller__DOT__dut__DOT__config_error));
        bufp->chgCData(oldp+19,(vlSelfRef.tb_mma_controller__DOT__dut__DOT__error_type),2);
        bufp->chgCData(oldp+20,(vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__current_master),3);
        bufp->chgBit(oldp+21,(vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__bus_busy));
        bufp->chgCData(oldp+22,(vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__priority_queue[0]),3);
        bufp->chgCData(oldp+23,(vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__priority_queue[1]),3);
        bufp->chgCData(oldp+24,(vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__priority_queue[2]),3);
        bufp->chgCData(oldp+25,(vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__priority_queue[3]),3);
        bufp->chgCData(oldp+26,(vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__next_priority_queue[0]),3);
        bufp->chgCData(oldp+27,(vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__next_priority_queue[1]),3);
        bufp->chgCData(oldp+28,(vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__next_priority_queue[2]),3);
        bufp->chgCData(oldp+29,(vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__next_priority_queue[3]),3);
        bufp->chgCData(oldp+30,(vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__unnamedblk1__DOT__next_device),3);
    }
    bufp->chgBit(oldp+31,(vlSelfRef.tb_mma_controller__DOT__clk));
    bufp->chgBit(oldp+32,(vlSelfRef.tb_mma_controller__DOT__rst_n));
    bufp->chgBit(oldp+33,(vlSymsp->TOP__tb_mma_controller__DOT__ctrl_if.calc_start));
    bufp->chgBit(oldp+34,(vlSymsp->TOP__tb_mma_controller__DOT__ctrl_if.cfg_16bits_ia));
    bufp->chgBit(oldp+35,(vlSymsp->TOP__tb_mma_controller__DOT__comp_if.partial_sum_calc_over));
    bufp->chgBit(oldp+36,(vlSymsp->TOP__tb_mma_controller__DOT__ia_if.load_ia_req));
    bufp->chgBit(oldp+37,(vlSymsp->TOP__tb_mma_controller__DOT__ia_if.ia_sending_done));
    bufp->chgBit(oldp+38,(vlSymsp->TOP__tb_mma_controller__DOT__ia_if.ia_data_valid));
    bufp->chgBit(oldp+39,(vlSymsp->TOP__tb_mma_controller__DOT__weight_if.load_weight_req));
    bufp->chgBit(oldp+40,(vlSymsp->TOP__tb_mma_controller__DOT__weight_if.weight_sending_done));
    bufp->chgBit(oldp+41,(vlSymsp->TOP__tb_mma_controller__DOT__weight_if.weight_data_valid));
    bufp->chgBit(oldp+42,(vlSymsp->TOP__tb_mma_controller__DOT__bias_if.load_bias_req));
    bufp->chgBit(oldp+43,(vlSymsp->TOP__tb_mma_controller__DOT__bias_if.bias_valid));
    bufp->chgBit(oldp+44,(vlSymsp->TOP__tb_mma_controller__DOT__quant_if.load_quant_req));
    bufp->chgBit(oldp+45,(vlSymsp->TOP__tb_mma_controller__DOT__quant_if.quant_params_valid));
    bufp->chgBit(oldp+46,(vlSymsp->TOP__tb_mma_controller__DOT__ctrl_if.fifo_full_flag));
    bufp->chgBit(oldp+47,(vlSymsp->TOP__tb_mma_controller__DOT__oa_if.write_oa_req));
    bufp->chgBit(oldp+48,(vlSymsp->TOP__tb_mma_controller__DOT__oa_if.write_done));
    bufp->chgBit(oldp+49,(vlSymsp->TOP__tb_mma_controller__DOT__oa_if.oa_calc_over));
    bufp->chgBit(oldp+50,(((IData)(vlSymsp->TOP__tb_mma_controller__DOT__oa_if.oa_calc_over) 
                           | ((7U == (IData)(vlSelfRef.tb_mma_controller__DOT__dut__DOT__current_state)) 
                              | (8U == (IData)(vlSelfRef.tb_mma_controller__DOT__dut__DOT__current_state))))));
    bufp->chgCData(oldp+51,(vlSelfRef.tb_mma_controller__DOT__dut__DOT__next_state),4);
    bufp->chgBit(oldp+52,((1U & ((~ (IData)(vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__bus_busy)) 
                                 | ((IData)(vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__bus_busy) 
                                    & (IData)(vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__current_done))))));
    bufp->chgBit(oldp+53,(vlSelfRef.tb_mma_controller__DOT__dut__DOT__u_icb_arbiter__DOT__current_done));
    bufp->chgBit(oldp+54,(vlSymsp->TOP__tb_mma_controller__DOT__ia_if.__PVT__ia_calc_done));
    bufp->chgBit(oldp+55,(vlSymsp->TOP__tb_mma_controller__DOT__comp_if.tile_calc_over));
}

void Vmma_controller_if___024root__trace_cleanup(void* voidSelf, VerilatedVcd* /*unused*/) {
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vmma_controller_if___024root__trace_cleanup\n"); );
    // Init
    Vmma_controller_if___024root* const __restrict vlSelf VL_ATTR_UNUSED = static_cast<Vmma_controller_if___024root*>(voidSelf);
    Vmma_controller_if__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    // Body
    vlSymsp->__Vm_activity = false;
    vlSymsp->TOP.__Vm_traceActivity[0U] = 0U;
    vlSymsp->TOP.__Vm_traceActivity[1U] = 0U;
}
