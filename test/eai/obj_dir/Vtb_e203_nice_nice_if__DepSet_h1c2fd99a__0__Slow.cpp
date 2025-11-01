// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Design implementation internals
// See Vtb_e203_nice.h for the primary calling header

#include "Vtb_e203_nice__pch.h"
#include "Vtb_e203_nice_nice_if.h"

VL_ATTR_COLD void Vtb_e203_nice_nice_if___eval_static__TOP__tb_e203_nice__DOT__nice_if_inst(Vtb_e203_nice_nice_if* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vtb_e203_nice__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+        Vtb_e203_nice_nice_if___eval_static__TOP__tb_e203_nice__DOT__nice_if_inst\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    vlSelfRef.cb__DOT__req_valid = vlSelfRef.req_valid;
    vlSelfRef.__Vclocking_prev__cb__DOT__req_valid 
        = vlSelfRef.cb__DOT__req_valid;
    vlSelfRef.cb__DOT__req_inst = vlSelfRef.req_inst;
    vlSelfRef.__Vclocking_prev__cb__DOT__req_inst = vlSelfRef.cb__DOT__req_inst;
    vlSelfRef.cb__DOT__req_rs1 = vlSelfRef.req_rs1;
    vlSelfRef.__Vclocking_prev__cb__DOT__req_rs1 = vlSelfRef.cb__DOT__req_rs1;
    vlSelfRef.cb__DOT__req_rs2 = vlSelfRef.req_rs2;
    vlSelfRef.__Vclocking_prev__cb__DOT__req_rs2 = vlSelfRef.cb__DOT__req_rs2;
    vlSelfRef.cb__DOT__rsp_ready = vlSelfRef.rsp_ready;
    vlSelfRef.__Vclocking_prev__cb__DOT__rsp_ready 
        = vlSelfRef.cb__DOT__rsp_ready;
    vlSelfRef.cb__DOT__icb_cmd_valid = vlSelfRef.icb_cmd_valid;
    vlSelfRef.__Vclocking_prev__cb__DOT__icb_cmd_valid 
        = vlSelfRef.cb__DOT__icb_cmd_valid;
    vlSelfRef.cb__DOT__icb_cmd_addr = vlSelfRef.icb_cmd_addr;
    vlSelfRef.__Vclocking_prev__cb__DOT__icb_cmd_addr 
        = vlSelfRef.cb__DOT__icb_cmd_addr;
    vlSelfRef.cb__DOT__icb_cmd_read = vlSelfRef.icb_cmd_read;
    vlSelfRef.__Vclocking_prev__cb__DOT__icb_cmd_read 
        = vlSelfRef.cb__DOT__icb_cmd_read;
    vlSelfRef.cb__DOT__icb_cmd_wdata = vlSelfRef.icb_cmd_wdata;
    vlSelfRef.__Vclocking_prev__cb__DOT__icb_cmd_wdata 
        = vlSelfRef.cb__DOT__icb_cmd_wdata;
    vlSelfRef.cb__DOT__icb_cmd_wmask = vlSelfRef.icb_cmd_wmask;
    vlSelfRef.__Vclocking_prev__cb__DOT__icb_cmd_wmask 
        = vlSelfRef.cb__DOT__icb_cmd_wmask;
    vlSelfRef.cb__DOT__icb_rsp_ready = vlSelfRef.icb_rsp_ready;
    vlSelfRef.__Vclocking_prev__cb__DOT__icb_rsp_ready 
        = vlSelfRef.cb__DOT__icb_rsp_ready;
}

VL_ATTR_COLD void Vtb_e203_nice_nice_if___ctor_var_reset(Vtb_e203_nice_nice_if* vlSelf) {
    (void)vlSelf;  // Prevent unused variable warning
    Vtb_e203_nice__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+        Vtb_e203_nice_nice_if___ctor_var_reset\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    vlSelf->clk = VL_RAND_RESET_I(1);
    vlSelf->rst_n = VL_RAND_RESET_I(1);
    vlSelf->req_valid = VL_RAND_RESET_I(1);
    vlSelf->req_inst = VL_RAND_RESET_I(32);
    vlSelf->req_rs1 = VL_RAND_RESET_I(32);
    vlSelf->req_rs2 = VL_RAND_RESET_I(32);
    vlSelf->rsp_ready = VL_RAND_RESET_I(1);
    vlSelf->icb_cmd_valid = VL_RAND_RESET_I(1);
    vlSelf->icb_cmd_addr = VL_RAND_RESET_I(32);
    vlSelf->icb_cmd_read = VL_RAND_RESET_I(1);
    vlSelf->icb_cmd_wdata = VL_RAND_RESET_I(32);
    vlSelf->icb_cmd_wmask = VL_RAND_RESET_I(4);
    vlSelf->icb_rsp_valid = VL_RAND_RESET_I(1);
    vlSelf->icb_rsp_ready = VL_RAND_RESET_I(1);
    vlSelf->cb__DOT__icb_rsp_ready = VL_RAND_RESET_I(1);
    vlSelf->cb__DOT__icb_cmd_wmask = VL_RAND_RESET_I(4);
    vlSelf->cb__DOT__icb_cmd_wdata = VL_RAND_RESET_I(32);
    vlSelf->cb__DOT__icb_cmd_read = VL_RAND_RESET_I(1);
    vlSelf->cb__DOT__icb_cmd_addr = VL_RAND_RESET_I(32);
    vlSelf->cb__DOT__icb_cmd_valid = VL_RAND_RESET_I(1);
    vlSelf->cb__DOT__rsp_ready = VL_RAND_RESET_I(1);
    vlSelf->cb__DOT__req_rs2 = VL_RAND_RESET_I(32);
    vlSelf->cb__DOT__req_rs1 = VL_RAND_RESET_I(32);
    vlSelf->cb__DOT__req_inst = VL_RAND_RESET_I(32);
    vlSelf->cb__DOT__req_valid = VL_RAND_RESET_I(1);
    vlSelf->__Vclocking_prev__cb__DOT__req_valid = VL_RAND_RESET_I(1);
    vlSelf->__Vclocking_prev__cb__DOT__req_inst = VL_RAND_RESET_I(32);
    vlSelf->__Vclocking_prev__cb__DOT__req_rs1 = VL_RAND_RESET_I(32);
    vlSelf->__Vclocking_prev__cb__DOT__req_rs2 = VL_RAND_RESET_I(32);
    vlSelf->__Vclocking_prev__cb__DOT__rsp_ready = VL_RAND_RESET_I(1);
    vlSelf->__Vclocking_prev__cb__DOT__icb_cmd_valid = VL_RAND_RESET_I(1);
    vlSelf->__Vclocking_prev__cb__DOT__icb_cmd_addr = VL_RAND_RESET_I(32);
    vlSelf->__Vclocking_prev__cb__DOT__icb_cmd_read = VL_RAND_RESET_I(1);
    vlSelf->__Vclocking_prev__cb__DOT__icb_cmd_wdata = VL_RAND_RESET_I(32);
    vlSelf->__Vclocking_prev__cb__DOT__icb_cmd_wmask = VL_RAND_RESET_I(4);
    vlSelf->__Vclocking_prev__cb__DOT__icb_rsp_ready = VL_RAND_RESET_I(1);
}
