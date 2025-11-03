// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Design internal header
// See Vtb_compute_core.h for the primary calling header

#ifndef VERILATED_VTB_COMPUTE_CORE_TB_COMPUTE_CORE_IF_H_
#define VERILATED_VTB_COMPUTE_CORE_TB_COMPUTE_CORE_IF_H_  // guard

#include "verilated.h"
#include "verilated_timing.h"


class Vtb_compute_core__Syms;

class alignas(VL_CACHE_LINE_BYTES) Vtb_compute_core_tb_compute_core_if final : public VerilatedModule {
  public:

    // DESIGN SPECIFIC STATE
    VL_IN8(clk,0,0);
    CData/*0:0*/ store_weight_req;
    CData/*0:0*/ ia_row_valid;
    CData/*0:0*/ ia_calc_done;
    CData/*0:0*/ ia_is_init_data;
    CData/*0:0*/ cb__DOT__ia_is_init_data;
    CData/*0:0*/ cb__DOT__ia_calc_done;
    CData/*0:0*/ cb__DOT__ia_row_valid;
    CData/*0:0*/ cb__DOT__store_weight_req;
    CData/*0:0*/ __Vclocking_prev__cb__DOT__store_weight_req;
    CData/*0:0*/ __Vclocking_prev__cb__DOT__ia_row_valid;
    CData/*0:0*/ __Vclocking_prev__cb__DOT__ia_calc_done;
    CData/*0:0*/ __Vclocking_prev__cb__DOT__ia_is_init_data;
    VlUnpacked<CData/*7:0*/, 4> weight_in;
    VlUnpacked<SData/*15:0*/, 4> ia_vec_in;
    VlUnpacked<IData/*31:0*/, 4> bias_in;
    VlUnpacked<IData/*31:0*/, 4> acc_data_out;
    VlUnpacked<IData/*31:0*/, 4> cb__DOT__bias_in;
    VlUnpacked<SData/*15:0*/, 4> cb__DOT__ia_vec_in;
    VlUnpacked<CData/*7:0*/, 4> cb__DOT__weight_in;
    VlUnpacked<CData/*7:0*/, 4> __Vclocking_prev__cb__DOT__weight_in;
    VlUnpacked<SData/*15:0*/, 4> __Vclocking_prev__cb__DOT__ia_vec_in;
    VlUnpacked<IData/*31:0*/, 4> __Vclocking_prev__cb__DOT__bias_in;
    VlEvent cb;

    // INTERNAL VARIABLES
    Vtb_compute_core__Syms* const vlSymsp;

    // CONSTRUCTORS
    Vtb_compute_core_tb_compute_core_if(Vtb_compute_core__Syms* symsp, const char* v__name);
    ~Vtb_compute_core_tb_compute_core_if();
    VL_UNCOPYABLE(Vtb_compute_core_tb_compute_core_if);

    // INTERNAL METHODS
    void __Vconfigure(bool first);
};

std::string VL_TO_STRING(const Vtb_compute_core_tb_compute_core_if* obj);

#endif  // guard
