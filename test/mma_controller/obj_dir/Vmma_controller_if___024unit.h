// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Design internal header
// See Vmma_controller_if.h for the primary calling header

#ifndef VERILATED_VMMA_CONTROLLER_IF___024UNIT_H_
#define VERILATED_VMMA_CONTROLLER_IF___024UNIT_H_  // guard

#include "verilated.h"
#include "verilated_timing.h"


class Vmma_controller_if__Syms;

class alignas(VL_CACHE_LINE_BYTES) Vmma_controller_if___024unit final : public VerilatedModule {
  public:

    // INTERNAL VARIABLES
    Vmma_controller_if__Syms* const vlSymsp;

    // CONSTRUCTORS
    Vmma_controller_if___024unit(Vmma_controller_if__Syms* symsp, const char* v__name);
    ~Vmma_controller_if___024unit();
    VL_UNCOPYABLE(Vmma_controller_if___024unit);

    // INTERNAL METHODS
    void __Vconfigure(bool first);
};


#endif  // guard
