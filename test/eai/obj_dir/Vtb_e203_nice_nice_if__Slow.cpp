// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Design implementation internals
// See Vtb_e203_nice.h for the primary calling header

#include "Vtb_e203_nice__pch.h"
#include "Vtb_e203_nice__Syms.h"
#include "Vtb_e203_nice_nice_if.h"

void Vtb_e203_nice_nice_if___ctor_var_reset(Vtb_e203_nice_nice_if* vlSelf);

Vtb_e203_nice_nice_if::Vtb_e203_nice_nice_if(Vtb_e203_nice__Syms* symsp, const char* v__name)
    : VerilatedModule{v__name}
    , vlSymsp{symsp}
 {
    // Reset structure values
    Vtb_e203_nice_nice_if___ctor_var_reset(this);
}

void Vtb_e203_nice_nice_if::__Vconfigure(bool first) {
    (void)first;  // Prevent unused variable warning
}

Vtb_e203_nice_nice_if::~Vtb_e203_nice_nice_if() {
}
