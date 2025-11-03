// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Design implementation internals
// See Vtb_compute_core.h for the primary calling header

#include "Vtb_compute_core__pch.h"
#include "Vtb_compute_core_tb_compute_core_if.h"

VL_INLINE_OPT void Vtb_compute_core_tb_compute_core_if___react_sequent__TOP__tb_compute_core__DOT__tb_if__0(Vtb_compute_core_tb_compute_core_if* vlSelf) {
    VL_DEBUG_IF(VL_DBG_MSGF("+        Vtb_compute_core_tb_compute_core_if___react_sequent__TOP__tb_compute_core__DOT__tb_if__0\n"); );
    Vtb_compute_core__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    auto& vlSelfRef = std::ref(*vlSelf).get();
    // Body
    if ((((IData)(vlSelfRef.__Vclocking_prev__cb__DOT__ia_is_init_data) 
          != (IData)(vlSelfRef.cb__DOT__ia_is_init_data)) 
         & vlSelfRef.cb.isTriggered())) {
        vlSelfRef.ia_is_init_data = vlSelfRef.cb__DOT__ia_is_init_data;
        vlSelfRef.__Vclocking_prev__cb__DOT__ia_is_init_data 
            = vlSelfRef.cb__DOT__ia_is_init_data;
    }
}

VL_INLINE_OPT void Vtb_compute_core_tb_compute_core_if___react_sequent__TOP__tb_compute_core__DOT__tb_if__1(Vtb_compute_core_tb_compute_core_if* vlSelf) {
    VL_DEBUG_IF(VL_DBG_MSGF("+        Vtb_compute_core_tb_compute_core_if___react_sequent__TOP__tb_compute_core__DOT__tb_if__1\n"); );
    Vtb_compute_core__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    auto& vlSelfRef = std::ref(*vlSelf).get();
    // Body
    if ((((IData)(vlSelfRef.__Vclocking_prev__cb__DOT__ia_calc_done) 
          != (IData)(vlSelfRef.cb__DOT__ia_calc_done)) 
         & vlSelfRef.cb.isTriggered())) {
        vlSelfRef.ia_calc_done = vlSelfRef.cb__DOT__ia_calc_done;
        vlSelfRef.__Vclocking_prev__cb__DOT__ia_calc_done 
            = vlSelfRef.cb__DOT__ia_calc_done;
    }
}

VL_INLINE_OPT void Vtb_compute_core_tb_compute_core_if___react_sequent__TOP__tb_compute_core__DOT__tb_if__2(Vtb_compute_core_tb_compute_core_if* vlSelf) {
    VL_DEBUG_IF(VL_DBG_MSGF("+        Vtb_compute_core_tb_compute_core_if___react_sequent__TOP__tb_compute_core__DOT__tb_if__2\n"); );
    Vtb_compute_core__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    auto& vlSelfRef = std::ref(*vlSelf).get();
    // Body
    if ((((IData)(vlSelfRef.__Vclocking_prev__cb__DOT__ia_row_valid) 
          != (IData)(vlSelfRef.cb__DOT__ia_row_valid)) 
         & vlSelfRef.cb.isTriggered())) {
        vlSelfRef.ia_row_valid = vlSelfRef.cb__DOT__ia_row_valid;
        vlSelfRef.__Vclocking_prev__cb__DOT__ia_row_valid 
            = vlSelfRef.cb__DOT__ia_row_valid;
    }
}

VL_INLINE_OPT void Vtb_compute_core_tb_compute_core_if___react_sequent__TOP__tb_compute_core__DOT__tb_if__3(Vtb_compute_core_tb_compute_core_if* vlSelf) {
    VL_DEBUG_IF(VL_DBG_MSGF("+        Vtb_compute_core_tb_compute_core_if___react_sequent__TOP__tb_compute_core__DOT__tb_if__3\n"); );
    Vtb_compute_core__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    auto& vlSelfRef = std::ref(*vlSelf).get();
    // Body
    if ((((IData)(vlSelfRef.__Vclocking_prev__cb__DOT__store_weight_req) 
          != (IData)(vlSelfRef.cb__DOT__store_weight_req)) 
         & vlSelfRef.cb.isTriggered())) {
        vlSelfRef.store_weight_req = vlSelfRef.cb__DOT__store_weight_req;
        vlSelfRef.__Vclocking_prev__cb__DOT__store_weight_req 
            = vlSelfRef.cb__DOT__store_weight_req;
    }
}

