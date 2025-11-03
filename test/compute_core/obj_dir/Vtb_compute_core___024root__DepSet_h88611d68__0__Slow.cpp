// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Design implementation internals
// See Vtb_compute_core.h for the primary calling header

#include "Vtb_compute_core__pch.h"
#include "Vtb_compute_core__Syms.h"
#include "Vtb_compute_core___024root.h"

VL_ATTR_COLD void Vtb_compute_core_tb_compute_core_if___eval_static__TOP__tb_compute_core__DOT__tb_if(Vtb_compute_core_tb_compute_core_if* vlSelf);
VL_ATTR_COLD void Vtb_compute_core___024root____Vm_traceActivitySetAll(Vtb_compute_core___024root* vlSelf);

VL_ATTR_COLD void Vtb_compute_core___024root___eval_static(Vtb_compute_core___024root* vlSelf) {
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_compute_core___024root___eval_static\n"); );
    Vtb_compute_core__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    auto& vlSelfRef = std::ref(*vlSelf).get();
    // Body
    Vtb_compute_core_tb_compute_core_if___eval_static__TOP__tb_compute_core__DOT__tb_if((&vlSymsp->TOP__tb_compute_core__DOT__tb_if));
    Vtb_compute_core___024root____Vm_traceActivitySetAll(vlSelf);
    vlSelfRef.__Vtrigprevexpr___TOP__tb_compute_core__DOT__clk__0 
        = vlSelfRef.tb_compute_core__DOT__clk;
    vlSelfRef.__Vtrigprevexpr___TOP__tb_compute_core__DOT__tb_if__cb__DOT__bias_in__0 
        = vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__bias_in;
    vlSelfRef.__Vtrigprevexpr___TOP__tb_compute_core__DOT__tb_if__cb__DOT__ia_is_init_data__0 
        = vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__ia_is_init_data;
    vlSelfRef.__Vtrigprevexpr___TOP__tb_compute_core__DOT__tb_if__cb__DOT__ia_calc_done__0 
        = vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__ia_calc_done;
    vlSelfRef.__Vtrigprevexpr___TOP__tb_compute_core__DOT__tb_if__cb__DOT__ia_row_valid__0 
        = vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__ia_row_valid;
    vlSelfRef.__Vtrigprevexpr___TOP__tb_compute_core__DOT__tb_if__cb__DOT__ia_vec_in__0 
        = vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__ia_vec_in;
    vlSelfRef.__Vtrigprevexpr___TOP__tb_compute_core__DOT__tb_if__cb__DOT__weight_in__0 
        = vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__weight_in;
    vlSelfRef.__Vtrigprevexpr___TOP__tb_compute_core__DOT__tb_if__cb__DOT__store_weight_req__0 
        = vlSymsp->TOP__tb_compute_core__DOT__tb_if.cb__DOT__store_weight_req;
    vlSelfRef.__Vtrigprevexpr___TOP__tb_compute_core__DOT____Vcellout__u_dut__partial_sum_calc_over__0 
        = vlSelfRef.tb_compute_core__DOT____Vcellout__u_dut__partial_sum_calc_over;
    vlSelfRef.__Vtrigprevexpr___TOP__tb_compute_core__DOT____Vcellout__u_dut__tile_calc_over__0 
        = vlSelfRef.tb_compute_core__DOT____Vcellout__u_dut__tile_calc_over;
}

VL_ATTR_COLD void Vtb_compute_core___024root___eval_initial__TOP(Vtb_compute_core___024root* vlSelf) {
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_compute_core___024root___eval_initial__TOP\n"); );
    Vtb_compute_core__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    auto& vlSelfRef = std::ref(*vlSelf).get();
    // Body
    vlSelfRef.tb_compute_core__DOT__clk = 0U;
    vlSelfRef.tb_compute_core__DOT__out_rows = 0U;
    vlSelfRef.tb_compute_core__DOT__errors = 0U;
    vlSelfRef.tb_compute_core__DOT__NUM_K = 0x10U;
    vlSelfRef.tb_compute_core__DOT__NUM_SEG = 4U;
    vlSymsp->_vm_contextp__->dumpfile(std::string{"wave.vcd"});
    vlSymsp->_traceDumpOpen();
}

#ifdef VL_DEBUG
VL_ATTR_COLD void Vtb_compute_core___024root___dump_triggers__stl(Vtb_compute_core___024root* vlSelf);
#endif  // VL_DEBUG

