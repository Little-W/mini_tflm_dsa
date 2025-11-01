// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Design internal header
// See Vtb_e203_nice.h for the primary calling header

#ifndef VERILATED_VTB_E203_NICE___024UNIT_H_
#define VERILATED_VTB_E203_NICE___024UNIT_H_  // guard

#include "verilated.h"
#include "verilated_timing.h"


class Vtb_e203_nice__Syms;

class alignas(VL_CACHE_LINE_BYTES) Vtb_e203_nice___024unit final : public VerilatedModule {
  public:

    // INTERNAL VARIABLES
    Vtb_e203_nice__Syms* const vlSymsp;

    // CONSTRUCTORS
    Vtb_e203_nice___024unit(Vtb_e203_nice__Syms* symsp, const char* v__name);
    ~Vtb_e203_nice___024unit();
    VL_UNCOPYABLE(Vtb_e203_nice___024unit);

    // INTERNAL METHODS
    void __Vconfigure(bool first);
};


#endif  // guard
