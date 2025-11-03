// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Design implementation internals
// See Vtb_compute_core.h for the primary calling header

#include "Vtb_compute_core__pch.h"
#include "Vtb_compute_core__Syms.h"
#include "Vtb_compute_core_tb_compute_core_if.h"

void Vtb_compute_core_tb_compute_core_if___ctor_var_reset(Vtb_compute_core_tb_compute_core_if* vlSelf);

Vtb_compute_core_tb_compute_core_if::Vtb_compute_core_tb_compute_core_if(Vtb_compute_core__Syms* symsp, const char* v__name)
    : VerilatedModule{v__name}
    , vlSymsp{symsp}
 {
    // Reset structure values
    Vtb_compute_core_tb_compute_core_if___ctor_var_reset(this);
}

void Vtb_compute_core_tb_compute_core_if::__Vconfigure(bool first) {
    (void)first;  // Prevent unused variable warning
}

Vtb_compute_core_tb_compute_core_if::~Vtb_compute_core_tb_compute_core_if() {
}
