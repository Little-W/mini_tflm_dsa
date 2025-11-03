// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Design internal header
// See Vmma_controller_if.h for the primary calling header

#ifndef VERILATED_VMMA_CONTROLLER_IF_WEIGHT_LOADER_IF_H_
#define VERILATED_VMMA_CONTROLLER_IF_WEIGHT_LOADER_IF_H_  // guard

#include "verilated.h"
#include "verilated_timing.h"


class Vmma_controller_if__Syms;

class alignas(VL_CACHE_LINE_BYTES) Vmma_controller_if_weight_loader_if final : public VerilatedModule {
  public:

    // DESIGN SPECIFIC STATE
    VL_IN8(clk,0,0);
    CData/*0:0*/ load_weight_req;
    CData/*0:0*/ weight_sending_done;
    CData/*0:0*/ weight_data_valid;
    CData/*0:0*/ cb__DOT__weight_data_valid;
    CData/*0:0*/ cb__DOT__weight_sending_done;
    CData/*0:0*/ cb__DOT__load_weight_req;
    CData/*0:0*/ __Vclocking_prev__cb__DOT__load_weight_req;
    CData/*0:0*/ __Vclocking_prev__cb__DOT__weight_sending_done;
    CData/*0:0*/ __Vclocking_prev__cb__DOT__weight_data_valid;
    CData/*0:0*/ __Vintraval_h33b037ac__0;
    CData/*0:0*/ __Vintraval_hbff9f8db__0;
    CData/*0:0*/ __Vintraval_h995cdc00__0;
    VlEvent cb;

    // INTERNAL VARIABLES
    Vmma_controller_if__Syms* const vlSymsp;

    // CONSTRUCTORS
    Vmma_controller_if_weight_loader_if(Vmma_controller_if__Syms* symsp, const char* v__name);
    ~Vmma_controller_if_weight_loader_if();
    VL_UNCOPYABLE(Vmma_controller_if_weight_loader_if);

    // INTERNAL METHODS
    void __Vconfigure(bool first);
};

std::string VL_TO_STRING(const Vmma_controller_if_weight_loader_if* obj);

#endif  // guard
