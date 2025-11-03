// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Tracing implementation internals
#include "verilated_vcd_c.h"
#include "Vtb_compute_core__Syms.h"


void Vtb_compute_core___024root__trace_chg_0_sub_0(Vtb_compute_core___024root* vlSelf, VerilatedVcd::Buffer* bufp);

void Vtb_compute_core___024root__trace_chg_0(void* voidSelf, VerilatedVcd::Buffer* bufp) {
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_compute_core___024root__trace_chg_0\n"); );
    // Init
    Vtb_compute_core___024root* const __restrict vlSelf VL_ATTR_UNUSED = static_cast<Vtb_compute_core___024root*>(voidSelf);
    Vtb_compute_core__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    if (VL_UNLIKELY(!vlSymsp->__Vm_activity)) return;
    // Body
    Vtb_compute_core___024root__trace_chg_0_sub_0((&vlSymsp->TOP), bufp);
}

void Vtb_compute_core___024root__trace_chg_0_sub_0(Vtb_compute_core___024root* vlSelf, VerilatedVcd::Buffer* bufp) {
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_compute_core___024root__trace_chg_0_sub_0\n"); );
    Vtb_compute_core__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    auto& vlSelfRef = std::ref(*vlSelf).get();
    // Init
    uint32_t* const oldp VL_ATTR_UNUSED = bufp->oldp(vlSymsp->__Vm_baseCode + 1);
    // Body
    if (VL_UNLIKELY(((vlSelfRef.__Vm_traceActivity[1U] 
                      | vlSelfRef.__Vm_traceActivity
                      [2U])))) {
        bufp->chgIData(oldp+0,(vlSelfRef.tb_compute_core__DOT__weight_mem[0]),32);
        bufp->chgIData(oldp+1,(vlSelfRef.tb_compute_core__DOT__weight_mem[1]),32);
        bufp->chgIData(oldp+2,(vlSelfRef.tb_compute_core__DOT__weight_mem[2]),32);
        bufp->chgIData(oldp+3,(vlSelfRef.tb_compute_core__DOT__weight_mem[3]),32);
        bufp->chgIData(oldp+4,(vlSelfRef.tb_compute_core__DOT__weight_mem[4]),32);
        bufp->chgIData(oldp+5,(vlSelfRef.tb_compute_core__DOT__weight_mem[5]),32);
        bufp->chgIData(oldp+6,(vlSelfRef.tb_compute_core__DOT__weight_mem[6]),32);
        bufp->chgIData(oldp+7,(vlSelfRef.tb_compute_core__DOT__weight_mem[7]),32);
        bufp->chgIData(oldp+8,(vlSelfRef.tb_compute_core__DOT__weight_mem[8]),32);
        bufp->chgIData(oldp+9,(vlSelfRef.tb_compute_core__DOT__weight_mem[9]),32);
        bufp->chgIData(oldp+10,(vlSelfRef.tb_compute_core__DOT__weight_mem[10]),32);
        bufp->chgIData(oldp+11,(vlSelfRef.tb_compute_core__DOT__weight_mem[11]),32);
        bufp->chgIData(oldp+12,(vlSelfRef.tb_compute_core__DOT__weight_mem[12]),32);
        bufp->chgIData(oldp+13,(vlSelfRef.tb_compute_core__DOT__weight_mem[13]),32);
        bufp->chgIData(oldp+14,(vlSelfRef.tb_compute_core__DOT__weight_mem[14]),32);
        bufp->chgIData(oldp+15,(vlSelfRef.tb_compute_core__DOT__weight_mem[15]),32);
        bufp->chgIData(oldp+16,(vlSelfRef.tb_compute_core__DOT__ia_mem[0]),32);
        bufp->chgIData(oldp+17,(vlSelfRef.tb_compute_core__DOT__ia_mem[1]),32);
        bufp->chgIData(oldp+18,(vlSelfRef.tb_compute_core__DOT__ia_mem[2]),32);
        bufp->chgIData(oldp+19,(vlSelfRef.tb_compute_core__DOT__ia_mem[3]),32);
        bufp->chgIData(oldp+20,(vlSelfRef.tb_compute_core__DOT__ia_mem[4]),32);
        bufp->chgIData(oldp+21,(vlSelfRef.tb_compute_core__DOT__ia_mem[5]),32);
        bufp->chgIData(oldp+22,(vlSelfRef.tb_compute_core__DOT__ia_mem[6]),32);
        bufp->chgIData(oldp+23,(vlSelfRef.tb_compute_core__DOT__ia_mem[7]),32);
        bufp->chgIData(oldp+24,(vlSelfRef.tb_compute_core__DOT__ia_mem[8]),32);
        bufp->chgIData(oldp+25,(vlSelfRef.tb_compute_core__DOT__ia_mem[9]),32);
        bufp->chgIData(oldp+26,(vlSelfRef.tb_compute_core__DOT__ia_mem[10]),32);
        bufp->chgIData(oldp+27,(vlSelfRef.tb_compute_core__DOT__ia_mem[11]),32);
        bufp->chgIData(oldp+28,(vlSelfRef.tb_compute_core__DOT__ia_mem[12]),32);
        bufp->chgIData(oldp+29,(vlSelfRef.tb_compute_core__DOT__ia_mem[13]),32);
        bufp->chgIData(oldp+30,(vlSelfRef.tb_compute_core__DOT__ia_mem[14]),32);
        bufp->chgIData(oldp+31,(vlSelfRef.tb_compute_core__DOT__ia_mem[15]),32);
        bufp->chgIData(oldp+32,(vlSelfRef.tb_compute_core__DOT__ia_mem[16]),32);
        bufp->chgIData(oldp+33,(vlSelfRef.tb_compute_core__DOT__ia_mem[17]),32);
        bufp->chgIData(oldp+34,(vlSelfRef.tb_compute_core__DOT__ia_mem[18]),32);
        bufp->chgIData(oldp+35,(vlSelfRef.tb_compute_core__DOT__ia_mem[19]),32);
        bufp->chgIData(oldp+36,(vlSelfRef.tb_compute_core__DOT__ia_mem[20]),32);
        bufp->chgIData(oldp+37,(vlSelfRef.tb_compute_core__DOT__ia_mem[21]),32);
        bufp->chgIData(oldp+38,(vlSelfRef.tb_compute_core__DOT__ia_mem[22]),32);
        bufp->chgIData(oldp+39,(vlSelfRef.tb_compute_core__DOT__ia_mem[23]),32);
        bufp->chgIData(oldp+40,(vlSelfRef.tb_compute_core__DOT__ia_mem[24]),32);
        bufp->chgIData(oldp+41,(vlSelfRef.tb_compute_core__DOT__ia_mem[25]),32);
        bufp->chgIData(oldp+42,(vlSelfRef.tb_compute_core__DOT__ia_mem[26]),32);
        bufp->chgIData(oldp+43,(vlSelfRef.tb_compute_core__DOT__ia_mem[27]),32);
        bufp->chgIData(oldp+44,(vlSelfRef.tb_compute_core__DOT__ia_mem[28]),32);
        bufp->chgIData(oldp+45,(vlSelfRef.tb_compute_core__DOT__ia_mem[29]),32);
        bufp->chgIData(oldp+46,(vlSelfRef.tb_compute_core__DOT__ia_mem[30]),32);
        bufp->chgIData(oldp+47,(vlSelfRef.tb_compute_core__DOT__ia_mem[31]),32);
        bufp->chgIData(oldp+48,(vlSelfRef.tb_compute_core__DOT__exp_mem[0]),32);
        bufp->chgIData(oldp+49,(vlSelfRef.tb_compute_core__DOT__exp_mem[1]),32);
        bufp->chgIData(oldp+50,(vlSelfRef.tb_compute_core__DOT__exp_mem[2]),32);
        bufp->chgIData(oldp+51,(vlSelfRef.tb_compute_core__DOT__exp_mem[3]),32);
        bufp->chgIData(oldp+52,(vlSelfRef.tb_compute_core__DOT__exp_mem[4]),32);
        bufp->chgIData(oldp+53,(vlSelfRef.tb_compute_core__DOT__exp_mem[5]),32);
        bufp->chgIData(oldp+54,(vlSelfRef.tb_compute_core__DOT__exp_mem[6]),32);
        bufp->chgIData(oldp+55,(vlSelfRef.tb_compute_core__DOT__exp_mem[7]),32);
        bufp->chgIData(oldp+56,(vlSelfRef.tb_compute_core__DOT__exp_mem[8]),32);
        bufp->chgIData(oldp+57,(vlSelfRef.tb_compute_core__DOT__exp_mem[9]),32);
        bufp->chgIData(oldp+58,(vlSelfRef.tb_compute_core__DOT__exp_mem[10]),32);
        bufp->chgIData(oldp+59,(vlSelfRef.tb_compute_core__DOT__exp_mem[11]),32);
        bufp->chgIData(oldp+60,(vlSelfRef.tb_compute_core__DOT__exp_mem[12]),32);
        bufp->chgIData(oldp+61,(vlSelfRef.tb_compute_core__DOT__exp_mem[13]),32);
        bufp->chgIData(oldp+62,(vlSelfRef.tb_compute_core__DOT__exp_mem[14]),32);
        bufp->chgIData(oldp+63,(vlSelfRef.tb_compute_core__DOT__exp_mem[15]),32);
        bufp->chgIData(oldp+64,(vlSelfRef.tb_compute_core__DOT__bias_mem[0]),32);
        bufp->chgIData(oldp+65,(vlSelfRef.tb_compute_core__DOT__bias_mem[1]),32);
        bufp->chgIData(oldp+66,(vlSelfRef.tb_compute_core__DOT__bias_mem[2]),32);
        bufp->chgIData(oldp+67,(vlSelfRef.tb_compute_core__DOT__bias_mem[3]),32);
        bufp->chgIData(oldp+68,(vlSelfRef.tb_compute_core__DOT__errors),32);
        bufp->chgIData(oldp+69,(vlSelfRef.tb_compute_core__DOT__idx),32);
        bufp->chgCData(oldp+70,(vlSelfRef.tb_compute_core__DOT__tile_buf
                                [0U][0U]),8);
        bufp->chgCData(oldp+71,(vlSelfRef.tb_compute_core__DOT__tile_buf
                                [0U][1U]),8);
        bufp->chgCData(oldp+72,(vlSelfRef.tb_compute_core__DOT__tile_buf
                                [0U][2U]),8);
        bufp->chgCData(oldp+73,(vlSelfRef.tb_compute_core__DOT__tile_buf
                                [0U][3U]),8);
        bufp->chgCData(oldp+74,(vlSelfRef.tb_compute_core__DOT__tile_buf
                                [1U][0U]),8);
        bufp->chgCData(oldp+75,(vlSelfRef.tb_compute_core__DOT__tile_buf
                                [1U][1U]),8);
        bufp->chgCData(oldp+76,(vlSelfRef.tb_compute_core__DOT__tile_buf
                                [1U][2U]),8);
        bufp->chgCData(oldp+77,(vlSelfRef.tb_compute_core__DOT__tile_buf
                                [1U][3U]),8);
        bufp->chgCData(oldp+78,(vlSelfRef.tb_compute_core__DOT__tile_buf
                                [2U][0U]),8);
        bufp->chgCData(oldp+79,(vlSelfRef.tb_compute_core__DOT__tile_buf
                                [2U][1U]),8);
        bufp->chgCData(oldp+80,(vlSelfRef.tb_compute_core__DOT__tile_buf
                                [2U][2U]),8);
        bufp->chgCData(oldp+81,(vlSelfRef.tb_compute_core__DOT__tile_buf
                                [2U][3U]),8);
        bufp->chgCData(oldp+82,(vlSelfRef.tb_compute_core__DOT__tile_buf
                                [3U][0U]),8);
        bufp->chgCData(oldp+83,(vlSelfRef.tb_compute_core__DOT__tile_buf
                                [3U][1U]),8);
        bufp->chgCData(oldp+84,(vlSelfRef.tb_compute_core__DOT__tile_buf
                                [3U][2U]),8);
        bufp->chgCData(oldp+85,(vlSelfRef.tb_compute_core__DOT__tile_buf
                                [3U][3U]),8);
        bufp->chgIData(oldp+86,(vlSelfRef.tb_compute_core__DOT__unnamedblk2__DOT__i),32);
        bufp->chgIData(oldp+87,(vlSelfRef.tb_compute_core__DOT__unnamedblk3__DOT__i),32);
        bufp->chgIData(oldp+88,(vlSelfRef.tb_compute_core__DOT__unnamedblk4__DOT__seg),32);
        bufp->chgIData(oldp+89,(vlSelfRef.tb_compute_core__DOT__unnamedblk5__DOT__r),32);
        bufp->chgIData(oldp+90,(vlSelfRef.tb_compute_core__DOT__unnamedblk5__DOT__unnamedblk6__DOT__c),32);
    }
    if (VL_UNLIKELY((vlSelfRef.__Vm_traceActivity[3U]))) {
        bufp->chgIData(oldp+91,(vlSelfRef.tb_compute_core__DOT__out_buf[0]),32);
        bufp->chgIData(oldp+92,(vlSelfRef.tb_compute_core__DOT__out_buf[1]),32);
        bufp->chgIData(oldp+93,(vlSelfRef.tb_compute_core__DOT__out_buf[2]),32);
        bufp->chgIData(oldp+94,(vlSelfRef.tb_compute_core__DOT__out_buf[3]),32);
        bufp->chgIData(oldp+95,(vlSelfRef.tb_compute_core__DOT__out_buf[4]),32);
        bufp->chgIData(oldp+96,(vlSelfRef.tb_compute_core__DOT__out_buf[5]),32);
        bufp->chgIData(oldp+97,(vlSelfRef.tb_compute_core__DOT__out_buf[6]),32);
        bufp->chgIData(oldp+98,(vlSelfRef.tb_compute_core__DOT__out_buf[7]),32);
        bufp->chgIData(oldp+99,(vlSelfRef.tb_compute_core__DOT__out_buf[8]),32);
        bufp->chgIData(oldp+100,(vlSelfRef.tb_compute_core__DOT__out_buf[9]),32);
        bufp->chgIData(oldp+101,(vlSelfRef.tb_compute_core__DOT__out_buf[10]),32);
        bufp->chgIData(oldp+102,(vlSelfRef.tb_compute_core__DOT__out_buf[11]),32);
        bufp->chgIData(oldp+103,(vlSelfRef.tb_compute_core__DOT__out_buf[12]),32);
        bufp->chgIData(oldp+104,(vlSelfRef.tb_compute_core__DOT__out_buf[13]),32);
        bufp->chgIData(oldp+105,(vlSelfRef.tb_compute_core__DOT__out_buf[14]),32);
        bufp->chgIData(oldp+106,(vlSelfRef.tb_compute_core__DOT__out_buf[15]),32);
        bufp->chgIData(oldp+107,(vlSelfRef.tb_compute_core__DOT____Vcellout__u_dut__acc_data_out[0]),32);
        bufp->chgIData(oldp+108,(vlSelfRef.tb_compute_core__DOT____Vcellout__u_dut__acc_data_out[1]),32);
        bufp->chgIData(oldp+109,(vlSelfRef.tb_compute_core__DOT____Vcellout__u_dut__acc_data_out[2]),32);
        bufp->chgIData(oldp+110,(vlSelfRef.tb_compute_core__DOT____Vcellout__u_dut__acc_data_out[3]),32);
        bufp->chgBit(oldp+111,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__calc_done_reg));
        bufp->chgBit(oldp+112,(vlSelfRef.tb_compute_core__DOT____Vcellout__u_dut__tile_calc_over));
        bufp->chgBit(oldp+113,(vlSelfRef.tb_compute_core__DOT____Vcellout__u_dut__partial_sum_calc_over));
        bufp->chgBit(oldp+114,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__input_valid_shift
                               [3U]));
        bufp->chgBit(oldp+115,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__calc_done_shift
                               [3U]));
        bufp->chgBit(oldp+116,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__is_init_data_shift
                               [3U]));
        bufp->chgIData(oldp+117,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__sa_sum_out[0]),32);
        bufp->chgIData(oldp+118,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__sa_sum_out[1]),32);
        bufp->chgIData(oldp+119,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__sa_sum_out[2]),32);
        bufp->chgIData(oldp+120,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__sa_sum_out[3]),32);
        bufp->chgIData(oldp+121,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellinp__u_accumulator_array__data_in[0]),32);
        bufp->chgIData(oldp+122,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellinp__u_accumulator_array__data_in[1]),32);
        bufp->chgIData(oldp+123,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellinp__u_accumulator_array__data_in[2]),32);
        bufp->chgIData(oldp+124,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellinp__u_accumulator_array__data_in[3]),32);
        bufp->chgIData(oldp+125,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellout__u_accumulator_array__data_out[0]),32);
        bufp->chgIData(oldp+126,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellout__u_accumulator_array__data_out[1]),32);
        bufp->chgIData(oldp+127,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellout__u_accumulator_array__data_out[2]),32);
        bufp->chgIData(oldp+128,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellout__u_accumulator_array__data_out[3]),32);
        bufp->chgCData(oldp+129,(((((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__calc_done_reg) 
                                    << 4U) | (((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__calc_done_reg) 
                                               << 3U) 
                                              | ((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__calc_done_reg) 
                                                 << 2U))) 
                                  | (((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__calc_done_reg) 
                                      << 1U) | vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__calc_done_shift
                                     [3U]))),5);
        bufp->chgCData(oldp+130,(((((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__input_valid_reg) 
                                    << 4U) | (((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__input_valid_reg) 
                                               << 3U) 
                                              | ((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__input_valid_reg) 
                                                 << 2U))) 
                                  | (((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__input_valid_reg) 
                                      << 1U) | vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__input_valid_shift
                                     [3U]))),5);
        bufp->chgCData(oldp+131,(((((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__is_init_data_reg) 
                                    << 4U) | (((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__is_init_data_reg) 
                                               << 3U) 
                                              | ((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__is_init_data_reg) 
                                                 << 2U))) 
                                  | (((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__is_init_data_reg) 
                                      << 1U) | vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__is_init_data_shift
                                     [3U]))),5);
        bufp->chgBit(oldp+132,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__calc_done_o_d));
        bufp->chgBit(oldp+133,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__input_valid_chain_d));
        bufp->chgBit(oldp+134,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__input_valid_i_d));
        bufp->chgCData(oldp+135,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__read_ptr),2);
        bufp->chgIData(oldp+136,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__sa_sum_out
                                 [0U]),32);
        bufp->chgIData(oldp+137,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__acc_fifo
                                 [vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__read_ptr]),32);
        bufp->chgBit(oldp+138,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__calc_done_reg));
        bufp->chgBit(oldp+139,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__input_valid_reg));
        bufp->chgBit(oldp+140,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__is_init_data_reg));
        bufp->chgIData(oldp+141,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__acc_fifo[0]),32);
        bufp->chgIData(oldp+142,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__acc_fifo[1]),32);
        bufp->chgIData(oldp+143,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__acc_fifo[2]),32);
        bufp->chgIData(oldp+144,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__acc_fifo[3]),32);
        bufp->chgCData(oldp+145,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__write_ptr),2);
        bufp->chgBit(oldp+146,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__input_valid_i_d));
        bufp->chgQData(oldp+147,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__unnamedblk1__DOT__sum),33);
        bufp->chgIData(oldp+149,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__sa_sum_out
                                 [1U]),32);
        bufp->chgIData(oldp+150,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__acc_fifo
                                 [vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__read_ptr]),32);
        bufp->chgBit(oldp+151,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__calc_done_reg));
        bufp->chgBit(oldp+152,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__input_valid_reg));
        bufp->chgBit(oldp+153,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__is_init_data_reg));
        bufp->chgIData(oldp+154,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__acc_fifo[0]),32);
        bufp->chgIData(oldp+155,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__acc_fifo[1]),32);
        bufp->chgIData(oldp+156,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__acc_fifo[2]),32);
        bufp->chgIData(oldp+157,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__acc_fifo[3]),32);
        bufp->chgCData(oldp+158,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__write_ptr),2);
        bufp->chgBit(oldp+159,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__input_valid_i_d));
        bufp->chgQData(oldp+160,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__unnamedblk1__DOT__sum),33);
        bufp->chgIData(oldp+162,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__sa_sum_out
                                 [2U]),32);
        bufp->chgIData(oldp+163,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__acc_fifo
                                 [vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__read_ptr]),32);
        bufp->chgBit(oldp+164,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__calc_done_reg));
        bufp->chgBit(oldp+165,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__input_valid_reg));
        bufp->chgBit(oldp+166,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__is_init_data_reg));
        bufp->chgIData(oldp+167,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__acc_fifo[0]),32);
        bufp->chgIData(oldp+168,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__acc_fifo[1]),32);
        bufp->chgIData(oldp+169,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__acc_fifo[2]),32);
        bufp->chgIData(oldp+170,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__acc_fifo[3]),32);
        bufp->chgCData(oldp+171,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__write_ptr),2);
        bufp->chgBit(oldp+172,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__input_valid_i_d));
        bufp->chgQData(oldp+173,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__unnamedblk1__DOT__sum),33);
        bufp->chgIData(oldp+175,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__sa_sum_out
                                 [3U]),32);
        bufp->chgIData(oldp+176,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__acc_fifo
                                 [vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__read_ptr]),32);
        bufp->chgBit(oldp+177,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__input_valid_reg));
        bufp->chgBit(oldp+178,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__is_init_data_reg));
        bufp->chgIData(oldp+179,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__acc_fifo[0]),32);
        bufp->chgIData(oldp+180,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__acc_fifo[1]),32);
        bufp->chgIData(oldp+181,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__acc_fifo[2]),32);
        bufp->chgIData(oldp+182,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__acc_fifo[3]),32);
        bufp->chgCData(oldp+183,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__write_ptr),2);
        bufp->chgBit(oldp+184,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__input_valid_i_d));
        bufp->chgQData(oldp+185,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__unnamedblk1__DOT__sum),33);
        bufp->chgBit(oldp+187,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__input_valid_shift[0]));
        bufp->chgBit(oldp+188,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__input_valid_shift[1]));
        bufp->chgBit(oldp+189,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__input_valid_shift[2]));
        bufp->chgBit(oldp+190,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__input_valid_shift[3]));
        bufp->chgBit(oldp+191,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__calc_done_shift[0]));
        bufp->chgBit(oldp+192,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__calc_done_shift[1]));
        bufp->chgBit(oldp+193,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__calc_done_shift[2]));
        bufp->chgBit(oldp+194,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__calc_done_shift[3]));
        bufp->chgBit(oldp+195,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__is_init_data_shift[0]));
        bufp->chgBit(oldp+196,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__is_init_data_shift[1]));
        bufp->chgBit(oldp+197,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__is_init_data_shift[2]));
        bufp->chgBit(oldp+198,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__is_init_data_shift[3]));
        bufp->chgIData(oldp+199,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__unnamedblk1__DOT__m),32);
        bufp->chgSData(oldp+200,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__1__KET____DOT__gen_delay_1__DOT__shift_reg),16);
        bufp->chgSData(oldp+201,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__2__KET____DOT__gen_delay_n__DOT__shift_reg[0]),16);
        bufp->chgSData(oldp+202,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__2__KET____DOT__gen_delay_n__DOT__shift_reg[1]),16);
        bufp->chgIData(oldp+203,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__2__KET____DOT__gen_delay_n__DOT__k),32);
        bufp->chgSData(oldp+204,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__3__KET____DOT__gen_delay_n__DOT__shift_reg[0]),16);
        bufp->chgSData(oldp+205,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__3__KET____DOT__gen_delay_n__DOT__shift_reg[1]),16);
        bufp->chgSData(oldp+206,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__3__KET____DOT__gen_delay_n__DOT__shift_reg[2]),16);
        bufp->chgIData(oldp+207,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__3__KET____DOT__gen_delay_n__DOT__k),32);
        bufp->chgSData(oldp+208,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
                                 [0U][0U]),16);
        bufp->chgSData(oldp+209,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
                                 [0U][1U]),16);
        bufp->chgSData(oldp+210,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
                                 [0U][2U]),16);
        bufp->chgSData(oldp+211,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
                                 [0U][3U]),16);
        bufp->chgSData(oldp+212,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
                                 [1U][0U]),16);
        bufp->chgSData(oldp+213,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
                                 [1U][1U]),16);
        bufp->chgSData(oldp+214,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
                                 [1U][2U]),16);
        bufp->chgSData(oldp+215,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
                                 [1U][3U]),16);
        bufp->chgSData(oldp+216,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
                                 [2U][0U]),16);
        bufp->chgSData(oldp+217,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
                                 [2U][1U]),16);
        bufp->chgSData(oldp+218,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
                                 [2U][2U]),16);
        bufp->chgSData(oldp+219,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
                                 [2U][3U]),16);
        bufp->chgSData(oldp+220,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
                                 [3U][0U]),16);
        bufp->chgSData(oldp+221,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
                                 [3U][1U]),16);
        bufp->chgSData(oldp+222,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
                                 [3U][2U]),16);
        bufp->chgSData(oldp+223,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
                                 [3U][3U]),16);
        bufp->chgCData(oldp+224,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
                                 [0U][0U]),8);
        bufp->chgCData(oldp+225,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
                                 [0U][1U]),8);
        bufp->chgCData(oldp+226,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
                                 [0U][2U]),8);
        bufp->chgCData(oldp+227,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
                                 [0U][3U]),8);
        bufp->chgCData(oldp+228,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
                                 [1U][0U]),8);
        bufp->chgCData(oldp+229,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
                                 [1U][1U]),8);
        bufp->chgCData(oldp+230,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
                                 [1U][2U]),8);
        bufp->chgCData(oldp+231,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
                                 [1U][3U]),8);
        bufp->chgCData(oldp+232,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
                                 [2U][0U]),8);
        bufp->chgCData(oldp+233,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
                                 [2U][1U]),8);
        bufp->chgCData(oldp+234,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
                                 [2U][2U]),8);
        bufp->chgCData(oldp+235,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
                                 [2U][3U]),8);
        bufp->chgCData(oldp+236,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
                                 [3U][0U]),8);
        bufp->chgCData(oldp+237,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
                                 [3U][1U]),8);
        bufp->chgCData(oldp+238,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
                                 [3U][2U]),8);
        bufp->chgCData(oldp+239,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
                                 [3U][3U]),8);
        bufp->chgIData(oldp+240,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
                                 [0U][0U]),32);
        bufp->chgIData(oldp+241,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
                                 [0U][1U]),32);
        bufp->chgIData(oldp+242,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
                                 [0U][2U]),32);
        bufp->chgIData(oldp+243,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
                                 [0U][3U]),32);
        bufp->chgIData(oldp+244,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
                                 [1U][0U]),32);
        bufp->chgIData(oldp+245,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
                                 [1U][1U]),32);
        bufp->chgIData(oldp+246,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
                                 [1U][2U]),32);
        bufp->chgIData(oldp+247,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
                                 [1U][3U]),32);
        bufp->chgIData(oldp+248,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
                                 [2U][0U]),32);
        bufp->chgIData(oldp+249,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
                                 [2U][1U]),32);
        bufp->chgIData(oldp+250,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
                                 [2U][2U]),32);
        bufp->chgIData(oldp+251,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
                                 [2U][3U]),32);
        bufp->chgIData(oldp+252,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
                                 [3U][0U]),32);
        bufp->chgIData(oldp+253,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
                                 [3U][1U]),32);
        bufp->chgIData(oldp+254,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
                                 [3U][2U]),32);
        bufp->chgIData(oldp+255,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
                                 [3U][3U]),32);
        bufp->chgSData(oldp+256,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__data_reg),16);
        bufp->chgCData(oldp+257,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__weight_reg),8);
        bufp->chgIData(oldp+258,((VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext)
                                   ? 0x7fffffffU : 
                                  (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext)
                                    ? 0x80000000U : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext)))),32);
        bufp->chgIData(oldp+259,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_reg),32);
        bufp->chgIData(oldp+260,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__mult_result),32);
        bufp->chgQData(oldp+261,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext),33);
        bufp->chgSData(oldp+263,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
                                 [0U][0U]),16);
        bufp->chgSData(oldp+264,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__data_reg),16);
        bufp->chgCData(oldp+265,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__weight_reg),8);
        bufp->chgIData(oldp+266,((VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext)
                                   ? 0x7fffffffU : 
                                  (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext)
                                    ? 0x80000000U : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext)))),32);
        bufp->chgIData(oldp+267,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_reg),32);
        bufp->chgIData(oldp+268,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__mult_result),32);
        bufp->chgQData(oldp+269,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext),33);
        bufp->chgSData(oldp+271,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
                                 [0U][1U]),16);
        bufp->chgSData(oldp+272,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__data_reg),16);
        bufp->chgCData(oldp+273,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__weight_reg),8);
        bufp->chgIData(oldp+274,((VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext)
                                   ? 0x7fffffffU : 
                                  (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext)
                                    ? 0x80000000U : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext)))),32);
        bufp->chgIData(oldp+275,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_reg),32);
        bufp->chgIData(oldp+276,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__mult_result),32);
        bufp->chgQData(oldp+277,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext),33);
        bufp->chgSData(oldp+279,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
                                 [0U][2U]),16);
        bufp->chgSData(oldp+280,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__data_reg),16);
        bufp->chgCData(oldp+281,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__weight_reg),8);
        bufp->chgIData(oldp+282,((VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext)
                                   ? 0x7fffffffU : 
                                  (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext)
                                    ? 0x80000000U : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext)))),32);
        bufp->chgIData(oldp+283,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_reg),32);
        bufp->chgIData(oldp+284,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__mult_result),32);
        bufp->chgQData(oldp+285,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext),33);
        bufp->chgCData(oldp+287,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
                                 [0U][0U]),8);
        bufp->chgIData(oldp+288,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
                                 [0U][0U]),32);
        bufp->chgSData(oldp+289,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__data_reg),16);
        bufp->chgCData(oldp+290,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__weight_reg),8);
        bufp->chgIData(oldp+291,((VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext)
                                   ? 0x7fffffffU : 
                                  (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext)
                                    ? 0x80000000U : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext)))),32);
        bufp->chgIData(oldp+292,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_reg),32);
        bufp->chgIData(oldp+293,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__mult_result),32);
        bufp->chgQData(oldp+294,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext),33);
        bufp->chgCData(oldp+296,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
                                 [0U][1U]),8);
        bufp->chgSData(oldp+297,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
                                 [1U][0U]),16);
        bufp->chgIData(oldp+298,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
                                 [0U][1U]),32);
        bufp->chgSData(oldp+299,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__data_reg),16);
        bufp->chgCData(oldp+300,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__weight_reg),8);
        bufp->chgIData(oldp+301,((VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext)
                                   ? 0x7fffffffU : 
                                  (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext)
                                    ? 0x80000000U : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext)))),32);
        bufp->chgIData(oldp+302,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_reg),32);
        bufp->chgIData(oldp+303,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__mult_result),32);
        bufp->chgQData(oldp+304,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext),33);
        bufp->chgCData(oldp+306,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
                                 [0U][2U]),8);
        bufp->chgSData(oldp+307,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
                                 [1U][1U]),16);
        bufp->chgIData(oldp+308,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
                                 [0U][2U]),32);
        bufp->chgSData(oldp+309,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__data_reg),16);
        bufp->chgCData(oldp+310,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__weight_reg),8);
        bufp->chgIData(oldp+311,((VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext)
                                   ? 0x7fffffffU : 
                                  (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext)
                                    ? 0x80000000U : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext)))),32);
        bufp->chgIData(oldp+312,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_reg),32);
        bufp->chgIData(oldp+313,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__mult_result),32);
        bufp->chgQData(oldp+314,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext),33);
        bufp->chgCData(oldp+316,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
                                 [0U][3U]),8);
        bufp->chgSData(oldp+317,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
                                 [1U][2U]),16);
        bufp->chgIData(oldp+318,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
                                 [0U][3U]),32);
        bufp->chgSData(oldp+319,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__data_reg),16);
        bufp->chgCData(oldp+320,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__weight_reg),8);
        bufp->chgIData(oldp+321,((VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext)
                                   ? 0x7fffffffU : 
                                  (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext)
                                    ? 0x80000000U : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext)))),32);
        bufp->chgIData(oldp+322,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_reg),32);
        bufp->chgIData(oldp+323,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__mult_result),32);
        bufp->chgQData(oldp+324,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext),33);
        bufp->chgCData(oldp+326,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
                                 [1U][0U]),8);
        bufp->chgSData(oldp+327,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__2__KET____DOT__gen_delay_n__DOT__shift_reg
                                 [1U]),16);
        bufp->chgIData(oldp+328,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
                                 [1U][0U]),32);
        bufp->chgSData(oldp+329,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__data_reg),16);
        bufp->chgCData(oldp+330,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__weight_reg),8);
        bufp->chgIData(oldp+331,((VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext)
                                   ? 0x7fffffffU : 
                                  (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext)
                                    ? 0x80000000U : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext)))),32);
        bufp->chgIData(oldp+332,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_reg),32);
        bufp->chgIData(oldp+333,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__mult_result),32);
        bufp->chgQData(oldp+334,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext),33);
        bufp->chgCData(oldp+336,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
                                 [1U][1U]),8);
        bufp->chgSData(oldp+337,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
                                 [2U][0U]),16);
        bufp->chgIData(oldp+338,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
                                 [1U][1U]),32);
        bufp->chgSData(oldp+339,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__data_reg),16);
        bufp->chgCData(oldp+340,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__weight_reg),8);
        bufp->chgIData(oldp+341,((VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext)
                                   ? 0x7fffffffU : 
                                  (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext)
                                    ? 0x80000000U : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext)))),32);
        bufp->chgIData(oldp+342,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_reg),32);
        bufp->chgIData(oldp+343,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__mult_result),32);
        bufp->chgQData(oldp+344,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext),33);
        bufp->chgCData(oldp+346,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
                                 [1U][2U]),8);
        bufp->chgSData(oldp+347,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
                                 [2U][1U]),16);
        bufp->chgIData(oldp+348,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
                                 [1U][2U]),32);
        bufp->chgSData(oldp+349,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__data_reg),16);
        bufp->chgCData(oldp+350,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__weight_reg),8);
        bufp->chgIData(oldp+351,((VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext)
                                   ? 0x7fffffffU : 
                                  (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext)
                                    ? 0x80000000U : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext)))),32);
        bufp->chgIData(oldp+352,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_reg),32);
        bufp->chgIData(oldp+353,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__mult_result),32);
        bufp->chgQData(oldp+354,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext),33);
        bufp->chgCData(oldp+356,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
                                 [1U][3U]),8);
        bufp->chgSData(oldp+357,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
                                 [2U][2U]),16);
        bufp->chgIData(oldp+358,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
                                 [1U][3U]),32);
        bufp->chgSData(oldp+359,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__data_reg),16);
        bufp->chgCData(oldp+360,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__weight_reg),8);
        bufp->chgIData(oldp+361,((VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext)
                                   ? 0x7fffffffU : 
                                  (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext)
                                    ? 0x80000000U : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext)))),32);
        bufp->chgIData(oldp+362,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_reg),32);
        bufp->chgIData(oldp+363,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__mult_result),32);
        bufp->chgQData(oldp+364,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext),33);
        bufp->chgCData(oldp+366,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
                                 [2U][0U]),8);
        bufp->chgSData(oldp+367,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__3__KET____DOT__gen_delay_n__DOT__shift_reg
                                 [2U]),16);
        bufp->chgIData(oldp+368,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
                                 [2U][0U]),32);
        bufp->chgSData(oldp+369,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__data_reg),16);
        bufp->chgCData(oldp+370,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__weight_reg),8);
        bufp->chgIData(oldp+371,((VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext)
                                   ? 0x7fffffffU : 
                                  (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext)
                                    ? 0x80000000U : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext)))),32);
        bufp->chgIData(oldp+372,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_reg),32);
        bufp->chgIData(oldp+373,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__mult_result),32);
        bufp->chgQData(oldp+374,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext),33);
        bufp->chgCData(oldp+376,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
                                 [2U][1U]),8);
        bufp->chgSData(oldp+377,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
                                 [3U][0U]),16);
        bufp->chgIData(oldp+378,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
                                 [2U][1U]),32);
        bufp->chgSData(oldp+379,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__data_reg),16);
        bufp->chgCData(oldp+380,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__weight_reg),8);
        bufp->chgIData(oldp+381,((VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext)
                                   ? 0x7fffffffU : 
                                  (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext)
                                    ? 0x80000000U : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext)))),32);
        bufp->chgIData(oldp+382,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_reg),32);
        bufp->chgIData(oldp+383,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__mult_result),32);
        bufp->chgQData(oldp+384,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext),33);
        bufp->chgCData(oldp+386,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
                                 [2U][2U]),8);
        bufp->chgSData(oldp+387,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
                                 [3U][1U]),16);
        bufp->chgIData(oldp+388,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
                                 [2U][2U]),32);
        bufp->chgSData(oldp+389,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__data_reg),16);
        bufp->chgCData(oldp+390,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__weight_reg),8);
        bufp->chgIData(oldp+391,((VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext)
                                   ? 0x7fffffffU : 
                                  (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext)
                                    ? 0x80000000U : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext)))),32);
        bufp->chgIData(oldp+392,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_reg),32);
        bufp->chgIData(oldp+393,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__mult_result),32);
        bufp->chgQData(oldp+394,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext),33);
        bufp->chgCData(oldp+396,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
                                 [2U][3U]),8);
        bufp->chgSData(oldp+397,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
                                 [3U][2U]),16);
        bufp->chgIData(oldp+398,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
                                 [2U][3U]),32);
        bufp->chgSData(oldp+399,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__data_reg),16);
        bufp->chgCData(oldp+400,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__weight_reg),8);
        bufp->chgIData(oldp+401,((VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext)
                                   ? 0x7fffffffU : 
                                  (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext)
                                    ? 0x80000000U : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext)))),32);
        bufp->chgIData(oldp+402,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_reg),32);
        bufp->chgIData(oldp+403,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__mult_result),32);
        bufp->chgQData(oldp+404,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext),33);
        bufp->chgIData(oldp+406,(vlSelfRef.tb_compute_core__DOT__unnamedblk1__DOT__c),32);
        bufp->chgIData(oldp+407,(vlSymsp->TOP__tb_compute_core__DOT__tb_if.acc_data_out[0]),32);
        bufp->chgIData(oldp+408,(vlSymsp->TOP__tb_compute_core__DOT__tb_if.acc_data_out[1]),32);
        bufp->chgIData(oldp+409,(vlSymsp->TOP__tb_compute_core__DOT__tb_if.acc_data_out[2]),32);
        bufp->chgIData(oldp+410,(vlSymsp->TOP__tb_compute_core__DOT__tb_if.acc_data_out[3]),32);
    }
    if (VL_UNLIKELY(((vlSelfRef.__Vm_traceActivity[3U] 
                      | vlSelfRef.__Vm_traceActivity
                      [6U])))) {
        bufp->chgSData(oldp+411,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__data_setup_out[0]),16);
        bufp->chgSData(oldp+412,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__data_setup_out[1]),16);
        bufp->chgSData(oldp+413,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__data_setup_out[2]),16);
        bufp->chgSData(oldp+414,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__data_setup_out[3]),16);
        bufp->chgSData(oldp+415,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellout__u_data_setup__data_out[0]),16);
        bufp->chgSData(oldp+416,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellout__u_data_setup__data_out[1]),16);
        bufp->chgSData(oldp+417,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellout__u_data_setup__data_out[2]),16);
        bufp->chgSData(oldp+418,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellout__u_data_setup__data_out[3]),16);
    }
    if (VL_UNLIKELY((vlSelfRef.__Vm_traceActivity[4U]))) {
        bufp->chgIData(oldp+419,(vlSelfRef.tb_compute_core__DOT____Vcellinp__u_dut__bias_in[0]),32);
        bufp->chgIData(oldp+420,(vlSelfRef.tb_compute_core__DOT____Vcellinp__u_dut__bias_in[1]),32);
        bufp->chgIData(oldp+421,(vlSelfRef.tb_compute_core__DOT____Vcellinp__u_dut__bias_in[2]),32);
        bufp->chgIData(oldp+422,(vlSelfRef.tb_compute_core__DOT____Vcellinp__u_dut__bias_in[3]),32);
        bufp->chgIData(oldp+423,(vlSymsp->TOP__tb_compute_core__DOT__tb_if.bias_in
                                 [0U]),32);
        bufp->chgIData(oldp+424,(vlSymsp->TOP__tb_compute_core__DOT__tb_if.bias_in
                                 [1U]),32);
        bufp->chgIData(oldp+425,(vlSymsp->TOP__tb_compute_core__DOT__tb_if.bias_in
                                 [2U]),32);
        bufp->chgIData(oldp+426,(vlSymsp->TOP__tb_compute_core__DOT__tb_if.bias_in
                                 [3U]),32);
        bufp->chgIData(oldp+427,(vlSymsp->TOP__tb_compute_core__DOT__tb_if.bias_in[0]),32);
        bufp->chgIData(oldp+428,(vlSymsp->TOP__tb_compute_core__DOT__tb_if.bias_in[1]),32);
        bufp->chgIData(oldp+429,(vlSymsp->TOP__tb_compute_core__DOT__tb_if.bias_in[2]),32);
        bufp->chgIData(oldp+430,(vlSymsp->TOP__tb_compute_core__DOT__tb_if.bias_in[3]),32);
    }
    if (VL_UNLIKELY((vlSelfRef.__Vm_traceActivity[5U]))) {
        bufp->chgCData(oldp+431,(vlSelfRef.tb_compute_core__DOT____Vcellinp__u_dut__weight_in[0]),8);
        bufp->chgCData(oldp+432,(vlSelfRef.tb_compute_core__DOT____Vcellinp__u_dut__weight_in[1]),8);
        bufp->chgCData(oldp+433,(vlSelfRef.tb_compute_core__DOT____Vcellinp__u_dut__weight_in[2]),8);
        bufp->chgCData(oldp+434,(vlSelfRef.tb_compute_core__DOT____Vcellinp__u_dut__weight_in[3]),8);
        bufp->chgCData(oldp+435,(vlSymsp->TOP__tb_compute_core__DOT__tb_if.weight_in
                                 [0U]),8);
        bufp->chgCData(oldp+436,(vlSymsp->TOP__tb_compute_core__DOT__tb_if.weight_in
                                 [1U]),8);
        bufp->chgCData(oldp+437,(vlSymsp->TOP__tb_compute_core__DOT__tb_if.weight_in
                                 [2U]),8);
        bufp->chgCData(oldp+438,(vlSymsp->TOP__tb_compute_core__DOT__tb_if.weight_in
                                 [3U]),8);
        bufp->chgCData(oldp+439,(vlSymsp->TOP__tb_compute_core__DOT__tb_if.weight_in[0]),8);
        bufp->chgCData(oldp+440,(vlSymsp->TOP__tb_compute_core__DOT__tb_if.weight_in[1]),8);
        bufp->chgCData(oldp+441,(vlSymsp->TOP__tb_compute_core__DOT__tb_if.weight_in[2]),8);
        bufp->chgCData(oldp+442,(vlSymsp->TOP__tb_compute_core__DOT__tb_if.weight_in[3]),8);
    }
    if (VL_UNLIKELY((vlSelfRef.__Vm_traceActivity[6U]))) {
        bufp->chgSData(oldp+443,(vlSelfRef.tb_compute_core__DOT____Vcellinp__u_dut__ia_vec_in[0]),16);
        bufp->chgSData(oldp+444,(vlSelfRef.tb_compute_core__DOT____Vcellinp__u_dut__ia_vec_in[1]),16);
        bufp->chgSData(oldp+445,(vlSelfRef.tb_compute_core__DOT____Vcellinp__u_dut__ia_vec_in[2]),16);
        bufp->chgSData(oldp+446,(vlSelfRef.tb_compute_core__DOT____Vcellinp__u_dut__ia_vec_in[3]),16);
        bufp->chgSData(oldp+447,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellinp__u_data_setup__data_in[0]),16);
        bufp->chgSData(oldp+448,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellinp__u_data_setup__data_in[1]),16);
        bufp->chgSData(oldp+449,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellinp__u_data_setup__data_in[2]),16);
        bufp->chgSData(oldp+450,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellinp__u_data_setup__data_in[3]),16);
        bufp->chgSData(oldp+451,(vlSymsp->TOP__tb_compute_core__DOT__tb_if.ia_vec_in
                                 [0U]),16);
        bufp->chgSData(oldp+452,(vlSymsp->TOP__tb_compute_core__DOT__tb_if.ia_vec_in[0]),16);
        bufp->chgSData(oldp+453,(vlSymsp->TOP__tb_compute_core__DOT__tb_if.ia_vec_in[1]),16);
        bufp->chgSData(oldp+454,(vlSymsp->TOP__tb_compute_core__DOT__tb_if.ia_vec_in[2]),16);
        bufp->chgSData(oldp+455,(vlSymsp->TOP__tb_compute_core__DOT__tb_if.ia_vec_in[3]),16);
    }
    bufp->chgBit(oldp+456,(vlSelfRef.tb_compute_core__DOT__clk));
    bufp->chgIData(oldp+457,(vlSelfRef.tb_compute_core__DOT__out_rows),32);
    bufp->chgIData(oldp+458,(vlSelfRef.tb_compute_core__DOT__NUM_K),32);
    bufp->chgIData(oldp+459,(vlSelfRef.tb_compute_core__DOT__NUM_SEG),32);
    bufp->chgBit(oldp+460,(vlSymsp->TOP__tb_compute_core__DOT__tb_if.store_weight_req));
    bufp->chgBit(oldp+461,(vlSymsp->TOP__tb_compute_core__DOT__tb_if.ia_row_valid));
    bufp->chgBit(oldp+462,(vlSymsp->TOP__tb_compute_core__DOT__tb_if.ia_calc_done));
    bufp->chgBit(oldp+463,(vlSymsp->TOP__tb_compute_core__DOT__tb_if.ia_is_init_data));
}

void Vtb_compute_core___024root__trace_cleanup(void* voidSelf, VerilatedVcd* /*unused*/) {
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_compute_core___024root__trace_cleanup\n"); );
    // Init
    Vtb_compute_core___024root* const __restrict vlSelf VL_ATTR_UNUSED = static_cast<Vtb_compute_core___024root*>(voidSelf);
    Vtb_compute_core__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    // Body
    vlSymsp->__Vm_activity = false;
    vlSymsp->TOP.__Vm_traceActivity[0U] = 0U;
    vlSymsp->TOP.__Vm_traceActivity[1U] = 0U;
    vlSymsp->TOP.__Vm_traceActivity[2U] = 0U;
    vlSymsp->TOP.__Vm_traceActivity[3U] = 0U;
    vlSymsp->TOP.__Vm_traceActivity[4U] = 0U;
    vlSymsp->TOP.__Vm_traceActivity[5U] = 0U;
    vlSymsp->TOP.__Vm_traceActivity[6U] = 0U;
}
