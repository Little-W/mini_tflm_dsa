// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Design internal header
// See Vtb_compute_core.h for the primary calling header

#ifndef VERILATED_VTB_COMPUTE_CORE___024ROOT_H_
#define VERILATED_VTB_COMPUTE_CORE___024ROOT_H_  // guard

#include "verilated.h"
#include "verilated_timing.h"
class Vtb_compute_core_tb_compute_core_if;


class Vtb_compute_core__Syms;

class alignas(VL_CACHE_LINE_BYTES) Vtb_compute_core___024root final : public VerilatedModule {
  public:
    // CELLS
    Vtb_compute_core_tb_compute_core_if* __PVT__tb_compute_core__DOT__tb_if;

    // DESIGN SPECIFIC STATE
    // Anonymous structures to workaround compiler member-count bugs
    struct {
        CData/*0:0*/ tb_compute_core__DOT__clk;
        CData/*0:0*/ tb_compute_core__DOT____Vcellout__u_dut__partial_sum_calc_over;
        CData/*0:0*/ tb_compute_core__DOT____Vcellout__u_dut__tile_calc_over;
        CData/*7:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__weight_reg;
        CData/*7:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__weight_reg;
        CData/*7:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__weight_reg;
        CData/*7:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__weight_reg;
        CData/*7:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__weight_reg;
        CData/*7:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__weight_reg;
        CData/*7:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__weight_reg;
        CData/*7:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__weight_reg;
        CData/*7:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__weight_reg;
        CData/*7:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__weight_reg;
        CData/*7:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__weight_reg;
        CData/*7:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__weight_reg;
        CData/*7:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__weight_reg;
        CData/*7:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__weight_reg;
        CData/*7:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__weight_reg;
        CData/*7:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__weight_reg;
        CData/*0:0*/ tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__calc_done_o_d;
        CData/*0:0*/ tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__input_valid_chain_d;
        CData/*0:0*/ tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__input_valid_i_d;
        CData/*1:0*/ tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__read_ptr;
        CData/*0:0*/ tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__is_init_data_reg;
        CData/*0:0*/ tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__input_valid_reg;
        CData/*0:0*/ tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__calc_done_reg;
        CData/*1:0*/ tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__write_ptr;
        CData/*0:0*/ tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__input_valid_i_d;
        CData/*0:0*/ tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__is_init_data_reg;
        CData/*0:0*/ tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__input_valid_reg;
        CData/*0:0*/ tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__calc_done_reg;
        CData/*1:0*/ tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__write_ptr;
        CData/*0:0*/ tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__input_valid_i_d;
        CData/*0:0*/ tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__is_init_data_reg;
        CData/*0:0*/ tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__input_valid_reg;
        CData/*0:0*/ tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__calc_done_reg;
        CData/*1:0*/ tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__write_ptr;
        CData/*0:0*/ tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__input_valid_i_d;
        CData/*0:0*/ tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__is_init_data_reg;
        CData/*0:0*/ tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__input_valid_reg;
        CData/*0:0*/ tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__calc_done_reg;
        CData/*1:0*/ tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__write_ptr;
        CData/*0:0*/ tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__input_valid_i_d;
        CData/*0:0*/ __VdlyVal__tb_compute_core__DOT__clk__v0;
        CData/*0:0*/ __VdlySet__tb_compute_core__DOT__clk__v0;
        CData/*0:0*/ __VstlFirstIteration;
        CData/*0:0*/ __Vtrigprevexpr___TOP__tb_compute_core__DOT__clk__0;
        CData/*0:0*/ __Vtrigprevexpr___TOP__tb_compute_core__DOT__tb_if__cb__DOT__ia_is_init_data__0;
        CData/*0:0*/ __Vtrigprevexpr___TOP__tb_compute_core__DOT__tb_if__cb__DOT__ia_calc_done__0;
        CData/*0:0*/ __Vtrigprevexpr___TOP__tb_compute_core__DOT__tb_if__cb__DOT__ia_row_valid__0;
        CData/*0:0*/ __Vtrigprevexpr___TOP__tb_compute_core__DOT__tb_if__cb__DOT__store_weight_req__0;
        CData/*0:0*/ __Vtrigprevexpr___TOP__tb_compute_core__DOT____Vcellout__u_dut__partial_sum_calc_over__0;
        CData/*0:0*/ __Vtrigprevexpr___TOP__tb_compute_core__DOT____Vcellout__u_dut__tile_calc_over__0;
        CData/*0:0*/ __VactDidInit;
        CData/*0:0*/ __VactContinue;
        CData/*0:0*/ __VnbaContinue;
        CData/*0:0*/ __VobsContinue;
        SData/*15:0*/ tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__1__KET____DOT__gen_delay_1__DOT__shift_reg;
        SData/*15:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__data_reg;
        SData/*15:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__data_reg;
        SData/*15:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__data_reg;
        SData/*15:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__data_reg;
        SData/*15:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__data_reg;
        SData/*15:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__data_reg;
    };
    struct {
        SData/*15:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__data_reg;
        SData/*15:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__data_reg;
        SData/*15:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__data_reg;
        SData/*15:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__data_reg;
        SData/*15:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__data_reg;
        SData/*15:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__data_reg;
        SData/*15:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__data_reg;
        SData/*15:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__data_reg;
        SData/*15:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__data_reg;
        SData/*15:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__data_reg;
        IData/*31:0*/ tb_compute_core__DOT__out_rows;
        IData/*31:0*/ tb_compute_core__DOT__errors;
        IData/*31:0*/ tb_compute_core__DOT__idx;
        IData/*31:0*/ tb_compute_core__DOT__NUM_K;
        IData/*31:0*/ tb_compute_core__DOT__NUM_SEG;
        IData/*31:0*/ tb_compute_core__DOT__unnamedblk1__DOT__c;
        IData/*31:0*/ tb_compute_core__DOT__unnamedblk2__DOT__i;
        IData/*31:0*/ tb_compute_core__DOT__unnamedblk3__DOT__i;
        IData/*31:0*/ tb_compute_core__DOT__unnamedblk4__DOT__seg;
        IData/*31:0*/ tb_compute_core__DOT__unnamedblk5__DOT__r;
        IData/*31:0*/ tb_compute_core__DOT__unnamedblk5__DOT__unnamedblk6__DOT__c;
        IData/*31:0*/ tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__2__KET____DOT__gen_delay_n__DOT__k;
        IData/*31:0*/ tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__3__KET____DOT__gen_delay_n__DOT__k;
        IData/*31:0*/ tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__unnamedblk1__DOT__m;
        IData/*31:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_reg;
        IData/*31:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__mult_result;
        IData/*31:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_reg;
        IData/*31:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__mult_result;
        IData/*31:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_reg;
        IData/*31:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__mult_result;
        IData/*31:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_reg;
        IData/*31:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__mult_result;
        IData/*31:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_reg;
        IData/*31:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__mult_result;
        IData/*31:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_reg;
        IData/*31:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__mult_result;
        IData/*31:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_reg;
        IData/*31:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__mult_result;
        IData/*31:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_reg;
        IData/*31:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__mult_result;
        IData/*31:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_reg;
        IData/*31:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__mult_result;
        IData/*31:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_reg;
        IData/*31:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__mult_result;
        IData/*31:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_reg;
        IData/*31:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__mult_result;
        IData/*31:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_reg;
        IData/*31:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__mult_result;
        IData/*31:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_reg;
        IData/*31:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__mult_result;
        IData/*31:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_reg;
        IData/*31:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__mult_result;
        IData/*31:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_reg;
        IData/*31:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__mult_result;
        IData/*31:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_reg;
        IData/*31:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__mult_result;
        IData/*31:0*/ __VactIterCount;
        IData/*31:0*/ __VnbaIterCount;
        IData/*31:0*/ __VobsIterCount;
        QData/*32:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext;
        QData/*32:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext;
        QData/*32:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext;
        QData/*32:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext;
        QData/*32:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext;
    };
    struct {
        QData/*32:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext;
        QData/*32:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext;
        QData/*32:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext;
        QData/*32:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext;
        QData/*32:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext;
        QData/*32:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext;
        QData/*32:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext;
        QData/*32:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext;
        QData/*32:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext;
        QData/*32:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext;
        QData/*32:0*/ tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext;
        QData/*32:0*/ tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__unnamedblk1__DOT__sum;
        QData/*32:0*/ tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__unnamedblk1__DOT__sum;
        QData/*32:0*/ tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__unnamedblk1__DOT__sum;
        QData/*32:0*/ tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__unnamedblk1__DOT__sum;
        VlUnpacked<CData/*7:0*/, 64> tb_compute_core__DOT__weight_mem_raw;
        VlUnpacked<SData/*15:0*/, 64> tb_compute_core__DOT__ia_mem_raw;
        VlUnpacked<IData/*31:0*/, 16> tb_compute_core__DOT__weight_mem;
        VlUnpacked<IData/*31:0*/, 32> tb_compute_core__DOT__ia_mem;
        VlUnpacked<IData/*31:0*/, 16> tb_compute_core__DOT__exp_mem;
        VlUnpacked<IData/*31:0*/, 4> tb_compute_core__DOT__bias_mem;
        VlUnpacked<IData/*31:0*/, 16> tb_compute_core__DOT__out_buf;
        VlUnpacked<VlUnpacked<CData/*7:0*/, 4>, 4> tb_compute_core__DOT__tile_buf;
        VlUnpacked<IData/*31:0*/, 4> tb_compute_core__DOT____Vcellout__u_dut__acc_data_out;
        VlUnpacked<IData/*31:0*/, 4> tb_compute_core__DOT____Vcellinp__u_dut__bias_in;
        VlUnpacked<SData/*15:0*/, 4> tb_compute_core__DOT____Vcellinp__u_dut__ia_vec_in;
        VlUnpacked<CData/*7:0*/, 4> tb_compute_core__DOT____Vcellinp__u_dut__weight_in;
        VlUnpacked<SData/*15:0*/, 4> tb_compute_core__DOT__u_dut__DOT__data_setup_out;
        VlUnpacked<IData/*31:0*/, 4> tb_compute_core__DOT__u_dut__DOT__sa_sum_out;
        VlUnpacked<SData/*15:0*/, 4> tb_compute_core__DOT__u_dut__DOT____Vcellout__u_data_setup__data_out;
        VlUnpacked<SData/*15:0*/, 4> tb_compute_core__DOT__u_dut__DOT____Vcellinp__u_data_setup__data_in;
        VlUnpacked<IData/*31:0*/, 4> tb_compute_core__DOT__u_dut__DOT____Vcellout__u_accumulator_array__data_out;
        VlUnpacked<IData/*31:0*/, 4> tb_compute_core__DOT__u_dut__DOT____Vcellinp__u_accumulator_array__data_in;
        VlUnpacked<SData/*15:0*/, 2> tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__2__KET____DOT__gen_delay_n__DOT__shift_reg;
        VlUnpacked<SData/*15:0*/, 3> tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__3__KET____DOT__gen_delay_n__DOT__shift_reg;
        VlUnpacked<CData/*0:0*/, 4> tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__input_valid_shift;
        VlUnpacked<CData/*0:0*/, 4> tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__calc_done_shift;
        VlUnpacked<CData/*0:0*/, 4> tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__is_init_data_shift;
        VlUnpacked<VlUnpacked<SData/*15:0*/, 4>, 4> tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe;
        VlUnpacked<VlUnpacked<CData/*7:0*/, 4>, 4> tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe;
        VlUnpacked<VlUnpacked<IData/*31:0*/, 4>, 4> tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe;
        VlUnpacked<IData/*31:0*/, 4> tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__acc_fifo;
        VlUnpacked<IData/*31:0*/, 4> tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__acc_fifo;
        VlUnpacked<IData/*31:0*/, 4> tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__acc_fifo;
        VlUnpacked<IData/*31:0*/, 4> tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__acc_fifo;
        VlUnpacked<IData/*31:0*/, 4> __Vtrigprevexpr___TOP__tb_compute_core__DOT__tb_if__cb__DOT__bias_in__0;
        VlUnpacked<SData/*15:0*/, 4> __Vtrigprevexpr___TOP__tb_compute_core__DOT__tb_if__cb__DOT__ia_vec_in__0;
        VlUnpacked<CData/*7:0*/, 4> __Vtrigprevexpr___TOP__tb_compute_core__DOT__tb_if__cb__DOT__weight_in__0;
        VlUnpacked<CData/*0:0*/, 7> __Vm_traceActivity;
    };
    VlDelayScheduler __VdlySched;
    VlTriggerScheduler __VtrigSched_h08f02b2e__0;
    VlTriggerScheduler __VtrigSched_h76832c6c__0;
    VlTriggerScheduler __VtrigSched_hf86aeebc__0;
    VlTriggerVec<1> __VstlTriggered;
    VlTriggerVec<12> __VactTriggered;
    VlTriggerVec<12> __VnbaTriggered;
    VlTriggerVec<12> __VobsTriggered;
    VlTriggerVec<12> __VreactTriggered;

    // INTERNAL VARIABLES
    Vtb_compute_core__Syms* const vlSymsp;

    // CONSTRUCTORS
    Vtb_compute_core___024root(Vtb_compute_core__Syms* symsp, const char* v__name);
    ~Vtb_compute_core___024root();
    VL_UNCOPYABLE(Vtb_compute_core___024root);

    // INTERNAL METHODS
    void __Vconfigure(bool first);
};


#endif  // guard
