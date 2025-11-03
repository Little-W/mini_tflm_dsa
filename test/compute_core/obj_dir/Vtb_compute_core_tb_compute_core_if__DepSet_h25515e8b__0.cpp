// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Design implementation internals
// See Vtb_compute_core.h for the primary calling header

#include "Vtb_compute_core__pch.h"
#include "Vtb_compute_core__Syms.h"
#include "Vtb_compute_core_tb_compute_core_if.h"

VL_INLINE_OPT void Vtb_compute_core_tb_compute_core_if___nba_sequent__TOP__tb_compute_core__DOT__tb_if__0(Vtb_compute_core_tb_compute_core_if* vlSelf) {
    VL_DEBUG_IF(VL_DBG_MSGF("+        Vtb_compute_core_tb_compute_core_if___nba_sequent__TOP__tb_compute_core__DOT__tb_if__0\n"); );
    Vtb_compute_core__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    auto& vlSelfRef = std::ref(*vlSelf).get();
    // Body
    vlSelfRef.acc_data_out[0U] = vlSymsp->TOP.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__acc_fifo
        [vlSymsp->TOP.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__read_ptr];
    vlSelfRef.acc_data_out[1U] = vlSymsp->TOP.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__acc_fifo
        [vlSymsp->TOP.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__read_ptr];
    vlSelfRef.acc_data_out[2U] = vlSymsp->TOP.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__acc_fifo
        [vlSymsp->TOP.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__read_ptr];
    vlSelfRef.acc_data_out[3U] = vlSymsp->TOP.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__acc_fifo
        [vlSymsp->TOP.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__read_ptr];
}

VL_INLINE_OPT void Vtb_compute_core_tb_compute_core_if___obs_sequent__TOP__tb_compute_core__DOT__tb_if__0(Vtb_compute_core_tb_compute_core_if* vlSelf) {
    VL_DEBUG_IF(VL_DBG_MSGF("+        Vtb_compute_core_tb_compute_core_if___obs_sequent__TOP__tb_compute_core__DOT__tb_if__0\n"); );
    Vtb_compute_core__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    auto& vlSelfRef = std::ref(*vlSelf).get();
    // Body
    vlSymsp->fireEvent(vlSelfRef.cb);
}