VL_INLINE_OPT void Vtb_compute_core_tb_compute_core_if___react_sequent__TOP__tb_compute_core__DOT__tb_if__4(Vtb_compute_core_tb_compute_core_if* vlSelf) {
    VL_DEBUG_IF(VL_DBG_MSGF("+        Vtb_compute_core_tb_compute_core_if___react_sequent__TOP__tb_compute_core__DOT__tb_if__4\n"); );
    Vtb_compute_core__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    auto& vlSelfRef = std::ref(*vlSelf).get();
    // Body
    if ((((((vlSelfRef.__Vclocking_prev__cb__DOT__bias_in
             [0U] != vlSelfRef.cb__DOT__bias_in[0U]) 
            || (vlSelfRef.__Vclocking_prev__cb__DOT__bias_in
                [1U] != vlSelfRef.cb__DOT__bias_in[1U])) 
           || (vlSelfRef.__Vclocking_prev__cb__DOT__bias_in
               [2U] != vlSelfRef.cb__DOT__bias_in[2U])) 
          || (vlSelfRef.__Vclocking_prev__cb__DOT__bias_in
              [3U] != vlSelfRef.cb__DOT__bias_in[3U])) 
         & vlSelfRef.cb.isTriggered())) {
        vlSelfRef.bias_in[0U] = vlSelfRef.cb__DOT__bias_in
            [0U];
        vlSelfRef.__Vclocking_prev__cb__DOT__bias_in[0U] 
            = vlSelfRef.cb__DOT__bias_in[0U];
        vlSelfRef.bias_in[1U] = vlSelfRef.cb__DOT__bias_in
            [1U];
        vlSelfRef.__Vclocking_prev__cb__DOT__bias_in[1U] 
            = vlSelfRef.cb__DOT__bias_in[1U];
        vlSelfRef.bias_in[2U] = vlSelfRef.cb__DOT__bias_in
            [2U];
        vlSelfRef.__Vclocking_prev__cb__DOT__bias_in[2U] 
            = vlSelfRef.cb__DOT__bias_in[2U];
        vlSelfRef.bias_in[3U] = vlSelfRef.cb__DOT__bias_in
            [3U];
        vlSelfRef.__Vclocking_prev__cb__DOT__bias_in[3U] 
            = vlSelfRef.cb__DOT__bias_in[3U];
    }
}

VL_INLINE_OPT void Vtb_compute_core_tb_compute_core_if___react_sequent__TOP__tb_compute_core__DOT__tb_if__5(Vtb_compute_core_tb_compute_core_if* vlSelf) {
    VL_DEBUG_IF(VL_DBG_MSGF("+        Vtb_compute_core_tb_compute_core_if___react_sequent__TOP__tb_compute_core__DOT__tb_if__5\n"); );
    Vtb_compute_core__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    auto& vlSelfRef = std::ref(*vlSelf).get();
    // Body
    if ((((((vlSelfRef.__Vclocking_prev__cb__DOT__weight_in
             [0U] != vlSelfRef.cb__DOT__weight_in[0U]) 
            || (vlSelfRef.__Vclocking_prev__cb__DOT__weight_in
                [1U] != vlSelfRef.cb__DOT__weight_in
                [1U])) || (vlSelfRef.__Vclocking_prev__cb__DOT__weight_in
                           [2U] != vlSelfRef.cb__DOT__weight_in
                           [2U])) || (vlSelfRef.__Vclocking_prev__cb__DOT__weight_in
                                      [3U] != vlSelfRef.cb__DOT__weight_in
                                      [3U])) & vlSelfRef.cb.isTriggered())) {
        vlSelfRef.weight_in[0U] = vlSelfRef.cb__DOT__weight_in
            [0U];
        vlSelfRef.__Vclocking_prev__cb__DOT__weight_in[0U] 
            = vlSelfRef.cb__DOT__weight_in[0U];
        vlSelfRef.weight_in[1U] = vlSelfRef.cb__DOT__weight_in
            [1U];
        vlSelfRef.__Vclocking_prev__cb__DOT__weight_in[1U] 
            = vlSelfRef.cb__DOT__weight_in[1U];
        vlSelfRef.weight_in[2U] = vlSelfRef.cb__DOT__weight_in
            [2U];
        vlSelfRef.__Vclocking_prev__cb__DOT__weight_in[2U] 
            = vlSelfRef.cb__DOT__weight_in[2U];
        vlSelfRef.weight_in[3U] = vlSelfRef.cb__DOT__weight_in
            [3U];
        vlSelfRef.__Vclocking_prev__cb__DOT__weight_in[3U] 
            = vlSelfRef.cb__DOT__weight_in[3U];
    }
}

