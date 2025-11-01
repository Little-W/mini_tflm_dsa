// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Design internal header
// See Vtb_e203_nice.h for the primary calling header

#ifndef VERILATED_VTB_E203_NICE_NICE_IF_H_
#define VERILATED_VTB_E203_NICE_NICE_IF_H_  // guard

#include "verilated.h"
#include "verilated_timing.h"


class Vtb_e203_nice__Syms;

class alignas(VL_CACHE_LINE_BYTES) Vtb_e203_nice_nice_if final : public VerilatedModule {
  public:

    // DESIGN SPECIFIC STATE
    VL_IN8(clk,0,0);
    VL_IN8(rst_n,0,0);
    CData/*0:0*/ req_valid;
    CData/*0:0*/ rsp_ready;
    CData/*0:0*/ icb_cmd_valid;
    CData/*0:0*/ icb_cmd_read;
    CData/*3:0*/ icb_cmd_wmask;
    CData/*0:0*/ icb_rsp_valid;
    CData/*0:0*/ icb_rsp_ready;
    CData/*0:0*/ cb__DOT__icb_rsp_ready;
    CData/*3:0*/ cb__DOT__icb_cmd_wmask;
    CData/*0:0*/ cb__DOT__icb_cmd_read;
    CData/*0:0*/ cb__DOT__icb_cmd_valid;
    CData/*0:0*/ cb__DOT__rsp_ready;
    CData/*0:0*/ cb__DOT__req_valid;
    CData/*0:0*/ __Vclocking_prev__cb__DOT__req_valid;
    CData/*0:0*/ __Vclocking_prev__cb__DOT__rsp_ready;
    CData/*0:0*/ __Vclocking_prev__cb__DOT__icb_cmd_valid;
    CData/*0:0*/ __Vclocking_prev__cb__DOT__icb_cmd_read;
    CData/*3:0*/ __Vclocking_prev__cb__DOT__icb_cmd_wmask;
    CData/*0:0*/ __Vclocking_prev__cb__DOT__icb_rsp_ready;
    IData/*31:0*/ req_inst;
    IData/*31:0*/ req_rs1;
    IData/*31:0*/ req_rs2;
    IData/*31:0*/ icb_cmd_addr;
    IData/*31:0*/ icb_cmd_wdata;
    IData/*31:0*/ cb__DOT__icb_cmd_wdata;
    IData/*31:0*/ cb__DOT__icb_cmd_addr;
    IData/*31:0*/ cb__DOT__req_rs2;
    IData/*31:0*/ cb__DOT__req_rs1;
    IData/*31:0*/ cb__DOT__req_inst;
    IData/*31:0*/ __Vclocking_prev__cb__DOT__req_inst;
    IData/*31:0*/ __Vclocking_prev__cb__DOT__req_rs1;
    IData/*31:0*/ __Vclocking_prev__cb__DOT__req_rs2;
    IData/*31:0*/ __Vclocking_prev__cb__DOT__icb_cmd_addr;
    IData/*31:0*/ __Vclocking_prev__cb__DOT__icb_cmd_wdata;
    VlEvent cb;

    // INTERNAL VARIABLES
    Vtb_e203_nice__Syms* const vlSymsp;

    // CONSTRUCTORS
    Vtb_e203_nice_nice_if(Vtb_e203_nice__Syms* symsp, const char* v__name);
    ~Vtb_e203_nice_nice_if();
    VL_UNCOPYABLE(Vtb_e203_nice_nice_if);

    // INTERNAL METHODS
    void __Vconfigure(bool first);
};

std::string VL_TO_STRING(const Vtb_e203_nice_nice_if* obj);

#endif  // guard
