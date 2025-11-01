// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Symbol table implementation internals

#include "Vtb_e203_nice__pch.h"
#include "Vtb_e203_nice.h"
#include "Vtb_e203_nice___024root.h"
#include "Vtb_e203_nice___024unit.h"
#include "Vtb_e203_nice_nice_if.h"

// FUNCTIONS
Vtb_e203_nice__Syms::~Vtb_e203_nice__Syms()
{
#ifdef VM_TRACE
    if (__Vm_dumping) _traceDumpClose();
#endif  // VM_TRACE
}

void Vtb_e203_nice__Syms::_traceDump() {
    const VerilatedLockGuard lock(__Vm_dumperMutex);
    __Vm_dumperp->dump(VL_TIME_Q());
}

void Vtb_e203_nice__Syms::_traceDumpOpen() {
    const VerilatedLockGuard lock(__Vm_dumperMutex);
    if (VL_UNLIKELY(!__Vm_dumperp)) {
        __Vm_dumperp = new VerilatedVcdC();
        __Vm_modelp->trace(__Vm_dumperp, 0, 0);
        std::string dumpfile = _vm_contextp__->dumpfileCheck();
        __Vm_dumperp->open(dumpfile.c_str());
        __Vm_dumping = true;
    }
}

void Vtb_e203_nice__Syms::_traceDumpClose() {
    const VerilatedLockGuard lock(__Vm_dumperMutex);
    __Vm_dumping = false;
    VL_DO_CLEAR(delete __Vm_dumperp, __Vm_dumperp = nullptr);
}

Vtb_e203_nice__Syms::Vtb_e203_nice__Syms(VerilatedContext* contextp, const char* namep, Vtb_e203_nice* modelp)
    : VerilatedSyms{contextp}
    // Setup internal state of the Syms class
    , __Vm_modelp{modelp}
    // Setup module instances
    , TOP{this, namep}
    , TOP__tb_e203_nice__DOT__nice_if_inst{this, Verilated::catName(namep, "tb_e203_nice.nice_if_inst")}
{
        // Check resources
        Verilated::stackCheck(76);
    // Configure time unit / time precision
    _vm_contextp__->timeunit(-9);
    _vm_contextp__->timeprecision(-12);
    // Setup each module's pointers to their submodules
    TOP.__PVT__tb_e203_nice__DOT__nice_if_inst = &TOP__tb_e203_nice__DOT__nice_if_inst;
    // Setup each module's pointer back to symbol table (for public functions)
    TOP.__Vconfigure(true);
    TOP__tb_e203_nice__DOT__nice_if_inst.__Vconfigure(true);
    // Setup scopes
    __Vscope_tb_e203_nice.configure(this, name(), "tb_e203_nice", "tb_e203_nice", -9, VerilatedScope::SCOPE_OTHER);
    __Vscope_tb_e203_nice__send_csr_read.configure(this, name(), "tb_e203_nice.send_csr_read", "send_csr_read", -9, VerilatedScope::SCOPE_OTHER);
}
