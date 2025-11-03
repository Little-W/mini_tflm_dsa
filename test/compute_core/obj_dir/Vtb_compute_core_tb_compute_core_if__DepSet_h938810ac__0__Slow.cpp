// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Design implementation internals
// See Vtb_compute_core.h for the primary calling header

#include "Vtb_compute_core__pch.h"
#include "Vtb_compute_core_tb_compute_core_if.h"

VL_ATTR_COLD void Vtb_compute_core_tb_compute_core_if___eval_static__TOP__tb_compute_core__DOT__tb_if(Vtb_compute_core_tb_compute_core_if* vlSelf) {
    VL_DEBUG_IF(VL_DBG_MSGF("+        Vtb_compute_core_tb_compute_core_if___eval_static__TOP__tb_compute_core__DOT__tb_if\n"); );
    Vtb_compute_core__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    auto& vlSelfRef = std::ref(*vlSelf).get();
    // Body
    vlSelfRef.cb__DOT__store_weight_req = vlSelfRef.store_weight_req;
    vlSelfRef.__Vclocking_prev__cb__DOT__store_weight_req 
        = vlSelfRef.cb__DOT__store_weight_req;
    vlSelfRef.cb__DOT__weight_in[0U] = vlSelfRef.weight_in
        [0U];
    vlSelfRef.cb__DOT__weight_in[1U] = vlSelfRef.weight_in
        [1U];
    vlSelfRef.cb__DOT__weight_in[2U] = vlSelfRef.weight_in
        [2U];
    vlSelfRef.cb__DOT__weight_in[3U] = vlSelfRef.weight_in
        [3U];
    vlSelfRef.__Vclocking_prev__cb__DOT__weight_in[0U] 
        = vlSelfRef.cb__DOT__weight_in[0U];
    vlSelfRef.__Vclocking_prev__cb__DOT__weight_in[1U] 
        = vlSelfRef.cb__DOT__weight_in[1U];
    vlSelfRef.__Vclocking_prev__cb__DOT__weight_in[2U] 
        = vlSelfRef.cb__DOT__weight_in[2U];
    vlSelfRef.__Vclocking_prev__cb__DOT__weight_in[3U] 
        = vlSelfRef.cb__DOT__weight_in[3U];
    vlSelfRef.cb__DOT__ia_vec_in[0U] = vlSelfRef.ia_vec_in
        [0U];
    vlSelfRef.cb__DOT__ia_vec_in[1U] = vlSelfRef.ia_vec_in
        [1U];
    vlSelfRef.cb__DOT__ia_vec_in[2U] = vlSelfRef.ia_vec_in
        [2U];
    vlSelfRef.cb__DOT__ia_vec_in[3U] = vlSelfRef.ia_vec_in
        [3U];
    vlSelfRef.__Vclocking_prev__cb__DOT__ia_vec_in[0U] 
        = vlSelfRef.cb__DOT__ia_vec_in[0U];
    vlSelfRef.__Vclocking_prev__cb__DOT__ia_vec_in[1U] 
        = vlSelfRef.cb__DOT__ia_vec_in[1U];
    vlSelfRef.__Vclocking_prev__cb__DOT__ia_vec_in[2U] 
        = vlSelfRef.cb__DOT__ia_vec_in[2U];
    vlSelfRef.__Vclocking_prev__cb__DOT__ia_vec_in[3U] 
        = vlSelfRef.cb__DOT__ia_vec_in[3U];
    vlSelfRef.cb__DOT__ia_row_valid = vlSelfRef.ia_row_valid;
    vlSelfRef.__Vclocking_prev__cb__DOT__ia_row_valid 
        = vlSelfRef.cb__DOT__ia_row_valid;
    vlSelfRef.cb__DOT__ia_calc_done = vlSelfRef.ia_calc_done;
    vlSelfRef.__Vclocking_prev__cb__DOT__ia_calc_done 
        = vlSelfRef.cb__DOT__ia_calc_done;
    vlSelfRef.cb__DOT__ia_is_init_data = vlSelfRef.ia_is_init_data;
    vlSelfRef.__Vclocking_prev__cb__DOT__ia_is_init_data 
        = vlSelfRef.cb__DOT__ia_is_init_data;
    vlSelfRef.cb__DOT__bias_in[0U] = vlSelfRef.bias_in
        [0U];
    vlSelfRef.cb__DOT__bias_in[1U] = vlSelfRef.bias_in
        [1U];
    vlSelfRef.cb__DOT__bias_in[2U] = vlSelfRef.bias_in
        [2U];
    vlSelfRef.cb__DOT__bias_in[3U] = vlSelfRef.bias_in
        [3U];
    vlSelfRef.__Vclocking_prev__cb__DOT__bias_in[0U] 
        = vlSelfRef.cb__DOT__bias_in[0U];
    vlSelfRef.__Vclocking_prev__cb__DOT__bias_in[1U] 
        = vlSelfRef.cb__DOT__bias_in[1U];
    vlSelfRef.__Vclocking_prev__cb__DOT__bias_in[2U] 
        = vlSelfRef.cb__DOT__bias_in[2U];
    vlSelfRef.__Vclocking_prev__cb__DOT__bias_in[3U] 
        = vlSelfRef.cb__DOT__bias_in[3U];
}

