// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Design implementation internals
// See Vtb_e203_nice.h for the primary calling header

#include "Vtb_e203_nice__pch.h"
#include "Vtb_e203_nice_nice_if.h"

VL_INLINE_OPT void Vtb_e203_nice_nice_if___obs_sequent__TOP__tb_e203_nice__DOT__nice_if_inst__0(Vtb_e203_nice_nice_if* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vtb_e203_nice__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+        Vtb_e203_nice_nice_if___obs_sequent__TOP__tb_e203_nice__DOT__nice_if_inst__0\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    vlSelfRef.cb.fire();
}

VL_INLINE_OPT void Vtb_e203_nice_nice_if___react_sequent__TOP__tb_e203_nice__DOT__nice_if_inst__0(Vtb_e203_nice_nice_if* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vtb_e203_nice__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+        Vtb_e203_nice_nice_if___react_sequent__TOP__tb_e203_nice__DOT__nice_if_inst__0\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    if (((IData)(vlSelfRef.__Vclocking_prev__cb__DOT__icb_rsp_ready) 
         != (IData)(vlSelfRef.cb__DOT__icb_rsp_ready))) {
        vlSelfRef.icb_rsp_ready = vlSelfRef.cb__DOT__icb_rsp_ready;
        vlSelfRef.__Vclocking_prev__cb__DOT__icb_rsp_ready 
            = vlSelfRef.cb__DOT__icb_rsp_ready;
    }
    if (((IData)(vlSelfRef.__Vclocking_prev__cb__DOT__icb_cmd_wmask) 
         != (IData)(vlSelfRef.cb__DOT__icb_cmd_wmask))) {
        vlSelfRef.icb_cmd_wmask = vlSelfRef.cb__DOT__icb_cmd_wmask;
        vlSelfRef.__Vclocking_prev__cb__DOT__icb_cmd_wmask 
            = vlSelfRef.cb__DOT__icb_cmd_wmask;
    }
    if ((vlSelfRef.__Vclocking_prev__cb__DOT__icb_cmd_wdata 
         != vlSelfRef.cb__DOT__icb_cmd_wdata)) {
        vlSelfRef.icb_cmd_wdata = vlSelfRef.cb__DOT__icb_cmd_wdata;
        vlSelfRef.__Vclocking_prev__cb__DOT__icb_cmd_wdata 
            = vlSelfRef.cb__DOT__icb_cmd_wdata;
    }
    if (((IData)(vlSelfRef.__Vclocking_prev__cb__DOT__icb_cmd_read) 
         != (IData)(vlSelfRef.cb__DOT__icb_cmd_read))) {
        vlSelfRef.icb_cmd_read = vlSelfRef.cb__DOT__icb_cmd_read;
        vlSelfRef.__Vclocking_prev__cb__DOT__icb_cmd_read 
            = vlSelfRef.cb__DOT__icb_cmd_read;
    }
    if ((vlSelfRef.__Vclocking_prev__cb__DOT__icb_cmd_addr 
         != vlSelfRef.cb__DOT__icb_cmd_addr)) {
        vlSelfRef.icb_cmd_addr = vlSelfRef.cb__DOT__icb_cmd_addr;
        vlSelfRef.__Vclocking_prev__cb__DOT__icb_cmd_addr 
            = vlSelfRef.cb__DOT__icb_cmd_addr;
    }
    if (((IData)(vlSelfRef.__Vclocking_prev__cb__DOT__icb_cmd_valid) 
         != (IData)(vlSelfRef.cb__DOT__icb_cmd_valid))) {
        vlSelfRef.icb_cmd_valid = vlSelfRef.cb__DOT__icb_cmd_valid;
        vlSelfRef.__Vclocking_prev__cb__DOT__icb_cmd_valid 
            = vlSelfRef.cb__DOT__icb_cmd_valid;
    }
    if ((vlSelfRef.__Vclocking_prev__cb__DOT__req_rs2 
         != vlSelfRef.cb__DOT__req_rs2)) {
        vlSelfRef.req_rs2 = vlSelfRef.cb__DOT__req_rs2;
        vlSelfRef.__Vclocking_prev__cb__DOT__req_rs2 
            = vlSelfRef.cb__DOT__req_rs2;
    }
    if ((vlSelfRef.__Vclocking_prev__cb__DOT__req_rs1 
         != vlSelfRef.cb__DOT__req_rs1)) {
        vlSelfRef.req_rs1 = vlSelfRef.cb__DOT__req_rs1;
        vlSelfRef.__Vclocking_prev__cb__DOT__req_rs1 
            = vlSelfRef.cb__DOT__req_rs1;
    }
    if (((IData)(vlSelfRef.__Vclocking_prev__cb__DOT__req_valid) 
         != (IData)(vlSelfRef.cb__DOT__req_valid))) {
        vlSelfRef.req_valid = vlSelfRef.cb__DOT__req_valid;
        vlSelfRef.__Vclocking_prev__cb__DOT__req_valid 
            = vlSelfRef.cb__DOT__req_valid;
    }
    if (((IData)(vlSelfRef.__Vclocking_prev__cb__DOT__rsp_ready) 
         != (IData)(vlSelfRef.cb__DOT__rsp_ready))) {
        vlSelfRef.rsp_ready = vlSelfRef.cb__DOT__rsp_ready;
        vlSelfRef.__Vclocking_prev__cb__DOT__rsp_ready 
            = vlSelfRef.cb__DOT__rsp_ready;
    }
    if ((vlSelfRef.__Vclocking_prev__cb__DOT__req_inst 
         != vlSelfRef.cb__DOT__req_inst)) {
        vlSelfRef.req_inst = vlSelfRef.cb__DOT__req_inst;
        vlSelfRef.__Vclocking_prev__cb__DOT__req_inst 
            = vlSelfRef.cb__DOT__req_inst;
    }
}

std::string VL_TO_STRING(const Vtb_e203_nice_nice_if* obj) {
    VL_DEBUG_IF(VL_DBG_MSGF("+        Vtb_e203_nice_nice_if::VL_TO_STRING\n"); );
    // Body
    return (obj ? obj->name() : "null");
}