VL_INLINE_OPT void Vtb_compute_core_tb_compute_core_if___react_sequent__TOP__tb_compute_core__DOT__tb_if__6(Vtb_compute_core_tb_compute_core_if* vlSelf) {
    VL_DEBUG_IF(VL_DBG_MSGF("+        Vtb_compute_core_tb_compute_core_if___react_sequent__TOP__tb_compute_core__DOT__tb_if__6\n"); );
    Vtb_compute_core__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    auto& vlSelfRef = std::ref(*vlSelf).get();
    // Body
    if ((((((vlSelfRef.__Vclocking_prev__cb__DOT__ia_vec_in
             [0U] != vlSelfRef.cb__DOT__ia_vec_in[0U]) 
            || (vlSelfRef.__Vclocking_prev__cb__DOT__ia_vec_in
                [1U] != vlSelfRef.cb__DOT__ia_vec_in
                [1U])) || (vlSelfRef.__Vclocking_prev__cb__DOT__ia_vec_in
                           [2U] != vlSelfRef.cb__DOT__ia_vec_in
                           [2U])) || (vlSelfRef.__Vclocking_prev__cb__DOT__ia_vec_in
                                      [3U] != vlSelfRef.cb__DOT__ia_vec_in
                                      [3U])) & vlSelfRef.cb.isTriggered())) {
        vlSelfRef.ia_vec_in[0U] = vlSelfRef.cb__DOT__ia_vec_in
            [0U];
        vlSelfRef.__Vclocking_prev__cb__DOT__ia_vec_in[0U] 
            = vlSelfRef.cb__DOT__ia_vec_in[0U];
        vlSelfRef.ia_vec_in[1U] = vlSelfRef.cb__DOT__ia_vec_in
            [1U];
        vlSelfRef.__Vclocking_prev__cb__DOT__ia_vec_in[1U] 
            = vlSelfRef.cb__DOT__ia_vec_in[1U];
        vlSelfRef.ia_vec_in[2U] = vlSelfRef.cb__DOT__ia_vec_in
            [2U];
        vlSelfRef.__Vclocking_prev__cb__DOT__ia_vec_in[2U] 
            = vlSelfRef.cb__DOT__ia_vec_in[2U];
        vlSelfRef.ia_vec_in[3U] = vlSelfRef.cb__DOT__ia_vec_in
            [3U];
        vlSelfRef.__Vclocking_prev__cb__DOT__ia_vec_in[3U] 
            = vlSelfRef.cb__DOT__ia_vec_in[3U];
    }
}

std::string VL_TO_STRING(const Vtb_compute_core_tb_compute_core_if* obj) {
    VL_DEBUG_IF(VL_DBG_MSGF("+        Vtb_compute_core_tb_compute_core_if::VL_TO_STRING\n"); );
    // Body
    return (obj ? obj->name() : "null");
}
