// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Symbol table internal header
//
// Internal details; most calling programs do not need this header,
// unless using verilator public meta comments.

#ifndef VERILATED_VTB_E203_NICE__SYMS_H_
#define VERILATED_VTB_E203_NICE__SYMS_H_  // guard

#include "verilated.h"
#include "verilated_vcd_c.h"

// INCLUDE MODEL CLASS

#include "Vtb_e203_nice.h"

// INCLUDE MODULE CLASSES
#include "Vtb_e203_nice___024root.h"
#include "Vtb_e203_nice___024unit.h"
#include "Vtb_e203_nice_nice_if.h"

// SYMS CLASS (contains all model state)
class alignas(VL_CACHE_LINE_BYTES)Vtb_e203_nice__Syms final : public VerilatedSyms {
  public:
    // INTERNAL STATE
    Vtb_e203_nice* const __Vm_modelp;
    bool __Vm_dumping = false;  // Dumping is active
    VerilatedMutex __Vm_dumperMutex;  // Protect __Vm_dumperp
    VerilatedVcdC* __Vm_dumperp VL_GUARDED_BY(__Vm_dumperMutex) = nullptr;  /// Trace class for $dump*
    bool __Vm_activity = false;  ///< Used by trace routines to determine change occurred
    uint32_t __Vm_baseCode = 0;  ///< Used by trace routines when tracing multiple models
    std::vector<VlEvent*> __Vm_triggeredEvents;
    VlDeleter __Vm_deleter;
    bool __Vm_didInit = false;

    // MODULE INSTANCE STATE
    Vtb_e203_nice___024root        TOP;
    Vtb_e203_nice_nice_if          TOP__tb_e203_nice__DOT__nice_if_inst;

    // SCOPE NAMES
    VerilatedScope __Vscope_tb_e203_nice;
    VerilatedScope __Vscope_tb_e203_nice__send_csr_read;

    // CONSTRUCTORS
    Vtb_e203_nice__Syms(VerilatedContext* contextp, const char* namep, Vtb_e203_nice* modelp);
    ~Vtb_e203_nice__Syms();

    // METHODS
    const char* name() { return TOP.name(); }
    void enqueueTriggeredEventForClearing(VlEvent& event) {
#ifdef VL_DEBUG
        if (VL_UNLIKELY(!event.isTriggered())) {
            VL_FATAL_MT(__FILE__, __LINE__, __FILE__, "event passed to 'enqueueTriggeredEventForClearing' was not triggered");
        }
#endif
        __Vm_triggeredEvents.push_back(&event);
    }
    void clearTriggeredEvents() {
        for (const auto eventp : __Vm_triggeredEvents) eventp->clearTriggered();
        __Vm_triggeredEvents.clear();
    }
    void _traceDump();
    void _traceDumpOpen();
    void _traceDumpClose();
};

#endif  // guard