VL_ATTR_COLD void Vtb_compute_core___024root___eval_triggers__stl(Vtb_compute_core___024root* vlSelf) {
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_compute_core___024root___eval_triggers__stl\n"); );
    Vtb_compute_core__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    auto& vlSelfRef = std::ref(*vlSelf).get();
    // Body
    vlSelfRef.__VstlTriggered.setBit(0U, (IData)(vlSelfRef.__VstlFirstIteration));
#ifdef VL_DEBUG
    if (VL_UNLIKELY(vlSymsp->_vm_contextp__->debug())) {
        Vtb_compute_core___024root___dump_triggers__stl(vlSelf);
    }
#endif
}

VL_ATTR_COLD void Vtb_compute_core___024root___stl_sequent__TOP__0(Vtb_compute_core___024root* vlSelf);
void Vtb_compute_core_tb_compute_core_if___nba_sequent__TOP__tb_compute_core__DOT__tb_if__0(Vtb_compute_core_tb_compute_core_if* vlSelf);

VL_ATTR_COLD void Vtb_compute_core___024root___eval_stl(Vtb_compute_core___024root* vlSelf) {
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_compute_core___024root___eval_stl\n"); );
    Vtb_compute_core__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    auto& vlSelfRef = std::ref(*vlSelf).get();
    // Body
    if ((1ULL & vlSelfRef.__VstlTriggered.word(0U))) {
        Vtb_compute_core___024root___stl_sequent__TOP__0(vlSelf);
        Vtb_compute_core___024root____Vm_traceActivitySetAll(vlSelf);
        Vtb_compute_core_tb_compute_core_if___nba_sequent__TOP__tb_compute_core__DOT__tb_if__0((&vlSymsp->TOP__tb_compute_core__DOT__tb_if));
    }
}

