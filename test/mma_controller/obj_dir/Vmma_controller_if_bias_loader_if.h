// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Design internal header
// See Vmma_controller_if.h for the primary calling header

#ifndef VERILATED_VMMA_CONTROLLER_IF_BIAS_LOADER_IF_H_
#define VERILATED_VMMA_CONTROLLER_IF_BIAS_LOADER_IF_H_  // guard

#include "verilated.h"
#include "verilated_timing.h"


class Vmma_controller_if__Syms;

class alignas(VL_CACHE_LINE_BYTES) Vmma_controller_if_bias_loader_if final : public VerilatedModule {
  public:

    // DESIGN SPECIFIC STATE
    VL_IN8(clk,0,0);
    CData/*0:0*/ load_bias_req;
    CData/*0:0*/ bias_valid;
    CData/*0:0*/ cb__DOT__bias_valid;
    CData/*0:0*/ cb__DOT__load_bias_req;
    CData/*0:0*/ __Vclocking_prev__cb__DOT__load_bias_req;
    CData/*0:0*/ __Vclocking_prev__cb__DOT__bias_valid;
    CData/*0:0*/ __Vintraval_hbfa2d195__0;
    CData/*0:0*/ __Vintraval_hcf882d00__0;
    VlEvent cb;

    // INTERNAL VARIABLES
    Vmma_controller_if__Syms* const vlSymsp;

    // CONSTRUCTORS
    Vmma_controller_if_bias_loader_if(Vmma_controller_if__Syms* symsp, const char* v__name);
    ~Vmma_controller_if_bias_loader_if();
    VL_UNCOPYABLE(Vmma_controller_if_bias_loader_if);

    // INTERNAL METHODS
    void __Vconfigure(bool first);
};

std::string VL_TO_STRING(const Vmma_controller_if_bias_loader_if* obj);

#endif  // guard
