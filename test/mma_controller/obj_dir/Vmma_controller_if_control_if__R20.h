// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Design internal header
// See Vmma_controller_if.h for the primary calling header

#ifndef VERILATED_VMMA_CONTROLLER_IF_CONTROL_IF__R20_H_
#define VERILATED_VMMA_CONTROLLER_IF_CONTROL_IF__R20_H_  // guard

#include "verilated.h"
#include "verilated_timing.h"


class Vmma_controller_if__Syms;

class alignas(VL_CACHE_LINE_BYTES) Vmma_controller_if_control_if__R20 final : public VerilatedModule {
  public:

    // DESIGN SPECIFIC STATE
    VL_IN8(clk,0,0);
    CData/*0:0*/ calc_start;
    CData/*0:0*/ cfg_16bits_ia;
    CData/*0:0*/ fifo_full_flag;
    CData/*0:0*/ cb__DOT__fifo_full_flag;
    CData/*0:0*/ cb__DOT__cfg_16bits_ia;
    CData/*0:0*/ cb__DOT__calc_start;
    CData/*0:0*/ __Vclocking_prev__cb__DOT__calc_start;
    CData/*0:0*/ __Vclocking_prev__cb__DOT__cfg_16bits_ia;
    CData/*0:0*/ __Vclocking_prev__cb__DOT__fifo_full_flag;
    CData/*0:0*/ __Vintraval_h9028ce99__0;
    CData/*0:0*/ __Vintraval_h10c76d9d__0;
    CData/*0:0*/ __Vintraval_h56cfd7c8__0;
    VlEvent cb;

    // INTERNAL VARIABLES
    Vmma_controller_if__Syms* const vlSymsp;

    // CONSTRUCTORS
    Vmma_controller_if_control_if__R20(Vmma_controller_if__Syms* symsp, const char* v__name);
    ~Vmma_controller_if_control_if__R20();
    VL_UNCOPYABLE(Vmma_controller_if_control_if__R20);

    // INTERNAL METHODS
    void __Vconfigure(bool first);
};

std::string VL_TO_STRING(const Vmma_controller_if_control_if__R20* obj);

#endif  // guard