VL_ATTR_COLD void Vtb_compute_core___024root___stl_sequent__TOP__0(Vtb_compute_core___024root* vlSelf) {
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_compute_core___024root___stl_sequent__TOP__0\n"); );
    Vtb_compute_core__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    auto& vlSelfRef = std::ref(*vlSelf).get();
    // Body
    vlSelfRef.tb_compute_core__DOT____Vcellinp__u_dut__bias_in[0U] 
        = vlSymsp->TOP__tb_compute_core__DOT__tb_if.bias_in
        [0U];
    vlSelfRef.tb_compute_core__DOT____Vcellinp__u_dut__bias_in[1U] 
        = vlSymsp->TOP__tb_compute_core__DOT__tb_if.bias_in
        [1U];
    vlSelfRef.tb_compute_core__DOT____Vcellinp__u_dut__bias_in[2U] 
        = vlSymsp->TOP__tb_compute_core__DOT__tb_if.bias_in
        [2U];
    vlSelfRef.tb_compute_core__DOT____Vcellinp__u_dut__bias_in[3U] 
        = vlSymsp->TOP__tb_compute_core__DOT__tb_if.bias_in
        [3U];
    vlSelfRef.tb_compute_core__DOT____Vcellinp__u_dut__ia_vec_in[0U] 
        = vlSymsp->TOP__tb_compute_core__DOT__tb_if.ia_vec_in
        [0U];
    vlSelfRef.tb_compute_core__DOT____Vcellinp__u_dut__ia_vec_in[1U] 
        = vlSymsp->TOP__tb_compute_core__DOT__tb_if.ia_vec_in
        [1U];
    vlSelfRef.tb_compute_core__DOT____Vcellinp__u_dut__ia_vec_in[2U] 
        = vlSymsp->TOP__tb_compute_core__DOT__tb_if.ia_vec_in
        [2U];
    vlSelfRef.tb_compute_core__DOT____Vcellinp__u_dut__ia_vec_in[3U] 
        = vlSymsp->TOP__tb_compute_core__DOT__tb_if.ia_vec_in
        [3U];
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__data_setup_out[0U] 
        = vlSymsp->TOP__tb_compute_core__DOT__tb_if.ia_vec_in
        [0U];
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__data_setup_out[1U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__1__KET____DOT__gen_delay_1__DOT__shift_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__data_setup_out[2U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__2__KET____DOT__gen_delay_n__DOT__shift_reg
        [1U];
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__data_setup_out[3U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__3__KET____DOT__gen_delay_n__DOT__shift_reg
        [2U];
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellout__u_data_setup__data_out[0U] 
        = vlSymsp->TOP__tb_compute_core__DOT__tb_if.ia_vec_in
        [0U];
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellout__u_data_setup__data_out[1U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__1__KET____DOT__gen_delay_1__DOT__shift_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellout__u_data_setup__data_out[2U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__2__KET____DOT__gen_delay_n__DOT__shift_reg
        [1U];
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellout__u_data_setup__data_out[3U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__3__KET____DOT__gen_delay_n__DOT__shift_reg
        [2U];
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellinp__u_data_setup__data_in[0U] 
        = vlSymsp->TOP__tb_compute_core__DOT__tb_if.ia_vec_in
        [0U];
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellinp__u_data_setup__data_in[1U] 
        = vlSymsp->TOP__tb_compute_core__DOT__tb_if.ia_vec_in
        [1U];
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellinp__u_data_setup__data_in[2U] 
        = vlSymsp->TOP__tb_compute_core__DOT__tb_if.ia_vec_in
        [2U];
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellinp__u_data_setup__data_in[3U] 
        = vlSymsp->TOP__tb_compute_core__DOT__tb_if.ia_vec_in
        [3U];
    vlSelfRef.tb_compute_core__DOT____Vcellinp__u_dut__weight_in[0U] 
        = vlSymsp->TOP__tb_compute_core__DOT__tb_if.weight_in
        [0U];
    vlSelfRef.tb_compute_core__DOT____Vcellinp__u_dut__weight_in[1U] 
        = vlSymsp->TOP__tb_compute_core__DOT__tb_if.weight_in
        [1U];
    vlSelfRef.tb_compute_core__DOT____Vcellinp__u_dut__weight_in[2U] 
        = vlSymsp->TOP__tb_compute_core__DOT__tb_if.weight_in
        [2U];
    vlSelfRef.tb_compute_core__DOT____Vcellinp__u_dut__weight_in[3U] 
        = vlSymsp->TOP__tb_compute_core__DOT__tb_if.weight_in
        [3U];
    vlSelfRef.tb_compute_core__DOT____Vcellout__u_dut__acc_data_out[0U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__acc_fifo
        [vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__read_ptr];
    vlSelfRef.tb_compute_core__DOT____Vcellout__u_dut__acc_data_out[1U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__acc_fifo
        [vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__read_ptr];
    vlSelfRef.tb_compute_core__DOT____Vcellout__u_dut__acc_data_out[2U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__acc_fifo
        [vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__read_ptr];
    vlSelfRef.tb_compute_core__DOT____Vcellout__u_dut__acc_data_out[3U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__acc_fifo
        [vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__read_ptr];
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellout__u_accumulator_array__data_out[0U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__acc_fifo
        [vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__read_ptr];
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellout__u_accumulator_array__data_out[1U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__acc_fifo
        [vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__read_ptr];
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellout__u_accumulator_array__data_out[2U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__acc_fifo
        [vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__read_ptr];
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellout__u_accumulator_array__data_out[3U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__acc_fifo
        [vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__read_ptr];
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe[0U][0U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__weight_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe[0U][0U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__data_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe[0U][1U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__weight_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe[0U][1U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__data_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe[0U][2U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__weight_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe[0U][2U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__data_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe[0U][3U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__weight_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe[0U][3U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__data_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe[1U][0U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__weight_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe[1U][0U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__data_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe[1U][1U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__weight_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe[1U][1U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__data_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe[1U][2U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__weight_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe[1U][2U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__data_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe[1U][3U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__weight_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe[1U][3U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__data_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe[2U][0U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__weight_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe[2U][0U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__data_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe[2U][1U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__weight_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe[2U][1U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__data_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe[2U][2U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__weight_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe[2U][2U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__data_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe[2U][3U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__weight_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe[2U][3U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__data_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe[3U][0U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__weight_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe[3U][0U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__data_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe[3U][1U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__weight_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe[3U][1U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__data_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe[3U][2U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__weight_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe[3U][2U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__data_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe[3U][3U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__weight_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe[3U][3U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__data_reg;
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__mult_result 
        = VL_MULS_III(32, VL_EXTENDS_II(32,16, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__data_reg)), 
                      VL_EXTENDS_II(32,8, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__weight_reg)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__mult_result 
        = VL_MULS_III(32, VL_EXTENDS_II(32,16, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__data_reg)), 
                      VL_EXTENDS_II(32,8, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__weight_reg)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__mult_result 
        = VL_MULS_III(32, VL_EXTENDS_II(32,16, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__data_reg)), 
                      VL_EXTENDS_II(32,8, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__weight_reg)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__mult_result 
        = VL_MULS_III(32, VL_EXTENDS_II(32,16, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__data_reg)), 
                      VL_EXTENDS_II(32,8, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__weight_reg)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__mult_result 
        = VL_MULS_III(32, VL_EXTENDS_II(32,16, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__data_reg)), 
                      VL_EXTENDS_II(32,8, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__weight_reg)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__mult_result 
        = VL_MULS_III(32, VL_EXTENDS_II(32,16, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__data_reg)), 
                      VL_EXTENDS_II(32,8, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__weight_reg)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__mult_result 
        = VL_MULS_III(32, VL_EXTENDS_II(32,16, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__data_reg)), 
                      VL_EXTENDS_II(32,8, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__weight_reg)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__mult_result 
        = VL_MULS_III(32, VL_EXTENDS_II(32,16, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__data_reg)), 
                      VL_EXTENDS_II(32,8, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__weight_reg)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__mult_result 
        = VL_MULS_III(32, VL_EXTENDS_II(32,16, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__data_reg)), 
                      VL_EXTENDS_II(32,8, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__weight_reg)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__mult_result 
        = VL_MULS_III(32, VL_EXTENDS_II(32,16, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__data_reg)), 
                      VL_EXTENDS_II(32,8, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__weight_reg)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__mult_result 
        = VL_MULS_III(32, VL_EXTENDS_II(32,16, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__data_reg)), 
                      VL_EXTENDS_II(32,8, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__weight_reg)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__mult_result 
        = VL_MULS_III(32, VL_EXTENDS_II(32,16, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__data_reg)), 
                      VL_EXTENDS_II(32,8, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__weight_reg)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__mult_result 
        = VL_MULS_III(32, VL_EXTENDS_II(32,16, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__data_reg)), 
                      VL_EXTENDS_II(32,8, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__weight_reg)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__mult_result 
        = VL_MULS_III(32, VL_EXTENDS_II(32,16, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__data_reg)), 
                      VL_EXTENDS_II(32,8, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__weight_reg)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__mult_result 
        = VL_MULS_III(32, VL_EXTENDS_II(32,16, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__data_reg)), 
                      VL_EXTENDS_II(32,8, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__weight_reg)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__mult_result 
        = VL_MULS_III(32, VL_EXTENDS_II(32,16, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__data_reg)), 
                      VL_EXTENDS_II(32,8, (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__weight_reg)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext 
        = (0x1ffffffffULL & ((((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_reg 
                                                >> 0x1fU))) 
                               << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_reg))) 
                             + (((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__mult_result 
                                                  >> 0x1fU))) 
                                 << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__mult_result)))));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext 
        = (0x1ffffffffULL & ((((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_reg 
                                                >> 0x1fU))) 
                               << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_reg))) 
                             + (((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__mult_result 
                                                  >> 0x1fU))) 
                                 << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__mult_result)))));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext 
        = (0x1ffffffffULL & ((((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_reg 
                                                >> 0x1fU))) 
                               << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_reg))) 
                             + (((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__mult_result 
                                                  >> 0x1fU))) 
                                 << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__mult_result)))));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext 
        = (0x1ffffffffULL & ((((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_reg 
                                                >> 0x1fU))) 
                               << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_reg))) 
                             + (((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__mult_result 
                                                  >> 0x1fU))) 
                                 << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__mult_result)))));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext 
        = (0x1ffffffffULL & ((((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_reg 
                                                >> 0x1fU))) 
                               << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_reg))) 
                             + (((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__mult_result 
                                                  >> 0x1fU))) 
                                 << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__mult_result)))));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext 
        = (0x1ffffffffULL & ((((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_reg 
                                                >> 0x1fU))) 
                               << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_reg))) 
                             + (((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__mult_result 
                                                  >> 0x1fU))) 
                                 << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__mult_result)))));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext 
        = (0x1ffffffffULL & ((((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_reg 
                                                >> 0x1fU))) 
                               << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_reg))) 
                             + (((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__mult_result 
                                                  >> 0x1fU))) 
                                 << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__mult_result)))));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext 
        = (0x1ffffffffULL & ((((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_reg 
                                                >> 0x1fU))) 
                               << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_reg))) 
                             + (((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__mult_result 
                                                  >> 0x1fU))) 
                                 << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__mult_result)))));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext 
        = (0x1ffffffffULL & ((((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_reg 
                                                >> 0x1fU))) 
                               << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_reg))) 
                             + (((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__mult_result 
                                                  >> 0x1fU))) 
                                 << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__mult_result)))));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext 
        = (0x1ffffffffULL & ((((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_reg 
                                                >> 0x1fU))) 
                               << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_reg))) 
                             + (((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__mult_result 
                                                  >> 0x1fU))) 
                                 << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__mult_result)))));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext 
        = (0x1ffffffffULL & ((((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_reg 
                                                >> 0x1fU))) 
                               << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_reg))) 
                             + (((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__mult_result 
                                                  >> 0x1fU))) 
                                 << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__mult_result)))));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext 
        = (0x1ffffffffULL & ((((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_reg 
                                                >> 0x1fU))) 
                               << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_reg))) 
                             + (((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__mult_result 
                                                  >> 0x1fU))) 
                                 << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__mult_result)))));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext 
        = (0x1ffffffffULL & ((((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_reg 
                                                >> 0x1fU))) 
                               << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_reg))) 
                             + (((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__mult_result 
                                                  >> 0x1fU))) 
                                 << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__mult_result)))));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext 
        = (0x1ffffffffULL & ((((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_reg 
                                                >> 0x1fU))) 
                               << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_reg))) 
                             + (((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__mult_result 
                                                  >> 0x1fU))) 
                                 << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__mult_result)))));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext 
        = (0x1ffffffffULL & ((((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_reg 
                                                >> 0x1fU))) 
                               << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_reg))) 
                             + (((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__mult_result 
                                                  >> 0x1fU))) 
                                 << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__mult_result)))));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext 
        = (0x1ffffffffULL & ((((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_reg 
                                                >> 0x1fU))) 
                               << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_reg))) 
                             + (((QData)((IData)((vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__mult_result 
                                                  >> 0x1fU))) 
                                 << 0x20U) | (QData)((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__mult_result)))));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe[0U][0U] 
        = (VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext)
            ? 0x7fffffffU : (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext)
                              ? 0x80000000U : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe[0U][1U] 
        = (VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext)
            ? 0x7fffffffU : (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext)
                              ? 0x80000000U : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe[0U][2U] 
        = (VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext)
            ? 0x7fffffffU : (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext)
                              ? 0x80000000U : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe[0U][3U] 
        = (VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext)
            ? 0x7fffffffU : (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext)
                              ? 0x80000000U : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe[1U][0U] 
        = (VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext)
            ? 0x7fffffffU : (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext)
                              ? 0x80000000U : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe[1U][1U] 
        = (VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext)
            ? 0x7fffffffU : (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext)
                              ? 0x80000000U : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe[1U][2U] 
        = (VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext)
            ? 0x7fffffffU : (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext)
                              ? 0x80000000U : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe[1U][3U] 
        = (VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext)
            ? 0x7fffffffU : (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext)
                              ? 0x80000000U : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe[2U][0U] 
        = (VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext)
            ? 0x7fffffffU : (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext)
                              ? 0x80000000U : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe[2U][1U] 
        = (VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext)
            ? 0x7fffffffU : (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext)
                              ? 0x80000000U : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe[2U][2U] 
        = (VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext)
            ? 0x7fffffffU : (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext)
                              ? 0x80000000U : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe[2U][3U] 
        = (VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext)
            ? 0x7fffffffU : (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext)
                              ? 0x80000000U : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe[3U][0U] 
        = (VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext)
            ? 0x7fffffffU : (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext)
                              ? 0x80000000U : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe[3U][1U] 
        = (VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext)
            ? 0x7fffffffU : (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext)
                              ? 0x80000000U : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe[3U][2U] 
        = (VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext)
            ? 0x7fffffffU : (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext)
                              ? 0x80000000U : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe[3U][3U] 
        = (VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext)
            ? 0x7fffffffU : (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext)
                              ? 0x80000000U : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext)));
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__sa_sum_out[0U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
        [3U][0U];
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__sa_sum_out[1U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
        [3U][1U];
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__sa_sum_out[2U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
        [3U][2U];
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT__sa_sum_out[3U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
        [3U][3U];
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellinp__u_accumulator_array__data_in[0U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__sa_sum_out
        [0U];
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellinp__u_accumulator_array__data_in[1U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__sa_sum_out
        [1U];
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellinp__u_accumulator_array__data_in[2U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__sa_sum_out
        [2U];
    vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellinp__u_accumulator_array__data_in[3U] 
        = vlSelfRef.tb_compute_core__DOT__u_dut__DOT__sa_sum_out
        [3U];
}
