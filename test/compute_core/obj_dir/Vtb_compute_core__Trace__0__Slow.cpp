// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Tracing implementation internals
#include "verilated_vcd_c.h"
#include "Vtb_compute_core__Syms.h"


VL_ATTR_COLD void Vtb_compute_core___024root__trace_init_sub__TOP__tb_compute_core__DOT__tb_if__0(Vtb_compute_core___024root* vlSelf, VerilatedVcd* tracep);

VL_ATTR_COLD void Vtb_compute_core___024root__trace_init_sub__TOP__0(Vtb_compute_core___024root* vlSelf, VerilatedVcd* tracep) {
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_compute_core___024root__trace_init_sub__TOP__0\n"); );
    Vtb_compute_core__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    auto& vlSelfRef = std::ref(*vlSelf).get();
    // Init
    const int c = vlSymsp->__Vm_baseCode;
    // Body
    tracep->pushPrefix("tb_compute_core", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->declBus(c+465,0,"SIZE",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBus(c+466,0,"DATA_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBit(c+457,0,"clk",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->pushPrefix("tb_if", VerilatedTracePrefixType::SCOPE_INTERFACE);
    Vtb_compute_core___024root__trace_init_sub__TOP__tb_compute_core__DOT__tb_if__0(vlSelf, tracep);
    tracep->popPrefix();
    tracep->declBus(c+467,0,"WeightWords",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBus(c+468,0,"IaWords",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->pushPrefix("weight_mem", VerilatedTracePrefixType::ARRAY_UNPACKED);
    for (int i = 0; i < 16; ++i) {
        tracep->declBus(c+1+i*1,0,"",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, true,(i+0), 31,0);
    }
    tracep->popPrefix();
    tracep->pushPrefix("ia_mem", VerilatedTracePrefixType::ARRAY_UNPACKED);
    for (int i = 0; i < 32; ++i) {
        tracep->declBus(c+17+i*1,0,"",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, true,(i+0), 31,0);
    }
    tracep->popPrefix();
    tracep->pushPrefix("exp_mem", VerilatedTracePrefixType::ARRAY_UNPACKED);
    for (int i = 0; i < 16; ++i) {
        tracep->declBus(c+49+i*1,0,"",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, true,(i+0), 31,0);
    }
    tracep->popPrefix();
    tracep->pushPrefix("bias_mem", VerilatedTracePrefixType::ARRAY_UNPACKED);
    for (int i = 0; i < 4; ++i) {
        tracep->declBus(c+65+i*1,0,"",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, true,(i+0), 31,0);
    }
    tracep->popPrefix();
    tracep->pushPrefix("out_buf", VerilatedTracePrefixType::ARRAY_UNPACKED);
    for (int i = 0; i < 16; ++i) {
        tracep->declBus(c+92+i*1,0,"",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, true,(i+0), 31,0);
    }
    tracep->popPrefix();
    tracep->declBus(c+458,0,"out_rows",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::INTEGER, false,-1, 31,0);
    tracep->declBus(c+69,0,"errors",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::INTEGER, false,-1, 31,0);
    tracep->declBus(c+70,0,"idx",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::INTEGER, false,-1, 31,0);
    tracep->declBus(c+459,0,"NUM_K",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::INTEGER, false,-1, 31,0);
    tracep->declBus(c+460,0,"NUM_SEG",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::INTEGER, false,-1, 31,0);
    tracep->pushPrefix("tile_buf", VerilatedTracePrefixType::ARRAY_UNPACKED);
    tracep->pushPrefix("[0]", VerilatedTracePrefixType::ARRAY_UNPACKED);
    tracep->declBus(c+71,0,"[0]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+72,0,"[1]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+73,0,"[2]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+74,0,"[3]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->popPrefix();
    tracep->pushPrefix("[1]", VerilatedTracePrefixType::ARRAY_UNPACKED);
    tracep->declBus(c+75,0,"[0]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+76,0,"[1]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+77,0,"[2]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+78,0,"[3]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->popPrefix();
    tracep->pushPrefix("[2]", VerilatedTracePrefixType::ARRAY_UNPACKED);
    tracep->declBus(c+79,0,"[0]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+80,0,"[1]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+81,0,"[2]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+82,0,"[3]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->popPrefix();
    tracep->pushPrefix("[3]", VerilatedTracePrefixType::ARRAY_UNPACKED);
    tracep->declBus(c+83,0,"[0]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+84,0,"[1]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+85,0,"[2]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+86,0,"[3]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->popPrefix();
    tracep->popPrefix();
    tracep->pushPrefix("u_dut", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->declBus(c+465,0,"SIZE",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBus(c+466,0,"DATA_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBit(c+457,0,"clk",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+461,0,"store_weight_req",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->pushPrefix("weight_in", VerilatedTracePrefixType::ARRAY_UNPACKED);
    for (int i = 0; i < 4; ++i) {
        tracep->declBus(c+432+i*1,0,"",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, true,(i+0), 7,0);
    }
    tracep->popPrefix();
    tracep->pushPrefix("ia_vec_in", VerilatedTracePrefixType::ARRAY_UNPACKED);
    for (int i = 0; i < 4; ++i) {
        tracep->declBus(c+444+i*1,0,"",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, true,(i+0), 15,0);
    }
    tracep->popPrefix();
    tracep->declBit(c+462,0,"ia_row_valid",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+463,0,"ia_calc_done",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+464,0,"ia_is_init_data",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->pushPrefix("bias_in", VerilatedTracePrefixType::ARRAY_UNPACKED);
    for (int i = 0; i < 4; ++i) {
        tracep->declBus(c+420+i*1,0,"",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, true,(i+0), 31,0);
    }
    tracep->popPrefix();
    tracep->pushPrefix("acc_data_out", VerilatedTracePrefixType::ARRAY_UNPACKED);
    for (int i = 0; i < 4; ++i) {
        tracep->declBus(c+108+i*1,0,"",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, true,(i+0), 31,0);
    }
    tracep->popPrefix();
    tracep->declBit(c+112,0,"acc_data_valid",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+113,0,"tile_calc_over",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+114,0,"partial_sum_calc_over",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->pushPrefix("data_setup_out", VerilatedTracePrefixType::ARRAY_UNPACKED);
    for (int i = 0; i < 4; ++i) {
        tracep->declBus(c+412+i*1,0,"",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, true,(i+0), 15,0);
    }
    tracep->popPrefix();
    tracep->declBit(c+115,0,"data_setup_input_valid",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+116,0,"data_setup_calc_done",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+117,0,"data_setup_is_init_data",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->pushPrefix("sa_sum_out", VerilatedTracePrefixType::ARRAY_UNPACKED);
    for (int i = 0; i < 4; ++i) {
        tracep->declBus(c+118+i*1,0,"",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, true,(i+0), 31,0);
    }
    tracep->popPrefix();
    tracep->pushPrefix("u_accumulator_array", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->declBus(c+469,0,"SIZE",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+470,0,"DATA_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBit(c+457,0,"clk",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->pushPrefix("data_in", VerilatedTracePrefixType::ARRAY_UNPACKED);
    for (int i = 0; i < 4; ++i) {
        tracep->declBus(c+122+i*1,0,"",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, true,(i+0), 31,0);
    }
    tracep->popPrefix();
    tracep->declBit(c+116,0,"calc_done_i",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+115,0,"input_valid_i",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+117,0,"is_init_data_i",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->pushPrefix("data_out", VerilatedTracePrefixType::ARRAY_UNPACKED);
    for (int i = 0; i < 4; ++i) {
        tracep->declBus(c+126+i*1,0,"",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, true,(i+0), 31,0);
    }
    tracep->popPrefix();
    tracep->declBit(c+112,0,"calc_done_o",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+113,0,"tile_calc_over_o",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+114,0,"partial_sum_calc_over",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+130,0,"calc_done_chain",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 4,0);
    tracep->declBus(c+131,0,"input_valid_chain",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 4,0);
    tracep->declBus(c+132,0,"is_init_data_chain",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 4,0);
    tracep->declBit(c+133,0,"calc_done_o_d",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+134,0,"input_valid_chain_d",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+135,0,"input_valid_i_d",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+136,0,"read_ptr",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 1,0);
    tracep->pushPrefix("accumulator_gen[0]", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->pushPrefix("acc_inst", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->declBus(c+469,0,"STAGE_NUM",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+470,0,"DATA_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBit(c+457,0,"clk",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+137,0,"data_in",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBit(c+116,0,"calc_done_i",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+115,0,"input_valid_i",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+117,0,"is_init_data_i",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+136,0,"read_ptr_i",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 1,0);
    tracep->declBus(c+138,0,"data_out",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBit(c+139,0,"calc_done_o",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+140,0,"input_valid_o",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+141,0,"is_init_data_o",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->pushPrefix("acc_fifo", VerilatedTracePrefixType::ARRAY_UNPACKED);
    for (int i = 0; i < 4; ++i) {
        tracep->declBus(c+142+i*1,0,"",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, true,(i+0), 31,0);
    }
    tracep->popPrefix();
    tracep->declBit(c+141,0,"is_init_data_reg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+140,0,"input_valid_reg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+139,0,"calc_done_reg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+146,0,"write_ptr",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 1,0);
    tracep->declBit(c+147,0,"input_valid_i_d",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->pushPrefix("unnamedblk1", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->declQuad(c+148,0,"sum",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 32,0);
    tracep->popPrefix();
    tracep->popPrefix();
    tracep->popPrefix();
    tracep->pushPrefix("accumulator_gen[1]", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->pushPrefix("acc_inst", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->declBus(c+469,0,"STAGE_NUM",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+470,0,"DATA_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBit(c+457,0,"clk",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+150,0,"data_in",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBit(c+139,0,"calc_done_i",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+140,0,"input_valid_i",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+141,0,"is_init_data_i",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+136,0,"read_ptr_i",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 1,0);
    tracep->declBus(c+151,0,"data_out",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBit(c+152,0,"calc_done_o",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+153,0,"input_valid_o",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+154,0,"is_init_data_o",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->pushPrefix("acc_fifo", VerilatedTracePrefixType::ARRAY_UNPACKED);
    for (int i = 0; i < 4; ++i) {
        tracep->declBus(c+155+i*1,0,"",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, true,(i+0), 31,0);
    }
    tracep->popPrefix();
    tracep->declBit(c+154,0,"is_init_data_reg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+153,0,"input_valid_reg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+152,0,"calc_done_reg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+159,0,"write_ptr",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 1,0);
    tracep->declBit(c+160,0,"input_valid_i_d",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->pushPrefix("unnamedblk1", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->declQuad(c+161,0,"sum",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 32,0);
    tracep->popPrefix();
    tracep->popPrefix();
    tracep->popPrefix();
    tracep->pushPrefix("accumulator_gen[2]", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->pushPrefix("acc_inst", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->declBus(c+469,0,"STAGE_NUM",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+470,0,"DATA_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBit(c+457,0,"clk",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+163,0,"data_in",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBit(c+152,0,"calc_done_i",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+153,0,"input_valid_i",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+154,0,"is_init_data_i",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+136,0,"read_ptr_i",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 1,0);
    tracep->declBus(c+164,0,"data_out",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBit(c+165,0,"calc_done_o",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+166,0,"input_valid_o",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+167,0,"is_init_data_o",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->pushPrefix("acc_fifo", VerilatedTracePrefixType::ARRAY_UNPACKED);
    for (int i = 0; i < 4; ++i) {
        tracep->declBus(c+168+i*1,0,"",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, true,(i+0), 31,0);
    }
    tracep->popPrefix();
    tracep->declBit(c+167,0,"is_init_data_reg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+166,0,"input_valid_reg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+165,0,"calc_done_reg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+172,0,"write_ptr",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 1,0);
    tracep->declBit(c+173,0,"input_valid_i_d",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->pushPrefix("unnamedblk1", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->declQuad(c+174,0,"sum",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 32,0);
    tracep->popPrefix();
    tracep->popPrefix();
    tracep->popPrefix();
    tracep->pushPrefix("accumulator_gen[3]", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->pushPrefix("acc_inst", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->declBus(c+469,0,"STAGE_NUM",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+470,0,"DATA_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBit(c+457,0,"clk",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+176,0,"data_in",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBit(c+165,0,"calc_done_i",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+166,0,"input_valid_i",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+167,0,"is_init_data_i",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+136,0,"read_ptr_i",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 1,0);
    tracep->declBus(c+177,0,"data_out",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBit(c+112,0,"calc_done_o",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+178,0,"input_valid_o",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+179,0,"is_init_data_o",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->pushPrefix("acc_fifo", VerilatedTracePrefixType::ARRAY_UNPACKED);
    for (int i = 0; i < 4; ++i) {
        tracep->declBus(c+180+i*1,0,"",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, true,(i+0), 31,0);
    }
    tracep->popPrefix();
    tracep->declBit(c+179,0,"is_init_data_reg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+178,0,"input_valid_reg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+112,0,"calc_done_reg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+184,0,"write_ptr",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 1,0);
    tracep->declBit(c+185,0,"input_valid_i_d",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->pushPrefix("unnamedblk1", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->declQuad(c+186,0,"sum",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 32,0);
    tracep->popPrefix();
    tracep->popPrefix();
    tracep->popPrefix();
    tracep->popPrefix();
    tracep->pushPrefix("u_data_setup", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->declBus(c+471,0,"DATA_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+469,0,"DATA_NUM",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBit(c+457,0,"clk",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->pushPrefix("data_in", VerilatedTracePrefixType::ARRAY_UNPACKED);
    for (int i = 0; i < 4; ++i) {
        tracep->declBus(c+448+i*1,0,"",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, true,(i+0), 15,0);
    }
    tracep->popPrefix();
    tracep->pushPrefix("data_out", VerilatedTracePrefixType::ARRAY_UNPACKED);
    for (int i = 0; i < 4; ++i) {
        tracep->declBus(c+416+i*1,0,"",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, true,(i+0), 15,0);
    }
    tracep->popPrefix();
    tracep->declBit(c+462,0,"input_valid_i",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+463,0,"calc_done_i",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+464,0,"is_init_data_i",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+115,0,"input_valid_o",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+116,0,"calc_done_o",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+117,0,"is_init_data_o",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->pushPrefix("genblk1", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->pushPrefix("gen_control_delay", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->pushPrefix("input_valid_shift", VerilatedTracePrefixType::ARRAY_UNPACKED);
    for (int i = 0; i < 4; ++i) {
        tracep->declBit(c+188+i*1,0,"",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, true,(i+0));
    }
    tracep->popPrefix();
    tracep->pushPrefix("calc_done_shift", VerilatedTracePrefixType::ARRAY_UNPACKED);
    for (int i = 0; i < 4; ++i) {
        tracep->declBit(c+192+i*1,0,"",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, true,(i+0));
    }
    tracep->popPrefix();
    tracep->pushPrefix("is_init_data_shift", VerilatedTracePrefixType::ARRAY_UNPACKED);
    for (int i = 0; i < 4; ++i) {
        tracep->declBit(c+196+i*1,0,"",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, true,(i+0));
    }
    tracep->popPrefix();
    tracep->pushPrefix("unnamedblk1", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->declBus(c+200,0,"m",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::INTEGER, false,-1, 31,0);
    tracep->popPrefix();
    tracep->popPrefix();
    tracep->pushPrefix("gen_shift_chain[1]", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->pushPrefix("gen_delay_1", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->declBus(c+201,0,"shift_reg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->popPrefix();
    tracep->popPrefix();
    tracep->pushPrefix("gen_shift_chain[2]", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->pushPrefix("gen_delay_n", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->pushPrefix("shift_reg", VerilatedTracePrefixType::ARRAY_UNPACKED);
    for (int i = 0; i < 2; ++i) {
        tracep->declBus(c+202+i*1,0,"",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, true,(i+0), 15,0);
    }
    tracep->popPrefix();
    tracep->declBus(c+204,0,"k",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::INTEGER, false,-1, 31,0);
    tracep->popPrefix();
    tracep->popPrefix();
    tracep->pushPrefix("gen_shift_chain[3]", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->pushPrefix("gen_delay_n", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->pushPrefix("shift_reg", VerilatedTracePrefixType::ARRAY_UNPACKED);
    for (int i = 0; i < 3; ++i) {
        tracep->declBus(c+205+i*1,0,"",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, true,(i+0), 15,0);
    }
    tracep->popPrefix();
    tracep->declBus(c+208,0,"k",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::INTEGER, false,-1, 31,0);
    tracep->popPrefix();
    tracep->popPrefix();
    tracep->popPrefix();
    tracep->popPrefix();
    tracep->pushPrefix("u_systolic_array", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->declBus(c+465,0,"SIZE",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBit(c+457,0,"clk",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+461,0,"store_weight_req",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->pushPrefix("weight_in", VerilatedTracePrefixType::ARRAY_UNPACKED);
    for (int i = 0; i < 4; ++i) {
        tracep->declBus(c+432+i*1,0,"",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, true,(i+0), 7,0);
    }
    tracep->popPrefix();
    tracep->pushPrefix("data_in", VerilatedTracePrefixType::ARRAY_UNPACKED);
    for (int i = 0; i < 4; ++i) {
        tracep->declBus(c+412+i*1,0,"",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, true,(i+0), 15,0);
    }
    tracep->popPrefix();
    tracep->pushPrefix("sum_in", VerilatedTracePrefixType::ARRAY_UNPACKED);
    for (int i = 0; i < 4; ++i) {
        tracep->declBus(c+420+i*1,0,"",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, true,(i+0), 31,0);
    }
    tracep->popPrefix();
    tracep->pushPrefix("sum_out", VerilatedTracePrefixType::ARRAY_UNPACKED);
    for (int i = 0; i < 4; ++i) {
        tracep->declBus(c+118+i*1,0,"",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, true,(i+0), 31,0);
    }
    tracep->popPrefix();
    tracep->pushPrefix("data_pipe", VerilatedTracePrefixType::ARRAY_UNPACKED);
    tracep->pushPrefix("[0]", VerilatedTracePrefixType::ARRAY_UNPACKED);
    tracep->declBus(c+209,0,"[0]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->declBus(c+210,0,"[1]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->declBus(c+211,0,"[2]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->declBus(c+212,0,"[3]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->popPrefix();
    tracep->pushPrefix("[1]", VerilatedTracePrefixType::ARRAY_UNPACKED);
    tracep->declBus(c+213,0,"[0]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->declBus(c+214,0,"[1]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->declBus(c+215,0,"[2]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->declBus(c+216,0,"[3]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->popPrefix();
    tracep->pushPrefix("[2]", VerilatedTracePrefixType::ARRAY_UNPACKED);
    tracep->declBus(c+217,0,"[0]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->declBus(c+218,0,"[1]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->declBus(c+219,0,"[2]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->declBus(c+220,0,"[3]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->popPrefix();
    tracep->pushPrefix("[3]", VerilatedTracePrefixType::ARRAY_UNPACKED);
    tracep->declBus(c+221,0,"[0]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->declBus(c+222,0,"[1]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->declBus(c+223,0,"[2]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->declBus(c+224,0,"[3]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->popPrefix();
    tracep->popPrefix();
    tracep->pushPrefix("weight_pipe", VerilatedTracePrefixType::ARRAY_UNPACKED);
    tracep->pushPrefix("[0]", VerilatedTracePrefixType::ARRAY_UNPACKED);
    tracep->declBus(c+225,0,"[0]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+226,0,"[1]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+227,0,"[2]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+228,0,"[3]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->popPrefix();
    tracep->pushPrefix("[1]", VerilatedTracePrefixType::ARRAY_UNPACKED);
    tracep->declBus(c+229,0,"[0]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+230,0,"[1]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+231,0,"[2]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+232,0,"[3]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->popPrefix();
    tracep->pushPrefix("[2]", VerilatedTracePrefixType::ARRAY_UNPACKED);
    tracep->declBus(c+233,0,"[0]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+234,0,"[1]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+235,0,"[2]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+236,0,"[3]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->popPrefix();
    tracep->pushPrefix("[3]", VerilatedTracePrefixType::ARRAY_UNPACKED);
    tracep->declBus(c+237,0,"[0]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+238,0,"[1]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+239,0,"[2]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+240,0,"[3]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->popPrefix();
    tracep->popPrefix();
    tracep->pushPrefix("sum_pipe", VerilatedTracePrefixType::ARRAY_UNPACKED);
    tracep->pushPrefix("[0]", VerilatedTracePrefixType::ARRAY_UNPACKED);
    tracep->declBus(c+241,0,"[0]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+242,0,"[1]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+243,0,"[2]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+244,0,"[3]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->popPrefix();
    tracep->pushPrefix("[1]", VerilatedTracePrefixType::ARRAY_UNPACKED);
    tracep->declBus(c+245,0,"[0]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+246,0,"[1]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+247,0,"[2]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+248,0,"[3]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->popPrefix();
    tracep->pushPrefix("[2]", VerilatedTracePrefixType::ARRAY_UNPACKED);
    tracep->declBus(c+249,0,"[0]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+250,0,"[1]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+251,0,"[2]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+252,0,"[3]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->popPrefix();
    tracep->pushPrefix("[3]", VerilatedTracePrefixType::ARRAY_UNPACKED);
    tracep->declBus(c+253,0,"[0]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+254,0,"[1]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+255,0,"[2]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+256,0,"[3]",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->popPrefix();
    tracep->popPrefix();
    tracep->pushPrefix("gen_row[0]", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->pushPrefix("gen_col[0]", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->pushPrefix("ws_cell", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->declBus(c+466,0,"DATA_IN_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBus(c+472,0,"WEIGHT_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBus(c+473,0,"ACC_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBit(c+457,0,"clk",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+461,0,"store_weight_req",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+436,0,"weight_in",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+452,0,"data_in",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->declBus(c+424,0,"sum_in",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+257,0,"data_out",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->declBus(c+258,0,"weight_out",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+259,0,"sum_out",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+257,0,"data_reg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->declBus(c+258,0,"weight_reg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+260,0,"sum_reg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+261,0,"mult_result",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declQuad(c+262,0,"sum_ext",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 32,0);
    tracep->popPrefix();
    tracep->popPrefix();
    tracep->pushPrefix("gen_col[1]", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->pushPrefix("ws_cell", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->declBus(c+466,0,"DATA_IN_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBus(c+472,0,"WEIGHT_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBus(c+473,0,"ACC_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBit(c+457,0,"clk",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+461,0,"store_weight_req",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+437,0,"weight_in",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+264,0,"data_in",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->declBus(c+425,0,"sum_in",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+265,0,"data_out",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->declBus(c+266,0,"weight_out",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+267,0,"sum_out",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+265,0,"data_reg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->declBus(c+266,0,"weight_reg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+268,0,"sum_reg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+269,0,"mult_result",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declQuad(c+270,0,"sum_ext",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 32,0);
    tracep->popPrefix();
    tracep->popPrefix();
    tracep->pushPrefix("gen_col[2]", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->pushPrefix("ws_cell", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->declBus(c+466,0,"DATA_IN_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBus(c+472,0,"WEIGHT_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBus(c+473,0,"ACC_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBit(c+457,0,"clk",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+461,0,"store_weight_req",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+438,0,"weight_in",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+272,0,"data_in",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->declBus(c+426,0,"sum_in",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+273,0,"data_out",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->declBus(c+274,0,"weight_out",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+275,0,"sum_out",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+273,0,"data_reg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->declBus(c+274,0,"weight_reg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+276,0,"sum_reg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+277,0,"mult_result",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declQuad(c+278,0,"sum_ext",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 32,0);
    tracep->popPrefix();
    tracep->popPrefix();
    tracep->pushPrefix("gen_col[3]", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->pushPrefix("ws_cell", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->declBus(c+466,0,"DATA_IN_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBus(c+472,0,"WEIGHT_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBus(c+473,0,"ACC_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBit(c+457,0,"clk",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+461,0,"store_weight_req",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+439,0,"weight_in",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+280,0,"data_in",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->declBus(c+427,0,"sum_in",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+281,0,"data_out",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->declBus(c+282,0,"weight_out",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+283,0,"sum_out",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+281,0,"data_reg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->declBus(c+282,0,"weight_reg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+284,0,"sum_reg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+285,0,"mult_result",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declQuad(c+286,0,"sum_ext",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 32,0);
    tracep->popPrefix();
    tracep->popPrefix();
    tracep->popPrefix();
    tracep->pushPrefix("gen_row[1]", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->pushPrefix("gen_col[0]", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->pushPrefix("ws_cell", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->declBus(c+466,0,"DATA_IN_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBus(c+472,0,"WEIGHT_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBus(c+473,0,"ACC_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBit(c+457,0,"clk",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+461,0,"store_weight_req",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+288,0,"weight_in",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+201,0,"data_in",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->declBus(c+289,0,"sum_in",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+290,0,"data_out",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->declBus(c+291,0,"weight_out",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+292,0,"sum_out",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+290,0,"data_reg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->declBus(c+291,0,"weight_reg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+293,0,"sum_reg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+294,0,"mult_result",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declQuad(c+295,0,"sum_ext",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 32,0);
    tracep->popPrefix();
    tracep->popPrefix();
    tracep->pushPrefix("gen_col[1]", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->pushPrefix("ws_cell", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->declBus(c+466,0,"DATA_IN_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBus(c+472,0,"WEIGHT_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBus(c+473,0,"ACC_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBit(c+457,0,"clk",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+461,0,"store_weight_req",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+297,0,"weight_in",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+298,0,"data_in",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->declBus(c+299,0,"sum_in",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+300,0,"data_out",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->declBus(c+301,0,"weight_out",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+302,0,"sum_out",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+300,0,"data_reg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->declBus(c+301,0,"weight_reg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+303,0,"sum_reg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+304,0,"mult_result",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declQuad(c+305,0,"sum_ext",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 32,0);
    tracep->popPrefix();
    tracep->popPrefix();
    tracep->pushPrefix("gen_col[2]", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->pushPrefix("ws_cell", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->declBus(c+466,0,"DATA_IN_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBus(c+472,0,"WEIGHT_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBus(c+473,0,"ACC_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBit(c+457,0,"clk",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+461,0,"store_weight_req",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+307,0,"weight_in",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+308,0,"data_in",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->declBus(c+309,0,"sum_in",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+310,0,"data_out",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->declBus(c+311,0,"weight_out",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+312,0,"sum_out",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+310,0,"data_reg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->declBus(c+311,0,"weight_reg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+313,0,"sum_reg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+314,0,"mult_result",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declQuad(c+315,0,"sum_ext",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 32,0);
    tracep->popPrefix();
    tracep->popPrefix();
    tracep->pushPrefix("gen_col[3]", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->pushPrefix("ws_cell", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->declBus(c+466,0,"DATA_IN_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBus(c+472,0,"WEIGHT_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBus(c+473,0,"ACC_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBit(c+457,0,"clk",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+461,0,"store_weight_req",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+317,0,"weight_in",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+318,0,"data_in",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->declBus(c+319,0,"sum_in",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+320,0,"data_out",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->declBus(c+321,0,"weight_out",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+322,0,"sum_out",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+320,0,"data_reg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->declBus(c+321,0,"weight_reg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+323,0,"sum_reg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+324,0,"mult_result",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declQuad(c+325,0,"sum_ext",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 32,0);
    tracep->popPrefix();
    tracep->popPrefix();
    tracep->popPrefix();
    tracep->pushPrefix("gen_row[2]", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->pushPrefix("gen_col[0]", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->pushPrefix("ws_cell", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->declBus(c+466,0,"DATA_IN_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBus(c+472,0,"WEIGHT_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBus(c+473,0,"ACC_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBit(c+457,0,"clk",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+461,0,"store_weight_req",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+327,0,"weight_in",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+328,0,"data_in",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->declBus(c+329,0,"sum_in",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+330,0,"data_out",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->declBus(c+331,0,"weight_out",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+332,0,"sum_out",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+330,0,"data_reg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->declBus(c+331,0,"weight_reg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+333,0,"sum_reg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+334,0,"mult_result",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declQuad(c+335,0,"sum_ext",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 32,0);
    tracep->popPrefix();
    tracep->popPrefix();
    tracep->pushPrefix("gen_col[1]", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->pushPrefix("ws_cell", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->declBus(c+466,0,"DATA_IN_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBus(c+472,0,"WEIGHT_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBus(c+473,0,"ACC_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBit(c+457,0,"clk",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+461,0,"store_weight_req",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+337,0,"weight_in",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+338,0,"data_in",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->declBus(c+339,0,"sum_in",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+340,0,"data_out",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->declBus(c+341,0,"weight_out",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+342,0,"sum_out",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+340,0,"data_reg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->declBus(c+341,0,"weight_reg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+343,0,"sum_reg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+344,0,"mult_result",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declQuad(c+345,0,"sum_ext",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 32,0);
    tracep->popPrefix();
    tracep->popPrefix();
    tracep->pushPrefix("gen_col[2]", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->pushPrefix("ws_cell", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->declBus(c+466,0,"DATA_IN_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBus(c+472,0,"WEIGHT_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBus(c+473,0,"ACC_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBit(c+457,0,"clk",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+461,0,"store_weight_req",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+347,0,"weight_in",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+348,0,"data_in",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->declBus(c+349,0,"sum_in",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+350,0,"data_out",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->declBus(c+351,0,"weight_out",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+352,0,"sum_out",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+350,0,"data_reg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->declBus(c+351,0,"weight_reg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+353,0,"sum_reg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+354,0,"mult_result",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declQuad(c+355,0,"sum_ext",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 32,0);
    tracep->popPrefix();
    tracep->popPrefix();
    tracep->pushPrefix("gen_col[3]", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->pushPrefix("ws_cell", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->declBus(c+466,0,"DATA_IN_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBus(c+472,0,"WEIGHT_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBus(c+473,0,"ACC_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBit(c+457,0,"clk",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+461,0,"store_weight_req",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+357,0,"weight_in",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+358,0,"data_in",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->declBus(c+359,0,"sum_in",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+360,0,"data_out",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->declBus(c+361,0,"weight_out",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+362,0,"sum_out",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+360,0,"data_reg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->declBus(c+361,0,"weight_reg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+363,0,"sum_reg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+364,0,"mult_result",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declQuad(c+365,0,"sum_ext",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 32,0);
    tracep->popPrefix();
    tracep->popPrefix();
    tracep->popPrefix();
    tracep->pushPrefix("gen_row[3]", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->pushPrefix("gen_col[0]", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->pushPrefix("ws_cell", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->declBus(c+466,0,"DATA_IN_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBus(c+472,0,"WEIGHT_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBus(c+473,0,"ACC_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBit(c+457,0,"clk",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+461,0,"store_weight_req",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+367,0,"weight_in",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+368,0,"data_in",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->declBus(c+369,0,"sum_in",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+370,0,"data_out",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->declBus(c+371,0,"weight_out",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+372,0,"sum_out",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+370,0,"data_reg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->declBus(c+371,0,"weight_reg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+373,0,"sum_reg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+374,0,"mult_result",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declQuad(c+375,0,"sum_ext",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 32,0);
    tracep->popPrefix();
    tracep->popPrefix();
    tracep->pushPrefix("gen_col[1]", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->pushPrefix("ws_cell", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->declBus(c+466,0,"DATA_IN_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBus(c+472,0,"WEIGHT_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBus(c+473,0,"ACC_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBit(c+457,0,"clk",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+461,0,"store_weight_req",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+377,0,"weight_in",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+378,0,"data_in",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->declBus(c+379,0,"sum_in",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+380,0,"data_out",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->declBus(c+381,0,"weight_out",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+382,0,"sum_out",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+380,0,"data_reg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->declBus(c+381,0,"weight_reg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+383,0,"sum_reg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+384,0,"mult_result",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declQuad(c+385,0,"sum_ext",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 32,0);
    tracep->popPrefix();
    tracep->popPrefix();
    tracep->pushPrefix("gen_col[2]", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->pushPrefix("ws_cell", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->declBus(c+466,0,"DATA_IN_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBus(c+472,0,"WEIGHT_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBus(c+473,0,"ACC_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBit(c+457,0,"clk",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+461,0,"store_weight_req",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+387,0,"weight_in",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+388,0,"data_in",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->declBus(c+389,0,"sum_in",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+390,0,"data_out",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->declBus(c+391,0,"weight_out",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+392,0,"sum_out",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+390,0,"data_reg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->declBus(c+391,0,"weight_reg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+393,0,"sum_reg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+394,0,"mult_result",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declQuad(c+395,0,"sum_ext",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 32,0);
    tracep->popPrefix();
    tracep->popPrefix();
    tracep->pushPrefix("gen_col[3]", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->pushPrefix("ws_cell", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->declBus(c+466,0,"DATA_IN_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBus(c+472,0,"WEIGHT_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBus(c+473,0,"ACC_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBit(c+457,0,"clk",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+461,0,"store_weight_req",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+397,0,"weight_in",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+398,0,"data_in",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->declBus(c+399,0,"sum_in",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+400,0,"data_out",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->declBus(c+401,0,"weight_out",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+402,0,"sum_out",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+400,0,"data_reg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 15,0);
    tracep->declBus(c+401,0,"weight_reg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+403,0,"sum_reg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+404,0,"mult_result",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declQuad(c+405,0,"sum_ext",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 32,0);
    tracep->popPrefix();
    tracep->popPrefix();
    tracep->popPrefix();
    tracep->popPrefix();
    tracep->popPrefix();
    tracep->pushPrefix("unnamedblk1", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->declBus(c+407,0,"c",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->popPrefix();
    tracep->pushPrefix("unnamedblk2", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->declBus(c+87,0,"i",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->popPrefix();
    tracep->pushPrefix("unnamedblk3", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->declBus(c+88,0,"i",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->popPrefix();
    tracep->pushPrefix("unnamedblk4", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->declBus(c+89,0,"seg",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->popPrefix();
    tracep->pushPrefix("unnamedblk5", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->declBus(c+90,0,"r",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->pushPrefix("unnamedblk6", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->declBus(c+91,0,"c",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->popPrefix();
    tracep->popPrefix();
    tracep->popPrefix();
}

VL_ATTR_COLD void Vtb_compute_core___024root__trace_init_sub__TOP__tb_compute_core__DOT__tb_if__0(Vtb_compute_core___024root* vlSelf, VerilatedVcd* tracep) {
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_compute_core___024root__trace_init_sub__TOP__tb_compute_core__DOT__tb_if__0\n"); );
    Vtb_compute_core__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    auto& vlSelfRef = std::ref(*vlSelf).get();
    // Init
    const int c = vlSymsp->__Vm_baseCode;
    // Body
    tracep->declBit(c+457,0,"clk",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+465,0,"SIZE",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBus(c+466,0,"DATA_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBit(c+461,0,"store_weight_req",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->pushPrefix("weight_in", VerilatedTracePrefixType::ARRAY_UNPACKED);
    for (int i = 0; i < 4; ++i) {
        tracep->declBus(c+440+i*1,0,"",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, true,(i+0), 7,0);
    }
    tracep->popPrefix();
    tracep->pushPrefix("ia_vec_in", VerilatedTracePrefixType::ARRAY_UNPACKED);
    for (int i = 0; i < 4; ++i) {
        tracep->declBus(c+453+i*1,0,"",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, true,(i+0), 15,0);
    }
    tracep->popPrefix();
    tracep->declBit(c+462,0,"ia_row_valid",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+463,0,"ia_calc_done",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+464,0,"ia_is_init_data",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->pushPrefix("bias_in", VerilatedTracePrefixType::ARRAY_UNPACKED);
    for (int i = 0; i < 4; ++i) {
        tracep->declBus(c+428+i*1,0,"",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, true,(i+0), 31,0);
    }
    tracep->popPrefix();
    tracep->pushPrefix("acc_data_out", VerilatedTracePrefixType::ARRAY_UNPACKED);
    for (int i = 0; i < 4; ++i) {
        tracep->declBus(c+408+i*1,0,"",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, true,(i+0), 31,0);
    }
    tracep->popPrefix();
    tracep->declBit(c+112,0,"acc_data_valid",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+113,0,"tile_calc_over",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+114,0,"partial_sum_calc_over",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
}

VL_ATTR_COLD void Vtb_compute_core___024root__trace_init_top(Vtb_compute_core___024root* vlSelf, VerilatedVcd* tracep) {
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_compute_core___024root__trace_init_top\n"); );
    Vtb_compute_core__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    auto& vlSelfRef = std::ref(*vlSelf).get();
    // Body
    Vtb_compute_core___024root__trace_init_sub__TOP__0(vlSelf, tracep);
}

VL_ATTR_COLD void Vtb_compute_core___024root__trace_const_0(void* voidSelf, VerilatedVcd::Buffer* bufp);
VL_ATTR_COLD void Vtb_compute_core___024root__trace_full_0(void* voidSelf, VerilatedVcd::Buffer* bufp);
void Vtb_compute_core___024root__trace_chg_0(void* voidSelf, VerilatedVcd::Buffer* bufp);
void Vtb_compute_core___024root__trace_cleanup(void* voidSelf, VerilatedVcd* /*unused*/);

VL_ATTR_COLD void Vtb_compute_core___024root__trace_register(Vtb_compute_core___024root* vlSelf, VerilatedVcd* tracep) {
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_compute_core___024root__trace_register\n"); );
    Vtb_compute_core__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    auto& vlSelfRef = std::ref(*vlSelf).get();
    // Body
    tracep->addConstCb(&Vtb_compute_core___024root__trace_const_0, 0U, vlSelf);
    tracep->addFullCb(&Vtb_compute_core___024root__trace_full_0, 0U, vlSelf);
    tracep->addChgCb(&Vtb_compute_core___024root__trace_chg_0, 0U, vlSelf);
    tracep->addCleanupCb(&Vtb_compute_core___024root__trace_cleanup, vlSelf);
}

VL_ATTR_COLD void Vtb_compute_core___024root__trace_const_0_sub_0(Vtb_compute_core___024root* vlSelf, VerilatedVcd::Buffer* bufp);

VL_ATTR_COLD void Vtb_compute_core___024root__trace_const_0(void* voidSelf, VerilatedVcd::Buffer* bufp) {
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_compute_core___024root__trace_const_0\n"); );
    // Init
    Vtb_compute_core___024root* const __restrict vlSelf VL_ATTR_UNUSED = static_cast<Vtb_compute_core___024root*>(voidSelf);
    Vtb_compute_core__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    // Body
    Vtb_compute_core___024root__trace_const_0_sub_0((&vlSymsp->TOP), bufp);
}

VL_ATTR_COLD void Vtb_compute_core___024root__trace_const_0_sub_0(Vtb_compute_core___024root* vlSelf, VerilatedVcd::Buffer* bufp) {
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_compute_core___024root__trace_const_0_sub_0\n"); );
    Vtb_compute_core__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    auto& vlSelfRef = std::ref(*vlSelf).get();
    // Init
    uint32_t* const oldp VL_ATTR_UNUSED = bufp->oldp(vlSymsp->__Vm_baseCode);
    // Body
    bufp->fullIData(oldp+465,(4U),32);
    bufp->fullIData(oldp+466,(0x10U),32);
    bufp->fullIData(oldp+467,(0x10U),32);
    bufp->fullIData(oldp+468,(0x20U),32);
    bufp->fullIData(oldp+469,(4U),32);
    bufp->fullIData(oldp+470,(0x20U),32);
    bufp->fullIData(oldp+471,(0x10U),32);
    bufp->fullIData(oldp+472,(8U),32);
    bufp->fullIData(oldp+473,(0x20U),32);
}

VL_ATTR_COLD void Vtb_compute_core___024root__trace_full_0_sub_0(Vtb_compute_core___024root* vlSelf, VerilatedVcd::Buffer* bufp);

VL_ATTR_COLD void Vtb_compute_core___024root__trace_full_0(void* voidSelf, VerilatedVcd::Buffer* bufp) {
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_compute_core___024root__trace_full_0\n"); );
    // Init
    Vtb_compute_core___024root* const __restrict vlSelf VL_ATTR_UNUSED = static_cast<Vtb_compute_core___024root*>(voidSelf);
    Vtb_compute_core__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    // Body
    Vtb_compute_core___024root__trace_full_0_sub_0((&vlSymsp->TOP), bufp);
}

VL_ATTR_COLD void Vtb_compute_core___024root__trace_full_0_sub_0(Vtb_compute_core___024root* vlSelf, VerilatedVcd::Buffer* bufp) {
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_compute_core___024root__trace_full_0_sub_0\n"); );
    Vtb_compute_core__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    auto& vlSelfRef = std::ref(*vlSelf).get();
    // Init
    uint32_t* const oldp VL_ATTR_UNUSED = bufp->oldp(vlSymsp->__Vm_baseCode);
    // Body
    bufp->fullIData(oldp+1,(vlSelfRef.tb_compute_core__DOT__weight_mem[0]),32);
    bufp->fullIData(oldp+2,(vlSelfRef.tb_compute_core__DOT__weight_mem[1]),32);
    bufp->fullIData(oldp+3,(vlSelfRef.tb_compute_core__DOT__weight_mem[2]),32);
    bufp->fullIData(oldp+4,(vlSelfRef.tb_compute_core__DOT__weight_mem[3]),32);
    bufp->fullIData(oldp+5,(vlSelfRef.tb_compute_core__DOT__weight_mem[4]),32);
    bufp->fullIData(oldp+6,(vlSelfRef.tb_compute_core__DOT__weight_mem[5]),32);
    bufp->fullIData(oldp+7,(vlSelfRef.tb_compute_core__DOT__weight_mem[6]),32);
    bufp->fullIData(oldp+8,(vlSelfRef.tb_compute_core__DOT__weight_mem[7]),32);
    bufp->fullIData(oldp+9,(vlSelfRef.tb_compute_core__DOT__weight_mem[8]),32);
    bufp->fullIData(oldp+10,(vlSelfRef.tb_compute_core__DOT__weight_mem[9]),32);
    bufp->fullIData(oldp+11,(vlSelfRef.tb_compute_core__DOT__weight_mem[10]),32);
    bufp->fullIData(oldp+12,(vlSelfRef.tb_compute_core__DOT__weight_mem[11]),32);
    bufp->fullIData(oldp+13,(vlSelfRef.tb_compute_core__DOT__weight_mem[12]),32);
    bufp->fullIData(oldp+14,(vlSelfRef.tb_compute_core__DOT__weight_mem[13]),32);
    bufp->fullIData(oldp+15,(vlSelfRef.tb_compute_core__DOT__weight_mem[14]),32);
    bufp->fullIData(oldp+16,(vlSelfRef.tb_compute_core__DOT__weight_mem[15]),32);
    bufp->fullIData(oldp+17,(vlSelfRef.tb_compute_core__DOT__ia_mem[0]),32);
    bufp->fullIData(oldp+18,(vlSelfRef.tb_compute_core__DOT__ia_mem[1]),32);
    bufp->fullIData(oldp+19,(vlSelfRef.tb_compute_core__DOT__ia_mem[2]),32);
    bufp->fullIData(oldp+20,(vlSelfRef.tb_compute_core__DOT__ia_mem[3]),32);
    bufp->fullIData(oldp+21,(vlSelfRef.tb_compute_core__DOT__ia_mem[4]),32);
    bufp->fullIData(oldp+22,(vlSelfRef.tb_compute_core__DOT__ia_mem[5]),32);
    bufp->fullIData(oldp+23,(vlSelfRef.tb_compute_core__DOT__ia_mem[6]),32);
    bufp->fullIData(oldp+24,(vlSelfRef.tb_compute_core__DOT__ia_mem[7]),32);
    bufp->fullIData(oldp+25,(vlSelfRef.tb_compute_core__DOT__ia_mem[8]),32);
    bufp->fullIData(oldp+26,(vlSelfRef.tb_compute_core__DOT__ia_mem[9]),32);
    bufp->fullIData(oldp+27,(vlSelfRef.tb_compute_core__DOT__ia_mem[10]),32);
    bufp->fullIData(oldp+28,(vlSelfRef.tb_compute_core__DOT__ia_mem[11]),32);
    bufp->fullIData(oldp+29,(vlSelfRef.tb_compute_core__DOT__ia_mem[12]),32);
    bufp->fullIData(oldp+30,(vlSelfRef.tb_compute_core__DOT__ia_mem[13]),32);
    bufp->fullIData(oldp+31,(vlSelfRef.tb_compute_core__DOT__ia_mem[14]),32);
    bufp->fullIData(oldp+32,(vlSelfRef.tb_compute_core__DOT__ia_mem[15]),32);
    bufp->fullIData(oldp+33,(vlSelfRef.tb_compute_core__DOT__ia_mem[16]),32);
    bufp->fullIData(oldp+34,(vlSelfRef.tb_compute_core__DOT__ia_mem[17]),32);
    bufp->fullIData(oldp+35,(vlSelfRef.tb_compute_core__DOT__ia_mem[18]),32);
    bufp->fullIData(oldp+36,(vlSelfRef.tb_compute_core__DOT__ia_mem[19]),32);
    bufp->fullIData(oldp+37,(vlSelfRef.tb_compute_core__DOT__ia_mem[20]),32);
    bufp->fullIData(oldp+38,(vlSelfRef.tb_compute_core__DOT__ia_mem[21]),32);
    bufp->fullIData(oldp+39,(vlSelfRef.tb_compute_core__DOT__ia_mem[22]),32);
    bufp->fullIData(oldp+40,(vlSelfRef.tb_compute_core__DOT__ia_mem[23]),32);
    bufp->fullIData(oldp+41,(vlSelfRef.tb_compute_core__DOT__ia_mem[24]),32);
    bufp->fullIData(oldp+42,(vlSelfRef.tb_compute_core__DOT__ia_mem[25]),32);
    bufp->fullIData(oldp+43,(vlSelfRef.tb_compute_core__DOT__ia_mem[26]),32);
    bufp->fullIData(oldp+44,(vlSelfRef.tb_compute_core__DOT__ia_mem[27]),32);
    bufp->fullIData(oldp+45,(vlSelfRef.tb_compute_core__DOT__ia_mem[28]),32);
    bufp->fullIData(oldp+46,(vlSelfRef.tb_compute_core__DOT__ia_mem[29]),32);
    bufp->fullIData(oldp+47,(vlSelfRef.tb_compute_core__DOT__ia_mem[30]),32);
    bufp->fullIData(oldp+48,(vlSelfRef.tb_compute_core__DOT__ia_mem[31]),32);
    bufp->fullIData(oldp+49,(vlSelfRef.tb_compute_core__DOT__exp_mem[0]),32);
    bufp->fullIData(oldp+50,(vlSelfRef.tb_compute_core__DOT__exp_mem[1]),32);
    bufp->fullIData(oldp+51,(vlSelfRef.tb_compute_core__DOT__exp_mem[2]),32);
    bufp->fullIData(oldp+52,(vlSelfRef.tb_compute_core__DOT__exp_mem[3]),32);
    bufp->fullIData(oldp+53,(vlSelfRef.tb_compute_core__DOT__exp_mem[4]),32);
    bufp->fullIData(oldp+54,(vlSelfRef.tb_compute_core__DOT__exp_mem[5]),32);
    bufp->fullIData(oldp+55,(vlSelfRef.tb_compute_core__DOT__exp_mem[6]),32);
    bufp->fullIData(oldp+56,(vlSelfRef.tb_compute_core__DOT__exp_mem[7]),32);
    bufp->fullIData(oldp+57,(vlSelfRef.tb_compute_core__DOT__exp_mem[8]),32);
    bufp->fullIData(oldp+58,(vlSelfRef.tb_compute_core__DOT__exp_mem[9]),32);
    bufp->fullIData(oldp+59,(vlSelfRef.tb_compute_core__DOT__exp_mem[10]),32);
    bufp->fullIData(oldp+60,(vlSelfRef.tb_compute_core__DOT__exp_mem[11]),32);
    bufp->fullIData(oldp+61,(vlSelfRef.tb_compute_core__DOT__exp_mem[12]),32);
    bufp->fullIData(oldp+62,(vlSelfRef.tb_compute_core__DOT__exp_mem[13]),32);
    bufp->fullIData(oldp+63,(vlSelfRef.tb_compute_core__DOT__exp_mem[14]),32);
    bufp->fullIData(oldp+64,(vlSelfRef.tb_compute_core__DOT__exp_mem[15]),32);
    bufp->fullIData(oldp+65,(vlSelfRef.tb_compute_core__DOT__bias_mem[0]),32);
    bufp->fullIData(oldp+66,(vlSelfRef.tb_compute_core__DOT__bias_mem[1]),32);
    bufp->fullIData(oldp+67,(vlSelfRef.tb_compute_core__DOT__bias_mem[2]),32);
    bufp->fullIData(oldp+68,(vlSelfRef.tb_compute_core__DOT__bias_mem[3]),32);
    bufp->fullIData(oldp+69,(vlSelfRef.tb_compute_core__DOT__errors),32);
    bufp->fullIData(oldp+70,(vlSelfRef.tb_compute_core__DOT__idx),32);
    bufp->fullCData(oldp+71,(vlSelfRef.tb_compute_core__DOT__tile_buf
                             [0U][0U]),8);
    bufp->fullCData(oldp+72,(vlSelfRef.tb_compute_core__DOT__tile_buf
                             [0U][1U]),8);
    bufp->fullCData(oldp+73,(vlSelfRef.tb_compute_core__DOT__tile_buf
                             [0U][2U]),8);
    bufp->fullCData(oldp+74,(vlSelfRef.tb_compute_core__DOT__tile_buf
                             [0U][3U]),8);
    bufp->fullCData(oldp+75,(vlSelfRef.tb_compute_core__DOT__tile_buf
                             [1U][0U]),8);
    bufp->fullCData(oldp+76,(vlSelfRef.tb_compute_core__DOT__tile_buf
                             [1U][1U]),8);
    bufp->fullCData(oldp+77,(vlSelfRef.tb_compute_core__DOT__tile_buf
                             [1U][2U]),8);
    bufp->fullCData(oldp+78,(vlSelfRef.tb_compute_core__DOT__tile_buf
                             [1U][3U]),8);
    bufp->fullCData(oldp+79,(vlSelfRef.tb_compute_core__DOT__tile_buf
                             [2U][0U]),8);
    bufp->fullCData(oldp+80,(vlSelfRef.tb_compute_core__DOT__tile_buf
                             [2U][1U]),8);
    bufp->fullCData(oldp+81,(vlSelfRef.tb_compute_core__DOT__tile_buf
                             [2U][2U]),8);
    bufp->fullCData(oldp+82,(vlSelfRef.tb_compute_core__DOT__tile_buf
                             [2U][3U]),8);
    bufp->fullCData(oldp+83,(vlSelfRef.tb_compute_core__DOT__tile_buf
                             [3U][0U]),8);
    bufp->fullCData(oldp+84,(vlSelfRef.tb_compute_core__DOT__tile_buf
                             [3U][1U]),8);
    bufp->fullCData(oldp+85,(vlSelfRef.tb_compute_core__DOT__tile_buf
                             [3U][2U]),8);
    bufp->fullCData(oldp+86,(vlSelfRef.tb_compute_core__DOT__tile_buf
                             [3U][3U]),8);
    bufp->fullIData(oldp+87,(vlSelfRef.tb_compute_core__DOT__unnamedblk2__DOT__i),32);
    bufp->fullIData(oldp+88,(vlSelfRef.tb_compute_core__DOT__unnamedblk3__DOT__i),32);
    bufp->fullIData(oldp+89,(vlSelfRef.tb_compute_core__DOT__unnamedblk4__DOT__seg),32);
    bufp->fullIData(oldp+90,(vlSelfRef.tb_compute_core__DOT__unnamedblk5__DOT__r),32);
    bufp->fullIData(oldp+91,(vlSelfRef.tb_compute_core__DOT__unnamedblk5__DOT__unnamedblk6__DOT__c),32);
    bufp->fullIData(oldp+92,(vlSelfRef.tb_compute_core__DOT__out_buf[0]),32);
    bufp->fullIData(oldp+93,(vlSelfRef.tb_compute_core__DOT__out_buf[1]),32);
    bufp->fullIData(oldp+94,(vlSelfRef.tb_compute_core__DOT__out_buf[2]),32);
    bufp->fullIData(oldp+95,(vlSelfRef.tb_compute_core__DOT__out_buf[3]),32);
    bufp->fullIData(oldp+96,(vlSelfRef.tb_compute_core__DOT__out_buf[4]),32);
    bufp->fullIData(oldp+97,(vlSelfRef.tb_compute_core__DOT__out_buf[5]),32);
    bufp->fullIData(oldp+98,(vlSelfRef.tb_compute_core__DOT__out_buf[6]),32);
    bufp->fullIData(oldp+99,(vlSelfRef.tb_compute_core__DOT__out_buf[7]),32);
    bufp->fullIData(oldp+100,(vlSelfRef.tb_compute_core__DOT__out_buf[8]),32);
    bufp->fullIData(oldp+101,(vlSelfRef.tb_compute_core__DOT__out_buf[9]),32);
    bufp->fullIData(oldp+102,(vlSelfRef.tb_compute_core__DOT__out_buf[10]),32);
    bufp->fullIData(oldp+103,(vlSelfRef.tb_compute_core__DOT__out_buf[11]),32);
    bufp->fullIData(oldp+104,(vlSelfRef.tb_compute_core__DOT__out_buf[12]),32);
    bufp->fullIData(oldp+105,(vlSelfRef.tb_compute_core__DOT__out_buf[13]),32);
    bufp->fullIData(oldp+106,(vlSelfRef.tb_compute_core__DOT__out_buf[14]),32);
    bufp->fullIData(oldp+107,(vlSelfRef.tb_compute_core__DOT__out_buf[15]),32);
    bufp->fullIData(oldp+108,(vlSelfRef.tb_compute_core__DOT____Vcellout__u_dut__acc_data_out[0]),32);
    bufp->fullIData(oldp+109,(vlSelfRef.tb_compute_core__DOT____Vcellout__u_dut__acc_data_out[1]),32);
    bufp->fullIData(oldp+110,(vlSelfRef.tb_compute_core__DOT____Vcellout__u_dut__acc_data_out[2]),32);
    bufp->fullIData(oldp+111,(vlSelfRef.tb_compute_core__DOT____Vcellout__u_dut__acc_data_out[3]),32);
    bufp->fullBit(oldp+112,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__calc_done_reg));
    bufp->fullBit(oldp+113,(vlSelfRef.tb_compute_core__DOT____Vcellout__u_dut__tile_calc_over));
    bufp->fullBit(oldp+114,(vlSelfRef.tb_compute_core__DOT____Vcellout__u_dut__partial_sum_calc_over));
    bufp->fullBit(oldp+115,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__input_valid_shift
                            [3U]));
    bufp->fullBit(oldp+116,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__calc_done_shift
                            [3U]));
    bufp->fullBit(oldp+117,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__is_init_data_shift
                            [3U]));
    bufp->fullIData(oldp+118,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__sa_sum_out[0]),32);
    bufp->fullIData(oldp+119,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__sa_sum_out[1]),32);
    bufp->fullIData(oldp+120,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__sa_sum_out[2]),32);
    bufp->fullIData(oldp+121,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__sa_sum_out[3]),32);
    bufp->fullIData(oldp+122,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellinp__u_accumulator_array__data_in[0]),32);
    bufp->fullIData(oldp+123,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellinp__u_accumulator_array__data_in[1]),32);
    bufp->fullIData(oldp+124,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellinp__u_accumulator_array__data_in[2]),32);
    bufp->fullIData(oldp+125,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellinp__u_accumulator_array__data_in[3]),32);
    bufp->fullIData(oldp+126,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellout__u_accumulator_array__data_out[0]),32);
    bufp->fullIData(oldp+127,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellout__u_accumulator_array__data_out[1]),32);
    bufp->fullIData(oldp+128,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellout__u_accumulator_array__data_out[2]),32);
    bufp->fullIData(oldp+129,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellout__u_accumulator_array__data_out[3]),32);
    bufp->fullCData(oldp+130,(((((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__calc_done_reg) 
                                 << 4U) | (((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__calc_done_reg) 
                                            << 3U) 
                                           | ((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__calc_done_reg) 
                                              << 2U))) 
                               | (((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__calc_done_reg) 
                                   << 1U) | vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__calc_done_shift
                                  [3U]))),5);
    bufp->fullCData(oldp+131,(((((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__input_valid_reg) 
                                 << 4U) | (((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__input_valid_reg) 
                                            << 3U) 
                                           | ((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__input_valid_reg) 
                                              << 2U))) 
                               | (((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__input_valid_reg) 
                                   << 1U) | vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__input_valid_shift
                                  [3U]))),5);
    bufp->fullCData(oldp+132,(((((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__is_init_data_reg) 
                                 << 4U) | (((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__is_init_data_reg) 
                                            << 3U) 
                                           | ((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__is_init_data_reg) 
                                              << 2U))) 
                               | (((IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__is_init_data_reg) 
                                   << 1U) | vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__is_init_data_shift
                                  [3U]))),5);
    bufp->fullBit(oldp+133,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__calc_done_o_d));
    bufp->fullBit(oldp+134,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__input_valid_chain_d));
    bufp->fullBit(oldp+135,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__input_valid_i_d));
    bufp->fullCData(oldp+136,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__read_ptr),2);
    bufp->fullIData(oldp+137,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__sa_sum_out
                              [0U]),32);
    bufp->fullIData(oldp+138,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__acc_fifo
                              [vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__read_ptr]),32);
    bufp->fullBit(oldp+139,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__calc_done_reg));
    bufp->fullBit(oldp+140,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__input_valid_reg));
    bufp->fullBit(oldp+141,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__is_init_data_reg));
    bufp->fullIData(oldp+142,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__acc_fifo[0]),32);
    bufp->fullIData(oldp+143,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__acc_fifo[1]),32);
    bufp->fullIData(oldp+144,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__acc_fifo[2]),32);
    bufp->fullIData(oldp+145,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__acc_fifo[3]),32);
    bufp->fullCData(oldp+146,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__write_ptr),2);
    bufp->fullBit(oldp+147,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__input_valid_i_d));
    bufp->fullQData(oldp+148,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__0__KET____DOT__acc_inst__DOT__unnamedblk1__DOT__sum),33);
    bufp->fullIData(oldp+150,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__sa_sum_out
                              [1U]),32);
    bufp->fullIData(oldp+151,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__acc_fifo
                              [vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__read_ptr]),32);
    bufp->fullBit(oldp+152,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__calc_done_reg));
    bufp->fullBit(oldp+153,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__input_valid_reg));
    bufp->fullBit(oldp+154,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__is_init_data_reg));
    bufp->fullIData(oldp+155,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__acc_fifo[0]),32);
    bufp->fullIData(oldp+156,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__acc_fifo[1]),32);
    bufp->fullIData(oldp+157,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__acc_fifo[2]),32);
    bufp->fullIData(oldp+158,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__acc_fifo[3]),32);
    bufp->fullCData(oldp+159,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__write_ptr),2);
    bufp->fullBit(oldp+160,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__input_valid_i_d));
    bufp->fullQData(oldp+161,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__1__KET____DOT__acc_inst__DOT__unnamedblk1__DOT__sum),33);
    bufp->fullIData(oldp+163,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__sa_sum_out
                              [2U]),32);
    bufp->fullIData(oldp+164,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__acc_fifo
                              [vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__read_ptr]),32);
    bufp->fullBit(oldp+165,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__calc_done_reg));
    bufp->fullBit(oldp+166,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__input_valid_reg));
    bufp->fullBit(oldp+167,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__is_init_data_reg));
    bufp->fullIData(oldp+168,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__acc_fifo[0]),32);
    bufp->fullIData(oldp+169,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__acc_fifo[1]),32);
    bufp->fullIData(oldp+170,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__acc_fifo[2]),32);
    bufp->fullIData(oldp+171,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__acc_fifo[3]),32);
    bufp->fullCData(oldp+172,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__write_ptr),2);
    bufp->fullBit(oldp+173,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__input_valid_i_d));
    bufp->fullQData(oldp+174,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__2__KET____DOT__acc_inst__DOT__unnamedblk1__DOT__sum),33);
    bufp->fullIData(oldp+176,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__sa_sum_out
                              [3U]),32);
    bufp->fullIData(oldp+177,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__acc_fifo
                              [vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__read_ptr]),32);
    bufp->fullBit(oldp+178,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__input_valid_reg));
    bufp->fullBit(oldp+179,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__is_init_data_reg));
    bufp->fullIData(oldp+180,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__acc_fifo[0]),32);
    bufp->fullIData(oldp+181,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__acc_fifo[1]),32);
    bufp->fullIData(oldp+182,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__acc_fifo[2]),32);
    bufp->fullIData(oldp+183,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__acc_fifo[3]),32);
    bufp->fullCData(oldp+184,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__write_ptr),2);
    bufp->fullBit(oldp+185,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__input_valid_i_d));
    bufp->fullQData(oldp+186,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_accumulator_array__DOT__accumulator_gen__BRA__3__KET____DOT__acc_inst__DOT__unnamedblk1__DOT__sum),33);
    bufp->fullBit(oldp+188,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__input_valid_shift[0]));
    bufp->fullBit(oldp+189,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__input_valid_shift[1]));
    bufp->fullBit(oldp+190,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__input_valid_shift[2]));
    bufp->fullBit(oldp+191,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__input_valid_shift[3]));
    bufp->fullBit(oldp+192,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__calc_done_shift[0]));
    bufp->fullBit(oldp+193,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__calc_done_shift[1]));
    bufp->fullBit(oldp+194,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__calc_done_shift[2]));
    bufp->fullBit(oldp+195,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__calc_done_shift[3]));
    bufp->fullBit(oldp+196,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__is_init_data_shift[0]));
    bufp->fullBit(oldp+197,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__is_init_data_shift[1]));
    bufp->fullBit(oldp+198,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__is_init_data_shift[2]));
    bufp->fullBit(oldp+199,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__is_init_data_shift[3]));
    bufp->fullIData(oldp+200,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_control_delay__DOT__unnamedblk1__DOT__m),32);
    bufp->fullSData(oldp+201,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__1__KET____DOT__gen_delay_1__DOT__shift_reg),16);
    bufp->fullSData(oldp+202,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__2__KET____DOT__gen_delay_n__DOT__shift_reg[0]),16);
    bufp->fullSData(oldp+203,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__2__KET____DOT__gen_delay_n__DOT__shift_reg[1]),16);
    bufp->fullIData(oldp+204,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__2__KET____DOT__gen_delay_n__DOT__k),32);
    bufp->fullSData(oldp+205,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__3__KET____DOT__gen_delay_n__DOT__shift_reg[0]),16);
    bufp->fullSData(oldp+206,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__3__KET____DOT__gen_delay_n__DOT__shift_reg[1]),16);
    bufp->fullSData(oldp+207,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__3__KET____DOT__gen_delay_n__DOT__shift_reg[2]),16);
    bufp->fullIData(oldp+208,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__3__KET____DOT__gen_delay_n__DOT__k),32);
    bufp->fullSData(oldp+209,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
                              [0U][0U]),16);
    bufp->fullSData(oldp+210,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
                              [0U][1U]),16);
    bufp->fullSData(oldp+211,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
                              [0U][2U]),16);
    bufp->fullSData(oldp+212,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
                              [0U][3U]),16);
    bufp->fullSData(oldp+213,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
                              [1U][0U]),16);
    bufp->fullSData(oldp+214,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
                              [1U][1U]),16);
    bufp->fullSData(oldp+215,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
                              [1U][2U]),16);
    bufp->fullSData(oldp+216,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
                              [1U][3U]),16);
    bufp->fullSData(oldp+217,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
                              [2U][0U]),16);
    bufp->fullSData(oldp+218,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
                              [2U][1U]),16);
    bufp->fullSData(oldp+219,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
                              [2U][2U]),16);
    bufp->fullSData(oldp+220,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
                              [2U][3U]),16);
    bufp->fullSData(oldp+221,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
                              [3U][0U]),16);
    bufp->fullSData(oldp+222,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
                              [3U][1U]),16);
    bufp->fullSData(oldp+223,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
                              [3U][2U]),16);
    bufp->fullSData(oldp+224,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
                              [3U][3U]),16);
    bufp->fullCData(oldp+225,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
                              [0U][0U]),8);
    bufp->fullCData(oldp+226,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
                              [0U][1U]),8);
    bufp->fullCData(oldp+227,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
                              [0U][2U]),8);
    bufp->fullCData(oldp+228,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
                              [0U][3U]),8);
    bufp->fullCData(oldp+229,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
                              [1U][0U]),8);
    bufp->fullCData(oldp+230,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
                              [1U][1U]),8);
    bufp->fullCData(oldp+231,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
                              [1U][2U]),8);
    bufp->fullCData(oldp+232,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
                              [1U][3U]),8);
    bufp->fullCData(oldp+233,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
                              [2U][0U]),8);
    bufp->fullCData(oldp+234,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
                              [2U][1U]),8);
    bufp->fullCData(oldp+235,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
                              [2U][2U]),8);
    bufp->fullCData(oldp+236,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
                              [2U][3U]),8);
    bufp->fullCData(oldp+237,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
                              [3U][0U]),8);
    bufp->fullCData(oldp+238,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
                              [3U][1U]),8);
    bufp->fullCData(oldp+239,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
                              [3U][2U]),8);
    bufp->fullCData(oldp+240,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
                              [3U][3U]),8);
    bufp->fullIData(oldp+241,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
                              [0U][0U]),32);
    bufp->fullIData(oldp+242,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
                              [0U][1U]),32);
    bufp->fullIData(oldp+243,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
                              [0U][2U]),32);
    bufp->fullIData(oldp+244,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
                              [0U][3U]),32);
    bufp->fullIData(oldp+245,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
                              [1U][0U]),32);
    bufp->fullIData(oldp+246,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
                              [1U][1U]),32);
    bufp->fullIData(oldp+247,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
                              [1U][2U]),32);
    bufp->fullIData(oldp+248,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
                              [1U][3U]),32);
    bufp->fullIData(oldp+249,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
                              [2U][0U]),32);
    bufp->fullIData(oldp+250,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
                              [2U][1U]),32);
    bufp->fullIData(oldp+251,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
                              [2U][2U]),32);
    bufp->fullIData(oldp+252,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
                              [2U][3U]),32);
    bufp->fullIData(oldp+253,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
                              [3U][0U]),32);
    bufp->fullIData(oldp+254,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
                              [3U][1U]),32);
    bufp->fullIData(oldp+255,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
                              [3U][2U]),32);
    bufp->fullIData(oldp+256,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
                              [3U][3U]),32);
    bufp->fullSData(oldp+257,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__data_reg),16);
    bufp->fullCData(oldp+258,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__weight_reg),8);
    bufp->fullIData(oldp+259,((VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext)
                                ? 0x7fffffffU : (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext)
                                                  ? 0x80000000U
                                                  : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext)))),32);
    bufp->fullIData(oldp+260,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_reg),32);
    bufp->fullIData(oldp+261,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__mult_result),32);
    bufp->fullQData(oldp+262,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext),33);
    bufp->fullSData(oldp+264,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
                              [0U][0U]),16);
    bufp->fullSData(oldp+265,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__data_reg),16);
    bufp->fullCData(oldp+266,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__weight_reg),8);
    bufp->fullIData(oldp+267,((VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext)
                                ? 0x7fffffffU : (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext)
                                                  ? 0x80000000U
                                                  : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext)))),32);
    bufp->fullIData(oldp+268,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_reg),32);
    bufp->fullIData(oldp+269,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__mult_result),32);
    bufp->fullQData(oldp+270,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext),33);
    bufp->fullSData(oldp+272,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
                              [0U][1U]),16);
    bufp->fullSData(oldp+273,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__data_reg),16);
    bufp->fullCData(oldp+274,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__weight_reg),8);
    bufp->fullIData(oldp+275,((VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext)
                                ? 0x7fffffffU : (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext)
                                                  ? 0x80000000U
                                                  : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext)))),32);
    bufp->fullIData(oldp+276,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_reg),32);
    bufp->fullIData(oldp+277,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__mult_result),32);
    bufp->fullQData(oldp+278,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext),33);
    bufp->fullSData(oldp+280,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
                              [0U][2U]),16);
    bufp->fullSData(oldp+281,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__data_reg),16);
    bufp->fullCData(oldp+282,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__weight_reg),8);
    bufp->fullIData(oldp+283,((VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext)
                                ? 0x7fffffffU : (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext)
                                                  ? 0x80000000U
                                                  : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext)))),32);
    bufp->fullIData(oldp+284,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_reg),32);
    bufp->fullIData(oldp+285,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__mult_result),32);
    bufp->fullQData(oldp+286,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__0__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext),33);
    bufp->fullCData(oldp+288,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
                              [0U][0U]),8);
    bufp->fullIData(oldp+289,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
                              [0U][0U]),32);
    bufp->fullSData(oldp+290,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__data_reg),16);
    bufp->fullCData(oldp+291,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__weight_reg),8);
    bufp->fullIData(oldp+292,((VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext)
                                ? 0x7fffffffU : (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext)
                                                  ? 0x80000000U
                                                  : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext)))),32);
    bufp->fullIData(oldp+293,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_reg),32);
    bufp->fullIData(oldp+294,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__mult_result),32);
    bufp->fullQData(oldp+295,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext),33);
    bufp->fullCData(oldp+297,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
                              [0U][1U]),8);
    bufp->fullSData(oldp+298,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
                              [1U][0U]),16);
    bufp->fullIData(oldp+299,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
                              [0U][1U]),32);
    bufp->fullSData(oldp+300,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__data_reg),16);
    bufp->fullCData(oldp+301,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__weight_reg),8);
    bufp->fullIData(oldp+302,((VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext)
                                ? 0x7fffffffU : (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext)
                                                  ? 0x80000000U
                                                  : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext)))),32);
    bufp->fullIData(oldp+303,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_reg),32);
    bufp->fullIData(oldp+304,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__mult_result),32);
    bufp->fullQData(oldp+305,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext),33);
    bufp->fullCData(oldp+307,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
                              [0U][2U]),8);
    bufp->fullSData(oldp+308,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
                              [1U][1U]),16);
    bufp->fullIData(oldp+309,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
                              [0U][2U]),32);
    bufp->fullSData(oldp+310,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__data_reg),16);
    bufp->fullCData(oldp+311,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__weight_reg),8);
    bufp->fullIData(oldp+312,((VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext)
                                ? 0x7fffffffU : (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext)
                                                  ? 0x80000000U
                                                  : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext)))),32);
    bufp->fullIData(oldp+313,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_reg),32);
    bufp->fullIData(oldp+314,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__mult_result),32);
    bufp->fullQData(oldp+315,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext),33);
    bufp->fullCData(oldp+317,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
                              [0U][3U]),8);
    bufp->fullSData(oldp+318,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
                              [1U][2U]),16);
    bufp->fullIData(oldp+319,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
                              [0U][3U]),32);
    bufp->fullSData(oldp+320,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__data_reg),16);
    bufp->fullCData(oldp+321,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__weight_reg),8);
    bufp->fullIData(oldp+322,((VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext)
                                ? 0x7fffffffU : (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext)
                                                  ? 0x80000000U
                                                  : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext)))),32);
    bufp->fullIData(oldp+323,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_reg),32);
    bufp->fullIData(oldp+324,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__mult_result),32);
    bufp->fullQData(oldp+325,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__1__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext),33);
    bufp->fullCData(oldp+327,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
                              [1U][0U]),8);
    bufp->fullSData(oldp+328,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__2__KET____DOT__gen_delay_n__DOT__shift_reg
                              [1U]),16);
    bufp->fullIData(oldp+329,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
                              [1U][0U]),32);
    bufp->fullSData(oldp+330,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__data_reg),16);
    bufp->fullCData(oldp+331,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__weight_reg),8);
    bufp->fullIData(oldp+332,((VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext)
                                ? 0x7fffffffU : (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext)
                                                  ? 0x80000000U
                                                  : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext)))),32);
    bufp->fullIData(oldp+333,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_reg),32);
    bufp->fullIData(oldp+334,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__mult_result),32);
    bufp->fullQData(oldp+335,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext),33);
    bufp->fullCData(oldp+337,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
                              [1U][1U]),8);
    bufp->fullSData(oldp+338,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
                              [2U][0U]),16);
    bufp->fullIData(oldp+339,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
                              [1U][1U]),32);
    bufp->fullSData(oldp+340,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__data_reg),16);
    bufp->fullCData(oldp+341,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__weight_reg),8);
    bufp->fullIData(oldp+342,((VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext)
                                ? 0x7fffffffU : (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext)
                                                  ? 0x80000000U
                                                  : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext)))),32);
    bufp->fullIData(oldp+343,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_reg),32);
    bufp->fullIData(oldp+344,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__mult_result),32);
    bufp->fullQData(oldp+345,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext),33);
    bufp->fullCData(oldp+347,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
                              [1U][2U]),8);
    bufp->fullSData(oldp+348,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
                              [2U][1U]),16);
    bufp->fullIData(oldp+349,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
                              [1U][2U]),32);
    bufp->fullSData(oldp+350,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__data_reg),16);
    bufp->fullCData(oldp+351,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__weight_reg),8);
    bufp->fullIData(oldp+352,((VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext)
                                ? 0x7fffffffU : (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext)
                                                  ? 0x80000000U
                                                  : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext)))),32);
    bufp->fullIData(oldp+353,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_reg),32);
    bufp->fullIData(oldp+354,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__mult_result),32);
    bufp->fullQData(oldp+355,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext),33);
    bufp->fullCData(oldp+357,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
                              [1U][3U]),8);
    bufp->fullSData(oldp+358,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
                              [2U][2U]),16);
    bufp->fullIData(oldp+359,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
                              [1U][3U]),32);
    bufp->fullSData(oldp+360,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__data_reg),16);
    bufp->fullCData(oldp+361,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__weight_reg),8);
    bufp->fullIData(oldp+362,((VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext)
                                ? 0x7fffffffU : (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext)
                                                  ? 0x80000000U
                                                  : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext)))),32);
    bufp->fullIData(oldp+363,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_reg),32);
    bufp->fullIData(oldp+364,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__mult_result),32);
    bufp->fullQData(oldp+365,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__2__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext),33);
    bufp->fullCData(oldp+367,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
                              [2U][0U]),8);
    bufp->fullSData(oldp+368,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_data_setup__DOT__genblk1__DOT__gen_shift_chain__BRA__3__KET____DOT__gen_delay_n__DOT__shift_reg
                              [2U]),16);
    bufp->fullIData(oldp+369,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
                              [2U][0U]),32);
    bufp->fullSData(oldp+370,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__data_reg),16);
    bufp->fullCData(oldp+371,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__weight_reg),8);
    bufp->fullIData(oldp+372,((VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext)
                                ? 0x7fffffffU : (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext)
                                                  ? 0x80000000U
                                                  : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext)))),32);
    bufp->fullIData(oldp+373,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_reg),32);
    bufp->fullIData(oldp+374,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__mult_result),32);
    bufp->fullQData(oldp+375,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__0__KET____DOT__ws_cell__DOT__sum_ext),33);
    bufp->fullCData(oldp+377,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
                              [2U][1U]),8);
    bufp->fullSData(oldp+378,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
                              [3U][0U]),16);
    bufp->fullIData(oldp+379,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
                              [2U][1U]),32);
    bufp->fullSData(oldp+380,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__data_reg),16);
    bufp->fullCData(oldp+381,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__weight_reg),8);
    bufp->fullIData(oldp+382,((VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext)
                                ? 0x7fffffffU : (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext)
                                                  ? 0x80000000U
                                                  : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext)))),32);
    bufp->fullIData(oldp+383,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_reg),32);
    bufp->fullIData(oldp+384,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__mult_result),32);
    bufp->fullQData(oldp+385,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__1__KET____DOT__ws_cell__DOT__sum_ext),33);
    bufp->fullCData(oldp+387,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
                              [2U][2U]),8);
    bufp->fullSData(oldp+388,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
                              [3U][1U]),16);
    bufp->fullIData(oldp+389,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
                              [2U][2U]),32);
    bufp->fullSData(oldp+390,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__data_reg),16);
    bufp->fullCData(oldp+391,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__weight_reg),8);
    bufp->fullIData(oldp+392,((VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext)
                                ? 0x7fffffffU : (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext)
                                                  ? 0x80000000U
                                                  : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext)))),32);
    bufp->fullIData(oldp+393,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_reg),32);
    bufp->fullIData(oldp+394,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__mult_result),32);
    bufp->fullQData(oldp+395,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__2__KET____DOT__ws_cell__DOT__sum_ext),33);
    bufp->fullCData(oldp+397,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__weight_pipe
                              [2U][3U]),8);
    bufp->fullSData(oldp+398,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__data_pipe
                              [3U][2U]),16);
    bufp->fullIData(oldp+399,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__sum_pipe
                              [2U][3U]),32);
    bufp->fullSData(oldp+400,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__data_reg),16);
    bufp->fullCData(oldp+401,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__weight_reg),8);
    bufp->fullIData(oldp+402,((VL_LTS_IQQ(33, 0x7fffffffULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext)
                                ? 0x7fffffffU : (VL_GTS_IQQ(33, 0x180000000ULL, vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext)
                                                  ? 0x80000000U
                                                  : (IData)(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext)))),32);
    bufp->fullIData(oldp+403,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_reg),32);
    bufp->fullIData(oldp+404,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__mult_result),32);
    bufp->fullQData(oldp+405,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__u_systolic_array__DOT__gen_row__BRA__3__KET____DOT__gen_col__BRA__3__KET____DOT__ws_cell__DOT__sum_ext),33);
    bufp->fullIData(oldp+407,(vlSelfRef.tb_compute_core__DOT__unnamedblk1__DOT__c),32);
    bufp->fullIData(oldp+408,(vlSymsp->TOP__tb_compute_core__DOT__tb_if.acc_data_out[0]),32);
    bufp->fullIData(oldp+409,(vlSymsp->TOP__tb_compute_core__DOT__tb_if.acc_data_out[1]),32);
    bufp->fullIData(oldp+410,(vlSymsp->TOP__tb_compute_core__DOT__tb_if.acc_data_out[2]),32);
    bufp->fullIData(oldp+411,(vlSymsp->TOP__tb_compute_core__DOT__tb_if.acc_data_out[3]),32);
    bufp->fullSData(oldp+412,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__data_setup_out[0]),16);
    bufp->fullSData(oldp+413,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__data_setup_out[1]),16);
    bufp->fullSData(oldp+414,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__data_setup_out[2]),16);
    bufp->fullSData(oldp+415,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT__data_setup_out[3]),16);
    bufp->fullSData(oldp+416,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellout__u_data_setup__data_out[0]),16);
    bufp->fullSData(oldp+417,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellout__u_data_setup__data_out[1]),16);
    bufp->fullSData(oldp+418,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellout__u_data_setup__data_out[2]),16);
    bufp->fullSData(oldp+419,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellout__u_data_setup__data_out[3]),16);
    bufp->fullIData(oldp+420,(vlSelfRef.tb_compute_core__DOT____Vcellinp__u_dut__bias_in[0]),32);
    bufp->fullIData(oldp+421,(vlSelfRef.tb_compute_core__DOT____Vcellinp__u_dut__bias_in[1]),32);
    bufp->fullIData(oldp+422,(vlSelfRef.tb_compute_core__DOT____Vcellinp__u_dut__bias_in[2]),32);
    bufp->fullIData(oldp+423,(vlSelfRef.tb_compute_core__DOT____Vcellinp__u_dut__bias_in[3]),32);
    bufp->fullIData(oldp+424,(vlSymsp->TOP__tb_compute_core__DOT__tb_if.bias_in
                              [0U]),32);
    bufp->fullIData(oldp+425,(vlSymsp->TOP__tb_compute_core__DOT__tb_if.bias_in
                              [1U]),32);
    bufp->fullIData(oldp+426,(vlSymsp->TOP__tb_compute_core__DOT__tb_if.bias_in
                              [2U]),32);
    bufp->fullIData(oldp+427,(vlSymsp->TOP__tb_compute_core__DOT__tb_if.bias_in
                              [3U]),32);
    bufp->fullIData(oldp+428,(vlSymsp->TOP__tb_compute_core__DOT__tb_if.bias_in[0]),32);
    bufp->fullIData(oldp+429,(vlSymsp->TOP__tb_compute_core__DOT__tb_if.bias_in[1]),32);
    bufp->fullIData(oldp+430,(vlSymsp->TOP__tb_compute_core__DOT__tb_if.bias_in[2]),32);
    bufp->fullIData(oldp+431,(vlSymsp->TOP__tb_compute_core__DOT__tb_if.bias_in[3]),32);
    bufp->fullCData(oldp+432,(vlSelfRef.tb_compute_core__DOT____Vcellinp__u_dut__weight_in[0]),8);
    bufp->fullCData(oldp+433,(vlSelfRef.tb_compute_core__DOT____Vcellinp__u_dut__weight_in[1]),8);
    bufp->fullCData(oldp+434,(vlSelfRef.tb_compute_core__DOT____Vcellinp__u_dut__weight_in[2]),8);
    bufp->fullCData(oldp+435,(vlSelfRef.tb_compute_core__DOT____Vcellinp__u_dut__weight_in[3]),8);
    bufp->fullCData(oldp+436,(vlSymsp->TOP__tb_compute_core__DOT__tb_if.weight_in
                              [0U]),8);
    bufp->fullCData(oldp+437,(vlSymsp->TOP__tb_compute_core__DOT__tb_if.weight_in
                              [1U]),8);
    bufp->fullCData(oldp+438,(vlSymsp->TOP__tb_compute_core__DOT__tb_if.weight_in
                              [2U]),8);
    bufp->fullCData(oldp+439,(vlSymsp->TOP__tb_compute_core__DOT__tb_if.weight_in
                              [3U]),8);
    bufp->fullCData(oldp+440,(vlSymsp->TOP__tb_compute_core__DOT__tb_if.weight_in[0]),8);
    bufp->fullCData(oldp+441,(vlSymsp->TOP__tb_compute_core__DOT__tb_if.weight_in[1]),8);
    bufp->fullCData(oldp+442,(vlSymsp->TOP__tb_compute_core__DOT__tb_if.weight_in[2]),8);
    bufp->fullCData(oldp+443,(vlSymsp->TOP__tb_compute_core__DOT__tb_if.weight_in[3]),8);
    bufp->fullSData(oldp+444,(vlSelfRef.tb_compute_core__DOT____Vcellinp__u_dut__ia_vec_in[0]),16);
    bufp->fullSData(oldp+445,(vlSelfRef.tb_compute_core__DOT____Vcellinp__u_dut__ia_vec_in[1]),16);
    bufp->fullSData(oldp+446,(vlSelfRef.tb_compute_core__DOT____Vcellinp__u_dut__ia_vec_in[2]),16);
    bufp->fullSData(oldp+447,(vlSelfRef.tb_compute_core__DOT____Vcellinp__u_dut__ia_vec_in[3]),16);
    bufp->fullSData(oldp+448,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellinp__u_data_setup__data_in[0]),16);
    bufp->fullSData(oldp+449,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellinp__u_data_setup__data_in[1]),16);
    bufp->fullSData(oldp+450,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellinp__u_data_setup__data_in[2]),16);
    bufp->fullSData(oldp+451,(vlSelfRef.tb_compute_core__DOT__u_dut__DOT____Vcellinp__u_data_setup__data_in[3]),16);
    bufp->fullSData(oldp+452,(vlSymsp->TOP__tb_compute_core__DOT__tb_if.ia_vec_in
                              [0U]),16);
    bufp->fullSData(oldp+453,(vlSymsp->TOP__tb_compute_core__DOT__tb_if.ia_vec_in[0]),16);
    bufp->fullSData(oldp+454,(vlSymsp->TOP__tb_compute_core__DOT__tb_if.ia_vec_in[1]),16);
    bufp->fullSData(oldp+455,(vlSymsp->TOP__tb_compute_core__DOT__tb_if.ia_vec_in[2]),16);
    bufp->fullSData(oldp+456,(vlSymsp->TOP__tb_compute_core__DOT__tb_if.ia_vec_in[3]),16);
    bufp->fullBit(oldp+457,(vlSelfRef.tb_compute_core__DOT__clk));
    bufp->fullIData(oldp+458,(vlSelfRef.tb_compute_core__DOT__out_rows),32);
    bufp->fullIData(oldp+459,(vlSelfRef.tb_compute_core__DOT__NUM_K),32);
    bufp->fullIData(oldp+460,(vlSelfRef.tb_compute_core__DOT__NUM_SEG),32);
    bufp->fullBit(oldp+461,(vlSymsp->TOP__tb_compute_core__DOT__tb_if.store_weight_req));
    bufp->fullBit(oldp+462,(vlSymsp->TOP__tb_compute_core__DOT__tb_if.ia_row_valid));
    bufp->fullBit(oldp+463,(vlSymsp->TOP__tb_compute_core__DOT__tb_if.ia_calc_done));
    bufp->fullBit(oldp+464,(vlSymsp->TOP__tb_compute_core__DOT__tb_if.ia_is_init_data));
}
