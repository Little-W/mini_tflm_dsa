// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Symbol table implementation internals

#include "Vmma_controller_if__pch.h"
#include "Vmma_controller_if.h"
#include "Vmma_controller_if___024root.h"
#include "Vmma_controller_if_ia_loader_if.h"
#include "Vmma_controller_if_weight_loader_if.h"
#include "Vmma_controller_if_bias_loader_if.h"
#include "Vmma_controller_if_requant_if.h"
#include "Vmma_controller_if_oa_writer_if.h"
#include "Vmma_controller_if_compute_core_if.h"
#include "Vmma_controller_if___024unit.h"
#include "Vmma_controller_if_control_if__R20.h"

// FUNCTIONS
Vmma_controller_if__Syms::~Vmma_controller_if__Syms()
{
#ifdef VM_TRACE
    if (__Vm_dumping) _traceDumpClose();
#endif  // VM_TRACE
}

void Vmma_controller_if__Syms::_traceDump() {
    const VerilatedLockGuard lock(__Vm_dumperMutex);
    __Vm_dumperp->dump(VL_TIME_Q());
}

void Vmma_controller_if__Syms::_traceDumpOpen() {
    const VerilatedLockGuard lock(__Vm_dumperMutex);
    if (VL_UNLIKELY(!__Vm_dumperp)) {
        __Vm_dumperp = new VerilatedVcdC();
        __Vm_modelp->trace(__Vm_dumperp, 0, 0);
        std::string dumpfile = _vm_contextp__->dumpfileCheck();
        __Vm_dumperp->open(dumpfile.c_str());
        __Vm_dumping = true;
    }
}

void Vmma_controller_if__Syms::_traceDumpClose() {
    const VerilatedLockGuard lock(__Vm_dumperMutex);
    __Vm_dumping = false;
    VL_DO_CLEAR(delete __Vm_dumperp, __Vm_dumperp = nullptr);
}

Vmma_controller_if__Syms::Vmma_controller_if__Syms(VerilatedContext* contextp, const char* namep, Vmma_controller_if* modelp)
    : VerilatedSyms{contextp}
    // Setup internal state of the Syms class
    , __Vm_modelp{modelp}
    // Setup module instances
    , TOP{this, namep}
    , TOP__tb_mma_controller__DOT__bias_if{this, Verilated::catName(namep, "tb_mma_controller.bias_if")}
    , TOP__tb_mma_controller__DOT__comp_if{this, Verilated::catName(namep, "tb_mma_controller.comp_if")}
    , TOP__tb_mma_controller__DOT__ctrl_if{this, Verilated::catName(namep, "tb_mma_controller.ctrl_if")}
    , TOP__tb_mma_controller__DOT__ia_if{this, Verilated::catName(namep, "tb_mma_controller.ia_if")}
    , TOP__tb_mma_controller__DOT__oa_if{this, Verilated::catName(namep, "tb_mma_controller.oa_if")}
    , TOP__tb_mma_controller__DOT__quant_if{this, Verilated::catName(namep, "tb_mma_controller.quant_if")}
    , TOP__tb_mma_controller__DOT__weight_if{this, Verilated::catName(namep, "tb_mma_controller.weight_if")}
{
        // Check resources
        Verilated::stackCheck(157);
    // Configure time unit / time precision
    _vm_contextp__->timeunit(-9);
    _vm_contextp__->timeprecision(-12);
    // Setup each module's pointers to their submodules
    TOP.__PVT__tb_mma_controller__DOT__bias_if = &TOP__tb_mma_controller__DOT__bias_if;
    TOP.__PVT__tb_mma_controller__DOT__comp_if = &TOP__tb_mma_controller__DOT__comp_if;
    TOP.__PVT__tb_mma_controller__DOT__ctrl_if = &TOP__tb_mma_controller__DOT__ctrl_if;
    TOP.__PVT__tb_mma_controller__DOT__ia_if = &TOP__tb_mma_controller__DOT__ia_if;
    TOP.__PVT__tb_mma_controller__DOT__oa_if = &TOP__tb_mma_controller__DOT__oa_if;
    TOP.__PVT__tb_mma_controller__DOT__quant_if = &TOP__tb_mma_controller__DOT__quant_if;
    TOP.__PVT__tb_mma_controller__DOT__weight_if = &TOP__tb_mma_controller__DOT__weight_if;
    // Setup each module's pointer back to symbol table (for public functions)
    TOP.__Vconfigure(true);
    TOP__tb_mma_controller__DOT__bias_if.__Vconfigure(true);
    TOP__tb_mma_controller__DOT__comp_if.__Vconfigure(true);
    TOP__tb_mma_controller__DOT__ctrl_if.__Vconfigure(true);
    TOP__tb_mma_controller__DOT__ia_if.__Vconfigure(true);
    TOP__tb_mma_controller__DOT__oa_if.__Vconfigure(true);
    TOP__tb_mma_controller__DOT__quant_if.__Vconfigure(true);
    TOP__tb_mma_controller__DOT__weight_if.__Vconfigure(true);
}
