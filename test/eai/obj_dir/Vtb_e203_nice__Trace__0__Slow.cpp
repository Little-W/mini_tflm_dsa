// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Tracing implementation internals
#include "verilated_vcd_c.h"
#include "Vtb_e203_nice__Syms.h"


VL_ATTR_COLD void Vtb_e203_nice___024root__trace_init_sub__TOP__tb_e203_nice__DOT__nice_if_inst__0(Vtb_e203_nice___024root* vlSelf, VerilatedVcd* tracep);

VL_ATTR_COLD void Vtb_e203_nice___024root__trace_init_sub__TOP__0(Vtb_e203_nice___024root* vlSelf, VerilatedVcd* tracep) {
    (void)vlSelf;  // Prevent unused variable warning
    Vtb_e203_nice__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_e203_nice___024root__trace_init_sub__TOP__0\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Init
    const int c = vlSymsp->__Vm_baseCode;
    // Body
    tracep->pushPrefix("tb_e203_nice", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->declBit(c+134,0,"clk",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+135,0,"rst_n",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+147,0,"CUSTOM_1",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::LOGIC, false,-1, 6,0);
    tracep->declBus(c+148,0,"MAT_MULT_FUNCT7",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::LOGIC, false,-1, 6,0);
    tracep->declBus(c+149,0,"NICE_FUNCT3",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::LOGIC, false,-1, 2,0);
    tracep->declBus(c+150,0,"CUSTOM_3",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::LOGIC, false,-1, 6,0);
    tracep->declBus(c+151,0,"CSRWR_FUNCT3",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::LOGIC, false,-1, 2,0);
    tracep->declBus(c+152,0,"CSRR_FUNCT3",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::LOGIC, false,-1, 2,0);
    tracep->pushPrefix("nice_if_inst", VerilatedTracePrefixType::SCOPE_INTERFACE);
    Vtb_e203_nice___024root__trace_init_sub__TOP__tb_e203_nice__DOT__nice_if_inst__0(vlSelf, tracep);
    tracep->popPrefix();
    tracep->declBus(c+136,0,"send_csr_read__Vstatic__read_value",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+137,0,"test_response_backpressure__Vstatic__read_value",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+138,0,"test_request_backpressure__Vstatic__read_value",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->pushPrefix("u_nice_core", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->declBit(c+134,0,"nice_clk",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+135,0,"nice_rst_n",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+1,0,"nice_active",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+2,0,"nice_mem_holdup",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+139,0,"nice_req_valid",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+110,0,"nice_req_ready",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+116,0,"nice_req_inst",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+117,0,"nice_req_rs1",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+118,0,"nice_req_rs2",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBit(c+3,0,"nice_rsp_valid",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+140,0,"nice_rsp_ready",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+4,0,"nice_rsp_rdat",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBit(c+153,0,"nice_rsp_err",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+5,0,"nice_icb_cmd_valid",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+154,0,"nice_icb_cmd_ready",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+6,0,"nice_icb_cmd_addr",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBit(c+7,0,"nice_icb_cmd_read",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+8,0,"nice_icb_cmd_wdata",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+9,0,"nice_icb_cmd_wmask",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 3,0);
    tracep->declBus(c+155,0,"nice_icb_cmd_size",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 1,0);
    tracep->declBit(c+10,0,"nice_icb_rsp_valid",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+154,0,"nice_icb_rsp_ready",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+156,0,"nice_icb_rsp_rdata",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBit(c+153,0,"nice_icb_rsp_err",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+1,0,"calc_start",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+11,0,"cfg_16bits_ia",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+12,0,"use_per_channel",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+13,0,"dst_base",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBit(c+14,0,"sa_ready",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+15,0,"csr_wdata",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBit(c+16,0,"csr_req",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+17,0,"is_csr_read",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+18,0,"csr_addr",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 11,0);
    tracep->declBit(c+19,0,"csr_ready",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+20,0,"csr_rdata",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+21,0,"lhs_base",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+22,0,"rhs_base",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+23,0,"dst_base_csr",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+24,0,"bias_base",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+25,0,"lhs_zp",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+26,0,"rhs_zp",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+27,0,"dst_zp",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+28,0,"q_mult_pt",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+29,0,"q_shift_pt",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+30,0,"k",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+31,0,"n",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+32,0,"m",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+33,0,"lhs_row_stride_b",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+34,0,"dst_row_stride_b",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+35,0,"rhs_row_stride_b",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+36,0,"act_min",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+37,0,"act_max",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBit(c+38,0,"mma_wb_valid",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+39,0,"mma_wb_ready",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+156,0,"mma_wb_data",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBit(c+16,0,"csr_wb_valid",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+40,0,"csr_wb_ready",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+41,0,"csr_wb_data",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+157,0,"mma_err_code",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 1,0);
    tracep->declBit(c+2,0,"retire_mem_holdup",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+153,0,"sa_icb_cmd_valid",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+42,0,"sa_icb_cmd_ready",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+156,0,"sa_icb_cmd_addr",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBit(c+153,0,"sa_icb_cmd_read",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+158,0,"sa_icb_cmd_len",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 2,0);
    tracep->declBus(c+156,0,"sa_icb_cmd_wdata",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+159,0,"sa_icb_cmd_wmask",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 3,0);
    tracep->declBit(c+153,0,"sa_icb_w_valid",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+43,0,"sa_icb_w_ready",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+44,0,"sa_icb_rsp_valid",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+154,0,"sa_icb_rsp_ready",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+45,0,"sa_icb_rsp_rdata",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBit(c+153,0,"sa_icb_rsp_err",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->pushPrefix("u_csr_unit", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->declBus(c+160,0,"REG_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBit(c+134,0,"clk",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+135,0,"rst_n",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+16,0,"csr_req",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+17,0,"is_csr_read",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+18,0,"csr_addr",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 11,0);
    tracep->declBus(c+15,0,"csr_wdata",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBit(c+19,0,"csr_ready",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+20,0,"csr_rdata",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBit(c+16,0,"csr_wb_valid",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+40,0,"csr_wb_ready",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+41,0,"csr_wb_data",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+21,0,"lhs_base",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+22,0,"rhs_base",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+23,0,"dst_base",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+24,0,"bias_base",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+25,0,"lhs_zp",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+26,0,"rhs_zp",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+27,0,"dst_zp",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+28,0,"q_mult_pt",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+29,0,"q_shift_pt",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+32,0,"m",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+30,0,"k",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+31,0,"n",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+33,0,"lhs_row_stride_b",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+34,0,"dst_row_stride_b",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+35,0,"rhs_row_stride_b",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+36,0,"act_min",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+37,0,"act_max",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+161,0,"MULT_LHS_PTR",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::LOGIC, false,-1, 11,0);
    tracep->declBus(c+162,0,"MULT_RHS_PTR",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::LOGIC, false,-1, 11,0);
    tracep->declBus(c+163,0,"MULT_DST_PTR",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::LOGIC, false,-1, 11,0);
    tracep->declBus(c+164,0,"MULT_BIAS_PTR",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::LOGIC, false,-1, 11,0);
    tracep->declBus(c+165,0,"MULT_LHS_ROWS",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::LOGIC, false,-1, 11,0);
    tracep->declBus(c+166,0,"MULT_RHS_COLS",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::LOGIC, false,-1, 11,0);
    tracep->declBus(c+167,0,"MULT_RHS_ROWS",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::LOGIC, false,-1, 11,0);
    tracep->declBus(c+168,0,"MULT_ROW_ADDR_OFFSET",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::LOGIC, false,-1, 11,0);
    tracep->declBus(c+169,0,"MULT_LHS_COLS_OFFSET",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::LOGIC, false,-1, 11,0);
    tracep->declBus(c+170,0,"MULT_RHS_ROW_STRIDE",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::LOGIC, false,-1, 11,0);
    tracep->declBus(c+171,0,"MULT_LHS_OFFSET",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::LOGIC, false,-1, 11,0);
    tracep->declBus(c+172,0,"MULT_RHS_OFFSET",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::LOGIC, false,-1, 11,0);
    tracep->declBus(c+173,0,"MULT_DST_OFFSET",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::LOGIC, false,-1, 11,0);
    tracep->declBus(c+174,0,"MULT_DST_MULT",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::LOGIC, false,-1, 11,0);
    tracep->declBus(c+175,0,"MULT_DST_SHIFT",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::LOGIC, false,-1, 11,0);
    tracep->declBus(c+176,0,"MULT_ACT_MIN",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::LOGIC, false,-1, 11,0);
    tracep->declBus(c+177,0,"MULT_ACT_MAX",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::LOGIC, false,-1, 11,0);
    tracep->declBus(c+21,0,"csr_lhs_base",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+22,0,"csr_rhs_base",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+23,0,"csr_dst_base",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+24,0,"csr_bias_base",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+30,0,"csr_k",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+31,0,"csr_n",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+32,0,"csr_m",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+34,0,"csr_dst_row_stride_b",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+33,0,"csr_lhs_row_stride_b",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+35,0,"csr_rhs_row_stride_b",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+25,0,"csr_lhs_zp",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+26,0,"csr_rhs_zp",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+27,0,"csr_dst_zp",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+28,0,"csr_q_mult_pt",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+29,0,"csr_q_shift_pt",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+36,0,"csr_act_min",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+37,0,"csr_act_max",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->popPrefix();
    tracep->pushPrefix("u_decode_dispatch", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->declBus(c+178,0,"REG_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBit(c+134,0,"clk",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+135,0,"rst_n",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+139,0,"decode_inst_valid",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+110,0,"decode_inst_ready",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+116,0,"instruction",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+117,0,"rs1_val",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+118,0,"rs2_val",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBit(c+14,0,"sa_ready",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+19,0,"csr_ready",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+153,0,"id_stall",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+1,0,"calc_start",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+11,0,"cfg_16bits_ia",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+12,0,"use_per_channel",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+13,0,"dst_base",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+15,0,"csr_wdata",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBit(c+16,0,"csr_req",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+17,0,"is_csr_read",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+18,0,"csr_addr",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 11,0);
    tracep->declBus(c+147,0,"OPCODE_CUSTOM_1",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::LOGIC, false,-1, 6,0);
    tracep->declBus(c+150,0,"OPCODE_CUSTOM_3",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::LOGIC, false,-1, 6,0);
    tracep->declBus(c+148,0,"FUNCT7_MAT_MULT_T",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::LOGIC, false,-1, 6,0);
    tracep->declBus(c+149,0,"FUNCT3_RD_RS1_RS2",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::LOGIC, false,-1, 2,0);
    tracep->declBus(c+151,0,"FUNCT3_CSR_WR",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::LOGIC, false,-1, 2,0);
    tracep->declBus(c+152,0,"FUNCT3_CSR_RD",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::LOGIC, false,-1, 2,0);
    tracep->declBus(c+119,0,"opcode",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 6,0);
    tracep->declBus(c+120,0,"funct3",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 2,0);
    tracep->declBus(c+121,0,"funct7",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 6,0);
    tracep->declBus(c+122,0,"imm12",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 11,0);
    tracep->declBus(c+123,0,"cfg_out_w",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 2,0);
    tracep->declBus(c+124,0,"cfg_bias_w",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 1,0);
    tracep->declBus(c+125,0,"cfg_b_w",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 1,0);
    tracep->declBus(c+126,0,"cfg_a_w",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 1,0);
    tracep->declBit(c+127,0,"cfg_per_ch",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+128,0,"is_a_16bits",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+129,0,"is_mat_mult_t",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+130,0,"is_csr_wr",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+131,0,"is_csr_rd",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+132,0,"is_valid_inst",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+133,0,"is_csr_inst",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+110,0,"target_ready",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+141,0,"inst_handshake",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->popPrefix();
    tracep->pushPrefix("u_icb_bridge", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->declBus(c+160,0,"WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+160,0,"ADDR_W",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+179,0,"OUTS_DEPTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+180,0,"ICB_LEN_W",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+180,0,"DW",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBit(c+134,0,"clk",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+135,0,"rst_n",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+153,0,"sa_icb_cmd_valid",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+42,0,"sa_icb_cmd_ready",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+156,0,"sa_icb_cmd_addr",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBit(c+153,0,"sa_icb_cmd_read",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+159,0,"sa_icb_cmd_len",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 3,0);
    tracep->declBus(c+156,0,"sa_icb_cmd_wdata",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+159,0,"sa_icb_cmd_wmask",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 3,0);
    tracep->declBit(c+153,0,"sa_icb_w_valid",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+43,0,"sa_icb_w_ready",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+44,0,"sa_icb_rsp_valid",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+154,0,"sa_icb_rsp_ready",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+45,0,"sa_icb_rsp_rdata",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBit(c+153,0,"sa_icb_rsp_err",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+5,0,"m_icb_cmd_valid",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+154,0,"m_icb_cmd_ready",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+6,0,"m_icb_cmd_addr",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBit(c+7,0,"m_icb_cmd_read",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+8,0,"m_icb_cmd_wdata",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+9,0,"m_icb_cmd_wmask",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 3,0);
    tracep->declBit(c+10,0,"m_icb_rsp_valid",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+154,0,"m_icb_rsp_ready",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+156,0,"m_icb_rsp_rdata",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBit(c+153,0,"m_icb_rsp_err",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+179,0,"FIFO_DEPTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+180,0,"PTR_W",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBit(c+153,0,"cmd_fifo_wen",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+46,0,"cmd_fifo_ren",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+47,0,"cmd_fifo_full",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+48,0,"cmd_fifo_empty",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declQuad(c+181,0,"cmd_fifo_wdata",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 36,0);
    tracep->declQuad(c+49,0,"cmd_fifo_rdata",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 36,0);
    tracep->declBus(c+51,0,"cmd_fifo_wptr",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 4,0);
    tracep->declBus(c+52,0,"cmd_fifo_rptr",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 4,0);
    tracep->pushPrefix("cmd_fifo_mem", VerilatedTracePrefixType::ARRAY_UNPACKED);
    for (int i = 0; i < 16; ++i) {
        tracep->declQuad(c+183+i*2,0,"",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, true,(i+0), 36,0);
    }
    tracep->popPrefix();
    tracep->declBus(c+53,0,"burst_cycle_1start",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 4,0);
    tracep->declBus(c+54,0,"cur_offset",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 1,0);
    tracep->declBus(c+55,0,"cur_base_addr",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBit(c+56,0,"cur_cross_boundary",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+57,0,"cur_burst_cnt",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 4,0);
    tracep->declBus(c+58,0,"burst_cnt_nxt",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 4,0);
    tracep->declBit(c+59,0,"fifo_is_read",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+60,0,"fifo_addr",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+61,0,"fifo_len",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 3,0);
    tracep->declBit(c+62,0,"cur_is_read",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+63,0,"cur_addr",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+64,0,"cur_len_0start",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 3,0);
    tracep->declBus(c+65,0,"rsp_burst_cnt",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 4,0);
    tracep->declBus(c+66,0,"rsp_burst_cnt_nxt",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 4,0);
    tracep->declBus(c+67,0,"wdata_buf",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+68,0,"wmask_buf",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 3,0);
    tracep->declBit(c+69,0,"wdata_buf_valid",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+8,0,"wdata_aligned",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+9,0,"wmask_aligned",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 3,0);
    tracep->declBus(c+70,0,"rdata_buf",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBit(c+71,0,"rdata_buf_valid",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+72,0,"rdata_aligned",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+73,0,"cmd_state",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 1,0);
    tracep->declBus(c+74,0,"cmd_state_nxt",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 1,0);
    tracep->declBus(c+75,0,"rsp_state",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 1,0);
    tracep->declBus(c+76,0,"rsp_state_nxt",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 1,0);
    tracep->declBit(c+77,0,"cmd_fire",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+10,0,"rsp_fire",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+78,0,"is_last_burst",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+79,0,"rd_last_burst",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+80,0,"last_beat_sent",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+7,0,"cur_is_read_comb",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+81,0,"cur_addr_comb",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+82,0,"cur_len_0start_comb",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 3,0);
    tracep->declBit(c+83,0,"rsp_cross_boundary",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+84,0,"rsp_burst_cycle_1start",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 4,0);
    tracep->declBit(c+153,0,"cmd_fire_write",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+85,0,"cmd_fire_read",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+86,0,"cmd_fire_write_last",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+87,0,"cur_offsetX8",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 4,0);
    tracep->declBit(c+44,0,"sa_rsp_valid_comb",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+215,0,"sa_rsp_ready_comb",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->popPrefix();
    tracep->pushPrefix("u_inst_tracker", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->declBit(c+134,0,"clk",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+135,0,"rst_n",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+1,0,"calc_start",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+38,0,"mma_wb_valid",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+39,0,"mma_wb_ready",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+2,0,"nice_mem_holdup",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+216,0,"IDLE",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::LOGIC, false,-1, 0,0);
    tracep->declBus(c+217,0,"PENDING",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::LOGIC, false,-1, 0,0);
    tracep->declBit(c+88,0,"state",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+89,0,"wb_handshake",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->popPrefix();
    tracep->pushPrefix("u_mma_top", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->declBus(c+218,0,"WEIGHT_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBus(c+219,0,"DATA_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBus(c+219,0,"SIZE",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBus(c+178,0,"BUS_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBus(c+178,0,"REG_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBus(c+178,0,"ADDR_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBus(c+220,0,"LEN_WIDTH",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::INT, false,-1, 31,0);
    tracep->declBit(c+134,0,"clk",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+135,0,"rst_n",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+1,0,"calc_start",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+11,0,"cfg_16bits_ia",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+14,0,"sa_ready",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+38,0,"wb_valid",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+39,0,"wb_ready",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+157,0,"err_code",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 1,0);
    tracep->declBus(c+21,0,"lhs_base",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+22,0,"rhs_base",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+13,0,"dst_base",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+24,0,"bias_base",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+25,0,"lhs_zp",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+26,0,"rhs_zp",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+27,0,"dst_zp",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+28,0,"q_mult_pt",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+29,0,"q_shift_pt",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBit(c+12,0,"use_per_channel",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+30,0,"k",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+31,0,"n",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+32,0,"m",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+33,0,"lhs_row_stride_b",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+34,0,"dst_row_stride_b",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+35,0,"rhs_row_stride_b",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+36,0,"act_min",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+37,0,"act_max",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBit(c+153,0,"sa_icb_cmd_valid",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+42,0,"sa_icb_cmd_ready",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+156,0,"sa_icb_cmd_addr",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBit(c+153,0,"sa_icb_cmd_read",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+158,0,"sa_icb_cmd_len",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 2,0);
    tracep->declBus(c+156,0,"sa_icb_cmd_wdata",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+159,0,"sa_icb_cmd_wmask",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 3,0);
    tracep->declBit(c+153,0,"sa_icb_w_valid",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+43,0,"sa_icb_w_ready",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+44,0,"sa_icb_rsp_valid",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+154,0,"sa_icb_rsp_ready",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+45,0,"sa_icb_rsp_rdata",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBit(c+153,0,"sa_icb_rsp_err",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+157,0,"IDLE",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::LOGIC, false,-1, 1,0);
    tracep->declBus(c+221,0,"COMPUTING",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::LOGIC, false,-1, 1,0);
    tracep->declBus(c+155,0,"DONE",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::LOGIC, false,-1, 1,0);
    tracep->declBus(c+90,0,"state",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 1,0);
    tracep->declBus(c+91,0,"cycle_cnt",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->declBus(c+222,0,"COMPUTE_CYCLES",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::LOGIC, false,-1, 7,0);
    tracep->popPrefix();
    tracep->pushPrefix("u_wbu", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->declBus(c+160,0,"DW",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBit(c+134,0,"clk",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+135,0,"rst_n",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+16,0,"csr_wb_valid",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+40,0,"csr_wb_ready",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+41,0,"csr_wb_data",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBit(c+38,0,"mma_wb_valid",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+39,0,"mma_wb_ready",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+156,0,"mma_wb_data",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBit(c+3,0,"nice_rsp_valid",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+140,0,"nice_rsp_ready",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+4,0,"nice_rsp_rdat",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBit(c+153,0,"nice_rsp_err",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+92,0,"csr_buf_rd_valid",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+142,0,"csr_buf_rd_ready",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+93,0,"csr_buf_rd_data",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBit(c+94,0,"mma_buf_rd_valid",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+143,0,"mma_buf_rd_ready",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+95,0,"mma_buf_rd_data",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBit(c+94,0,"sel_mma",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+96,0,"sel_csr",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->pushPrefix("u_csr_wb_pingpong_buf", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->declBus(c+160,0,"DW",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBit(c+134,0,"clk",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+135,0,"rst_n",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+16,0,"wr_valid",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+40,0,"wr_ready",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+41,0,"wr_wb_data",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBit(c+92,0,"rd_valid",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+142,0,"rd_ready",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+93,0,"rd_wb_data",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+97,0,"wb_data_ping",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+98,0,"wb_data_pong",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBit(c+99,0,"ping_full",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+100,0,"pong_full",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+101,0,"wr_sel",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+102,0,"rd_sel",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+103,0,"wr_hsked",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+144,0,"rd_hsked",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->popPrefix();
    tracep->pushPrefix("u_mma_wb_pingpong_buf", VerilatedTracePrefixType::SCOPE_MODULE);
    tracep->declBus(c+160,0,"DW",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::PARAMETER, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBit(c+134,0,"clk",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+135,0,"rst_n",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+38,0,"wr_valid",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+39,0,"wr_ready",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+156,0,"wr_wb_data",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBit(c+94,0,"rd_valid",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+143,0,"rd_ready",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+95,0,"rd_wb_data",-1, VerilatedTraceSigDirection::OUTPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+104,0,"wb_data_ping",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+105,0,"wb_data_pong",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBit(c+106,0,"ping_full",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+107,0,"pong_full",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+108,0,"wr_sel",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+109,0,"rd_sel",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+89,0,"wr_hsked",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+145,0,"rd_hsked",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->popPrefix();
    tracep->popPrefix();
    tracep->popPrefix();
    tracep->popPrefix();
}

VL_ATTR_COLD void Vtb_e203_nice___024root__trace_init_sub__TOP__tb_e203_nice__DOT__nice_if_inst__0(Vtb_e203_nice___024root* vlSelf, VerilatedVcd* tracep) {
    (void)vlSelf;  // Prevent unused variable warning
    Vtb_e203_nice__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_e203_nice___024root__trace_init_sub__TOP__tb_e203_nice__DOT__nice_if_inst__0\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Init
    const int c = vlSymsp->__Vm_baseCode;
    // Body
    tracep->declBit(c+134,0,"clk",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+135,0,"rst_n",-1, VerilatedTraceSigDirection::INPUT, VerilatedTraceSigKind::WIRE, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+139,0,"req_valid",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+110,0,"req_ready",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+116,0,"req_inst",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+117,0,"req_rs1",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+118,0,"req_rs2",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBit(c+3,0,"rsp_valid",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+140,0,"rsp_ready",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+4,0,"rsp_rdat",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBit(c+153,0,"rsp_err",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+2,0,"mem_holdup",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+111,0,"icb_cmd_valid",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+154,0,"icb_cmd_ready",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+112,0,"icb_cmd_addr",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBit(c+113,0,"icb_cmd_read",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+114,0,"icb_cmd_wdata",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBus(c+115,0,"icb_cmd_wmask",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 3,0);
    tracep->declBit(c+10,0,"icb_rsp_valid",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBit(c+146,0,"icb_rsp_ready",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
    tracep->declBus(c+156,0,"icb_rsp_rdata",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1, 31,0);
    tracep->declBit(c+153,0,"icb_rsp_err",-1, VerilatedTraceSigDirection::NONE, VerilatedTraceSigKind::VAR, VerilatedTraceSigType::LOGIC, false,-1);
}

VL_ATTR_COLD void Vtb_e203_nice___024root__trace_init_top(Vtb_e203_nice___024root* vlSelf, VerilatedVcd* tracep) {
    (void)vlSelf;  // Prevent unused variable warning
    Vtb_e203_nice__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_e203_nice___024root__trace_init_top\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    Vtb_e203_nice___024root__trace_init_sub__TOP__0(vlSelf, tracep);
}

VL_ATTR_COLD void Vtb_e203_nice___024root__trace_const_0(void* voidSelf, VerilatedVcd::Buffer* bufp);
VL_ATTR_COLD void Vtb_e203_nice___024root__trace_full_0(void* voidSelf, VerilatedVcd::Buffer* bufp);
void Vtb_e203_nice___024root__trace_chg_0(void* voidSelf, VerilatedVcd::Buffer* bufp);
void Vtb_e203_nice___024root__trace_cleanup(void* voidSelf, VerilatedVcd* /*unused*/);

VL_ATTR_COLD void Vtb_e203_nice___024root__trace_register(Vtb_e203_nice___024root* vlSelf, VerilatedVcd* tracep) {
    (void)vlSelf;  // Prevent unused variable warning
    Vtb_e203_nice__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_e203_nice___024root__trace_register\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Body
    tracep->addConstCb(&Vtb_e203_nice___024root__trace_const_0, 0U, vlSelf);
    tracep->addFullCb(&Vtb_e203_nice___024root__trace_full_0, 0U, vlSelf);
    tracep->addChgCb(&Vtb_e203_nice___024root__trace_chg_0, 0U, vlSelf);
    tracep->addCleanupCb(&Vtb_e203_nice___024root__trace_cleanup, vlSelf);
}

VL_ATTR_COLD void Vtb_e203_nice___024root__trace_const_0_sub_0(Vtb_e203_nice___024root* vlSelf, VerilatedVcd::Buffer* bufp);

VL_ATTR_COLD void Vtb_e203_nice___024root__trace_const_0(void* voidSelf, VerilatedVcd::Buffer* bufp) {
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_e203_nice___024root__trace_const_0\n"); );
    // Init
    Vtb_e203_nice___024root* const __restrict vlSelf VL_ATTR_UNUSED = static_cast<Vtb_e203_nice___024root*>(voidSelf);
    Vtb_e203_nice__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    // Body
    Vtb_e203_nice___024root__trace_const_0_sub_0((&vlSymsp->TOP), bufp);
}

VL_ATTR_COLD void Vtb_e203_nice___024root__trace_const_0_sub_0(Vtb_e203_nice___024root* vlSelf, VerilatedVcd::Buffer* bufp) {
    (void)vlSelf;  // Prevent unused variable warning
    Vtb_e203_nice__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_e203_nice___024root__trace_const_0_sub_0\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Init
    uint32_t* const oldp VL_ATTR_UNUSED = bufp->oldp(vlSymsp->__Vm_baseCode);
    // Body
    bufp->fullCData(oldp+147,(0x2bU),7);
    bufp->fullCData(oldp+148,(1U),7);
    bufp->fullCData(oldp+149,(7U),3);
    bufp->fullCData(oldp+150,(0x7bU),7);
    bufp->fullCData(oldp+151,(2U),3);
    bufp->fullCData(oldp+152,(4U),3);
    bufp->fullBit(oldp+153,(0U));
    bufp->fullBit(oldp+154,(1U));
    bufp->fullCData(oldp+155,(2U),2);
    bufp->fullIData(oldp+156,(0U),32);
    bufp->fullCData(oldp+157,(0U),2);
    bufp->fullCData(oldp+158,(0U),3);
    bufp->fullCData(oldp+159,(0U),4);
    bufp->fullIData(oldp+160,(0x20U),32);
    bufp->fullSData(oldp+161,(0x7c0U),12);
    bufp->fullSData(oldp+162,(0x7c1U),12);
    bufp->fullSData(oldp+163,(0x7c2U),12);
    bufp->fullSData(oldp+164,(0x7c3U),12);
    bufp->fullSData(oldp+165,(0x7c4U),12);
    bufp->fullSData(oldp+166,(0x7c5U),12);
    bufp->fullSData(oldp+167,(0x7c6U),12);
    bufp->fullSData(oldp+168,(0x7c7U),12);
    bufp->fullSData(oldp+169,(0x7c8U),12);
    bufp->fullSData(oldp+170,(0x7c9U),12);
    bufp->fullSData(oldp+171,(0x7caU),12);
    bufp->fullSData(oldp+172,(0x7cbU),12);
    bufp->fullSData(oldp+173,(0x7ccU),12);
    bufp->fullSData(oldp+174,(0x7cdU),12);
    bufp->fullSData(oldp+175,(0x7ceU),12);
    bufp->fullSData(oldp+176,(0x7cfU),12);
    bufp->fullSData(oldp+177,(0x7d0U),12);
    bufp->fullIData(oldp+178,(0x20U),32);
    bufp->fullIData(oldp+179,(0x10U),32);
    bufp->fullIData(oldp+180,(4U),32);
    bufp->fullQData(oldp+181,(0ULL),37);
    bufp->fullQData(oldp+183,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_mem[0]),37);
    bufp->fullQData(oldp+185,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_mem[1]),37);
    bufp->fullQData(oldp+187,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_mem[2]),37);
    bufp->fullQData(oldp+189,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_mem[3]),37);
    bufp->fullQData(oldp+191,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_mem[4]),37);
    bufp->fullQData(oldp+193,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_mem[5]),37);
    bufp->fullQData(oldp+195,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_mem[6]),37);
    bufp->fullQData(oldp+197,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_mem[7]),37);
    bufp->fullQData(oldp+199,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_mem[8]),37);
    bufp->fullQData(oldp+201,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_mem[9]),37);
    bufp->fullQData(oldp+203,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_mem[10]),37);
    bufp->fullQData(oldp+205,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_mem[11]),37);
    bufp->fullQData(oldp+207,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_mem[12]),37);
    bufp->fullQData(oldp+209,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_mem[13]),37);
    bufp->fullQData(oldp+211,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_mem[14]),37);
    bufp->fullQData(oldp+213,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_mem[15]),37);
    bufp->fullBit(oldp+215,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__sa_rsp_ready_comb));
    bufp->fullBit(oldp+216,(0U));
    bufp->fullBit(oldp+217,(1U));
    bufp->fullIData(oldp+218,(8U),32);
    bufp->fullIData(oldp+219,(0x10U),32);
    bufp->fullIData(oldp+220,(3U),32);
    bufp->fullCData(oldp+221,(1U),2);
    bufp->fullCData(oldp+222,(0xaU),8);
}

VL_ATTR_COLD void Vtb_e203_nice___024root__trace_full_0_sub_0(Vtb_e203_nice___024root* vlSelf, VerilatedVcd::Buffer* bufp);

VL_ATTR_COLD void Vtb_e203_nice___024root__trace_full_0(void* voidSelf, VerilatedVcd::Buffer* bufp) {
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_e203_nice___024root__trace_full_0\n"); );
    // Init
    Vtb_e203_nice___024root* const __restrict vlSelf VL_ATTR_UNUSED = static_cast<Vtb_e203_nice___024root*>(voidSelf);
    Vtb_e203_nice__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    // Body
    Vtb_e203_nice___024root__trace_full_0_sub_0((&vlSymsp->TOP), bufp);
}

VL_ATTR_COLD void Vtb_e203_nice___024root__trace_full_0_sub_0(Vtb_e203_nice___024root* vlSelf, VerilatedVcd::Buffer* bufp) {
    (void)vlSelf;  // Prevent unused variable warning
    Vtb_e203_nice__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    VL_DEBUG_IF(VL_DBG_MSGF("+    Vtb_e203_nice___024root__trace_full_0_sub_0\n"); );
    auto &vlSelfRef = std::ref(*vlSelf).get();
    // Init
    uint32_t* const oldp VL_ATTR_UNUSED = bufp->oldp(vlSymsp->__Vm_baseCode);
    // Body
    bufp->fullBit(oldp+1,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__calc_start));
    bufp->fullBit(oldp+2,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__retire_mem_holdup));
    bufp->fullBit(oldp+3,(((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__csr_buf_rd_valid) 
                           | (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__mma_buf_rd_valid))));
    bufp->fullIData(oldp+4,(((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__mma_buf_rd_valid)
                              ? ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__rd_sel)
                                  ? vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__wb_data_pong
                                  : vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__wb_data_ping)
                              : ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__rd_sel)
                                  ? vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__wb_data_pong
                                  : vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__wb_data_ping))),32);
    bufp->fullBit(oldp+5,(vlSelfRef.tb_e203_nice__DOT____Vcellout__u_nice_core__nice_icb_cmd_valid));
    bufp->fullIData(oldp+6,(((0xfffffffcU & vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_addr_comb) 
                             + VL_SHIFTL_III(32,32,32, (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_burst_cnt), 2U))),32);
    bufp->fullBit(oldp+7,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_is_read_comb));
    bufp->fullIData(oldp+8,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__wdata_aligned),32);
    bufp->fullCData(oldp+9,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__wmask_aligned),4);
    bufp->fullBit(oldp+10,(vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.icb_rsp_valid));
    bufp->fullBit(oldp+11,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__cfg_16bits_ia));
    bufp->fullBit(oldp+12,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__use_per_channel));
    bufp->fullIData(oldp+13,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__dst_base),32);
    bufp->fullBit(oldp+14,((0U == (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_mma_top__DOT__state))));
    bufp->fullIData(oldp+15,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_wdata),32);
    bufp->fullBit(oldp+16,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_req));
    bufp->fullBit(oldp+17,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__is_csr_read));
    bufp->fullSData(oldp+18,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_addr),12);
    bufp->fullBit(oldp+19,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_ready));
    bufp->fullIData(oldp+20,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_rdata),32);
    bufp->fullIData(oldp+21,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_lhs_base),32);
    bufp->fullIData(oldp+22,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_rhs_base),32);
    bufp->fullIData(oldp+23,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_dst_base),32);
    bufp->fullIData(oldp+24,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_bias_base),32);
    bufp->fullIData(oldp+25,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_lhs_zp),32);
    bufp->fullIData(oldp+26,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_rhs_zp),32);
    bufp->fullIData(oldp+27,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_dst_zp),32);
    bufp->fullIData(oldp+28,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_q_mult_pt),32);
    bufp->fullIData(oldp+29,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_q_shift_pt),32);
    bufp->fullIData(oldp+30,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_k),32);
    bufp->fullIData(oldp+31,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_n),32);
    bufp->fullIData(oldp+32,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_m),32);
    bufp->fullIData(oldp+33,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_lhs_row_stride_b),32);
    bufp->fullIData(oldp+34,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_dst_row_stride_b),32);
    bufp->fullIData(oldp+35,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_rhs_row_stride_b),32);
    bufp->fullIData(oldp+36,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_act_min),32);
    bufp->fullIData(oldp+37,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_csr_unit__DOT__csr_act_max),32);
    bufp->fullBit(oldp+38,((2U == (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_mma_top__DOT__state))));
    bufp->fullBit(oldp+39,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__mma_wb_ready));
    bufp->fullBit(oldp+40,((1U & (~ ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__wr_sel)
                                      ? (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__pong_full)
                                      : (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__ping_full))))));
    bufp->fullIData(oldp+41,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_wb_data),32);
    bufp->fullBit(oldp+42,((1U & (~ (((1U & ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_wptr) 
                                             >> 4U)) 
                                      != (1U & ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_rptr) 
                                                >> 4U))) 
                                     & ((0xfU & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_wptr)) 
                                        == (0xfU & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_rptr))))))));
    bufp->fullBit(oldp+43,(((~ (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_is_read_comb)) 
                            & ((0U != (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_state)) 
                               & (~ ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__is_last_burst) 
                                     & (0U != (3U & vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_addr_comb))))))));
    bufp->fullBit(oldp+44,(((IData)(vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.icb_rsp_valid) 
                            & (((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_is_read) 
                                & (((0U == (3U & vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_addr)) 
                                    & (0U == (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rsp_state))) 
                                   | (3U == (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rsp_state)))) 
                               | ((~ (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_is_read)) 
                                  & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rd_last_burst))))));
    bufp->fullIData(oldp+45,(((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_is_read_comb)
                               ? vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rdata_aligned
                               : 0U)),32);
    bufp->fullBit(oldp+46,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_ren));
    bufp->fullBit(oldp+47,((((1U & ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_wptr) 
                                    >> 4U)) != (1U 
                                                & ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_rptr) 
                                                   >> 4U))) 
                            & ((0xfU & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_wptr)) 
                               == (0xfU & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_rptr))))));
    bufp->fullBit(oldp+48,(((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_rptr) 
                            == (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_wptr))));
    bufp->fullQData(oldp+49,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_mem
                             [(0xfU & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_rptr))]),37);
    bufp->fullCData(oldp+51,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_wptr),5);
    bufp->fullCData(oldp+52,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_rptr),5);
    bufp->fullCData(oldp+53,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__burst_cycle_1start),5);
    bufp->fullCData(oldp+54,((3U & vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_addr_comb)),2);
    bufp->fullIData(oldp+55,((0xfffffffcU & vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_addr_comb)),32);
    bufp->fullBit(oldp+56,((0U != (3U & vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_addr_comb))));
    bufp->fullCData(oldp+57,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_burst_cnt),5);
    bufp->fullCData(oldp+58,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__burst_cnt_nxt),5);
    bufp->fullBit(oldp+59,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__fifo_is_read));
    bufp->fullIData(oldp+60,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__fifo_addr),32);
    bufp->fullCData(oldp+61,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__fifo_len),4);
    bufp->fullBit(oldp+62,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_is_read));
    bufp->fullIData(oldp+63,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_addr),32);
    bufp->fullCData(oldp+64,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_len_0start),4);
    bufp->fullCData(oldp+65,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rsp_burst_cnt),5);
    bufp->fullCData(oldp+66,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rsp_burst_cnt_nxt),5);
    bufp->fullIData(oldp+67,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__wdata_buf),32);
    bufp->fullCData(oldp+68,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__wmask_buf),4);
    bufp->fullBit(oldp+69,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__wdata_buf_valid));
    bufp->fullIData(oldp+70,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rdata_buf),32);
    bufp->fullBit(oldp+71,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rdata_buf_valid));
    bufp->fullIData(oldp+72,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rdata_aligned),32);
    bufp->fullCData(oldp+73,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_state),2);
    bufp->fullCData(oldp+74,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_state_nxt),2);
    bufp->fullCData(oldp+75,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rsp_state),2);
    bufp->fullCData(oldp+76,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rsp_state_nxt),2);
    bufp->fullBit(oldp+77,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fire));
    bufp->fullBit(oldp+78,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__is_last_burst));
    bufp->fullBit(oldp+79,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__rd_last_burst));
    bufp->fullBit(oldp+80,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__last_beat_sent));
    bufp->fullIData(oldp+81,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_addr_comb),32);
    bufp->fullCData(oldp+82,(((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cmd_fifo_ren)
                               ? (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__fifo_len)
                               : (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_len_0start))),4);
    bufp->fullBit(oldp+83,((0U != (3U & vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_addr))));
    bufp->fullCData(oldp+84,((0x1fU & ((IData)(1U) 
                                       + ((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_len_0start) 
                                          + (0U != 
                                             (3U & vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_addr)))))),5);
    bufp->fullBit(oldp+85,(((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_is_read_comb) 
                            & (IData)(vlSelfRef.tb_e203_nice__DOT____Vcellout__u_nice_core__nice_icb_cmd_valid))));
    bufp->fullBit(oldp+86,(((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT____VdfgRegularize_hc6488b08_0_5) 
                            & (IData)(vlSelfRef.tb_e203_nice__DOT____Vcellout__u_nice_core__nice_icb_cmd_valid))));
    bufp->fullCData(oldp+87,((0x1fU & VL_SHIFTL_III(5,5,32, 
                                                    (3U 
                                                     & vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_icb_bridge__DOT__cur_addr_comb), 3U))),5);
    bufp->fullBit(oldp+88,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_inst_tracker__DOT__state));
    bufp->fullBit(oldp+89,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_inst_tracker__DOT__wb_handshake));
    bufp->fullCData(oldp+90,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_mma_top__DOT__state),2);
    bufp->fullCData(oldp+91,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_mma_top__DOT__cycle_cnt),8);
    bufp->fullBit(oldp+92,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__csr_buf_rd_valid));
    bufp->fullIData(oldp+93,(((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__rd_sel)
                               ? vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__wb_data_pong
                               : vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__wb_data_ping)),32);
    bufp->fullBit(oldp+94,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__mma_buf_rd_valid));
    bufp->fullIData(oldp+95,(((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__rd_sel)
                               ? vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__wb_data_pong
                               : vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__wb_data_ping)),32);
    bufp->fullBit(oldp+96,(((~ (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__mma_buf_rd_valid)) 
                            & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__csr_buf_rd_valid))));
    bufp->fullIData(oldp+97,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__wb_data_ping),32);
    bufp->fullIData(oldp+98,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__wb_data_pong),32);
    bufp->fullBit(oldp+99,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__ping_full));
    bufp->fullBit(oldp+100,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__pong_full));
    bufp->fullBit(oldp+101,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__wr_sel));
    bufp->fullBit(oldp+102,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__rd_sel));
    bufp->fullBit(oldp+103,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__wr_hsked));
    bufp->fullIData(oldp+104,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__wb_data_ping),32);
    bufp->fullIData(oldp+105,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__wb_data_pong),32);
    bufp->fullBit(oldp+106,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__ping_full));
    bufp->fullBit(oldp+107,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__pong_full));
    bufp->fullBit(oldp+108,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__wr_sel));
    bufp->fullBit(oldp+109,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__rd_sel));
    bufp->fullBit(oldp+110,(((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_decode_dispatch__DOT__is_csr_inst)
                              ? (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__csr_ready)
                              : (0U == (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_mma_top__DOT__state)))));
    bufp->fullBit(oldp+111,(vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.icb_cmd_valid));
    bufp->fullIData(oldp+112,(vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.icb_cmd_addr),32);
    bufp->fullBit(oldp+113,(vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.icb_cmd_read));
    bufp->fullIData(oldp+114,(vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.icb_cmd_wdata),32);
    bufp->fullCData(oldp+115,(vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.icb_cmd_wmask),4);
    bufp->fullIData(oldp+116,(vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.req_inst),32);
    bufp->fullIData(oldp+117,(vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.req_rs1),32);
    bufp->fullIData(oldp+118,(vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.req_rs2),32);
    bufp->fullCData(oldp+119,((0x7fU & vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.req_inst)),7);
    bufp->fullCData(oldp+120,((7U & (vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.req_inst 
                                     >> 0xcU))),3);
    bufp->fullCData(oldp+121,((vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.req_inst 
                               >> 0x19U)),7);
    bufp->fullSData(oldp+122,((vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.req_inst 
                               >> 0x14U)),12);
    bufp->fullCData(oldp+123,((7U & vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.req_rs2)),3);
    bufp->fullCData(oldp+124,((3U & (vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.req_rs2 
                                     >> 3U))),2);
    bufp->fullCData(oldp+125,((3U & (vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.req_rs2 
                                     >> 5U))),2);
    bufp->fullCData(oldp+126,((3U & (vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.req_rs2 
                                     >> 7U))),2);
    bufp->fullBit(oldp+127,((1U & (vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.req_rs2 
                                   >> 9U))));
    bufp->fullBit(oldp+128,((2U == (3U & (vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.req_rs2 
                                          >> 7U)))));
    bufp->fullBit(oldp+129,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_decode_dispatch__DOT__is_mat_mult_t));
    bufp->fullBit(oldp+130,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_decode_dispatch__DOT__is_csr_wr));
    bufp->fullBit(oldp+131,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_decode_dispatch__DOT__is_csr_rd));
    bufp->fullBit(oldp+132,(((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_decode_dispatch__DOT__is_mat_mult_t) 
                             | (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_decode_dispatch__DOT__is_csr_inst))));
    bufp->fullBit(oldp+133,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_decode_dispatch__DOT__is_csr_inst));
    bufp->fullBit(oldp+134,(vlSelfRef.tb_e203_nice__DOT__clk));
    bufp->fullBit(oldp+135,(vlSelfRef.tb_e203_nice__DOT__rst_n));
    bufp->fullIData(oldp+136,(vlSelfRef.tb_e203_nice__DOT__send_csr_read__Vstatic__read_value),32);
    bufp->fullIData(oldp+137,(vlSelfRef.tb_e203_nice__DOT__test_response_backpressure__Vstatic__read_value),32);
    bufp->fullIData(oldp+138,(vlSelfRef.tb_e203_nice__DOT__test_request_backpressure__Vstatic__read_value),32);
    bufp->fullBit(oldp+139,(vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.req_valid));
    bufp->fullBit(oldp+140,(vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.rsp_ready));
    bufp->fullBit(oldp+141,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_decode_dispatch__DOT__inst_handshake));
    bufp->fullBit(oldp+142,((((~ (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__mma_buf_rd_valid)) 
                              & (IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__csr_buf_rd_valid)) 
                             & (IData)(vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.rsp_ready))));
    bufp->fullBit(oldp+143,(((IData)(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__mma_buf_rd_valid) 
                             & (IData)(vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.rsp_ready))));
    bufp->fullBit(oldp+144,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_csr_wb_pingpong_buf__DOT__rd_hsked));
    bufp->fullBit(oldp+145,(vlSelfRef.tb_e203_nice__DOT__u_nice_core__DOT__u_wbu__DOT__u_mma_wb_pingpong_buf__DOT__rd_hsked));
    bufp->fullBit(oldp+146,(vlSymsp->TOP__tb_e203_nice__DOT__nice_if_inst.icb_rsp_ready));
}