VL_ATTR_COLD void Vtb_compute_core_tb_compute_core_if___ctor_var_reset(Vtb_compute_core_tb_compute_core_if* vlSelf) {
    VL_DEBUG_IF(VL_DBG_MSGF("+        Vtb_compute_core_tb_compute_core_if___ctor_var_reset\n"); );
    Vtb_compute_core__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    auto& vlSelfRef = std::ref(*vlSelf).get();
    // Body
    const uint64_t __VscopeHash = VL_MURMUR64_HASH(vlSelf->name());
    vlSelf->clk = VL_SCOPED_RAND_RESET_I(1, __VscopeHash, 16707436170211756652ull);
    vlSelf->store_weight_req = VL_SCOPED_RAND_RESET_I(1, __VscopeHash, 14793720530513866194ull);
    for (int __Vi0 = 0; __Vi0 < 4; ++__Vi0) {
        vlSelf->weight_in[__Vi0] = VL_SCOPED_RAND_RESET_I(8, __VscopeHash, 17664990524737627050ull);
    }
    for (int __Vi0 = 0; __Vi0 < 4; ++__Vi0) {
        vlSelf->ia_vec_in[__Vi0] = VL_SCOPED_RAND_RESET_I(16, __VscopeHash, 15866055415044269824ull);
    }
    vlSelf->ia_row_valid = VL_SCOPED_RAND_RESET_I(1, __VscopeHash, 1896708595106470020ull);
    vlSelf->ia_calc_done = VL_SCOPED_RAND_RESET_I(1, __VscopeHash, 9035685912482068377ull);
    vlSelf->ia_is_init_data = VL_SCOPED_RAND_RESET_I(1, __VscopeHash, 3292895698440576764ull);
    for (int __Vi0 = 0; __Vi0 < 4; ++__Vi0) {
        vlSelf->bias_in[__Vi0] = VL_SCOPED_RAND_RESET_I(32, __VscopeHash, 13525725657989020303ull);
    }
    for (int __Vi0 = 0; __Vi0 < 4; ++__Vi0) {
        vlSelf->acc_data_out[__Vi0] = VL_SCOPED_RAND_RESET_I(32, __VscopeHash, 2817369934831272435ull);
    }
    for (int __Vi0 = 0; __Vi0 < 4; ++__Vi0) {
        vlSelf->cb__DOT__bias_in[__Vi0] = VL_SCOPED_RAND_RESET_I(32, __VscopeHash, 15460389136751488953ull);
    }
    vlSelf->cb__DOT__ia_is_init_data = VL_SCOPED_RAND_RESET_I(1, __VscopeHash, 13601915236240652101ull);
    vlSelf->cb__DOT__ia_calc_done = VL_SCOPED_RAND_RESET_I(1, __VscopeHash, 7207606534386932019ull);
    vlSelf->cb__DOT__ia_row_valid = VL_SCOPED_RAND_RESET_I(1, __VscopeHash, 1275261173960092779ull);
    for (int __Vi0 = 0; __Vi0 < 4; ++__Vi0) {
        vlSelf->cb__DOT__ia_vec_in[__Vi0] = VL_SCOPED_RAND_RESET_I(16, __VscopeHash, 13807983322546823510ull);
    }
    for (int __Vi0 = 0; __Vi0 < 4; ++__Vi0) {
        vlSelf->cb__DOT__weight_in[__Vi0] = VL_SCOPED_RAND_RESET_I(8, __VscopeHash, 13354473892838876648ull);
    }
    vlSelf->cb__DOT__store_weight_req = VL_SCOPED_RAND_RESET_I(1, __VscopeHash, 16408690130235182035ull);
    vlSelf->__Vclocking_prev__cb__DOT__store_weight_req = VL_SCOPED_RAND_RESET_I(1, __VscopeHash, 15610044321141512849ull);
    for (int __Vi0 = 0; __Vi0 < 4; ++__Vi0) {
        vlSelf->__Vclocking_prev__cb__DOT__weight_in[__Vi0] = VL_SCOPED_RAND_RESET_I(8, __VscopeHash, 8683294772885265009ull);
    }
    for (int __Vi0 = 0; __Vi0 < 4; ++__Vi0) {
        vlSelf->__Vclocking_prev__cb__DOT__ia_vec_in[__Vi0] = VL_SCOPED_RAND_RESET_I(16, __VscopeHash, 4329905417518576207ull);
    }
    vlSelf->__Vclocking_prev__cb__DOT__ia_row_valid = VL_SCOPED_RAND_RESET_I(1, __VscopeHash, 12488815242930680065ull);
    vlSelf->__Vclocking_prev__cb__DOT__ia_calc_done = VL_SCOPED_RAND_RESET_I(1, __VscopeHash, 890410276245692220ull);
    vlSelf->__Vclocking_prev__cb__DOT__ia_is_init_data = VL_SCOPED_RAND_RESET_I(1, __VscopeHash, 1662715145817882755ull);
    for (int __Vi0 = 0; __Vi0 < 4; ++__Vi0) {
        vlSelf->__Vclocking_prev__cb__DOT__bias_in[__Vi0] = VL_SCOPED_RAND_RESET_I(32, __VscopeHash, 8800976742439729164ull);
    }
}
