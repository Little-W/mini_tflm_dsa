// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Design implementation internals
// See Vmma_controller_if.h for the primary calling header

#include "Vmma_controller_if__pch.h"
#include "Vmma_controller_if__Syms.h"
#include "Vmma_controller_if_requant_if.h"

void Vmma_controller_if_requant_if___ctor_var_reset(Vmma_controller_if_requant_if* vlSelf);

Vmma_controller_if_requant_if::Vmma_controller_if_requant_if(Vmma_controller_if__Syms* symsp, const char* v__name)
    : VerilatedModule{v__name}
    , vlSymsp{symsp}
 {
    // Reset structure values
    Vmma_controller_if_requant_if___ctor_var_reset(this);
}

void Vmma_controller_if_requant_if::__Vconfigure(bool first) {
    (void)first;  // Prevent unused variable warning
}

Vmma_controller_if_requant_if::~Vmma_controller_if_requant_if() {
}
