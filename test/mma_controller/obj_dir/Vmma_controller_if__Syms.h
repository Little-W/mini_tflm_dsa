// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Symbol table internal header
//
// Internal details; most calling programs do not need this header,
// unless using verilator public meta comments.

#ifndef VERILATED_VMMA_CONTROLLER_IF__SYMS_H_
#define VERILATED_VMMA_CONTROLLER_IF__SYMS_H_  // guard

#include "verilated.h"
#include "verilated_vcd_c.h"

// INCLUDE MODEL CLASS

#include "Vmma_controller_if.h"

// INCLUDE MODULE CLASSES
#include "Vmma_controller_if___024root.h"
#include "Vmma_controller_if_ia_loader_if.h"
#include "Vmma_controller_if_weight_loader_if.h"
#include "Vmma_controller_if_bias_loader_if.h"
#include "Vmma_controller_if_requant_if.h"
#include "Vmma_controller_if_oa_writer_if.h"
#include "Vmma_controller_if_compute_core_if.h"
#include "Vmma_controller_if___024unit.h"
#include "Vmma_controller_if_control_if__R20.h"

// SYMS CLASS (contains all model state)
class alignas(VL_CACHE_LINE_BYTES)Vmma_controller_if__Syms final : public VerilatedSyms {
  public:
    // INTERNAL STATE
    Vmma_controller_if* const __Vm_modelp;
    bool __Vm_dumping = false;  // Dumping is active
    VerilatedMutex __Vm_dumperMutex;  // Protect __Vm_dumperp
    VerilatedVcdC* __Vm_dumperp VL_GUARDED_BY(__Vm_dumperMutex) = nullptr;  /// Trace class for $dump*
    bool __Vm_activity = false;  ///< Used by trace routines to determine change occurred
    uint32_t __Vm_baseCode = 0;  ///< Used by trace routines when tracing multiple models
    std::vector<VlEvent*> __Vm_triggeredEvents;
    VlDeleter __Vm_deleter;
    bool __Vm_didInit = false;

    // MODULE INSTANCE STATE
    Vmma_controller_if___024root   TOP;
    Vmma_controller_if_bias_loader_if TOP__tb_mma_controller__DOT__bias_if;
    Vmma_controller_if_compute_core_if TOP__tb_mma_controller__DOT__comp_if;
    Vmma_controller_if_control_if__R20 TOP__tb_mma_controller__DOT__ctrl_if;
    Vmma_controller_if_ia_loader_if TOP__tb_mma_controller__DOT__ia_if;
    Vmma_controller_if_oa_writer_if TOP__tb_mma_controller__DOT__oa_if;
    Vmma_controller_if_requant_if  TOP__tb_mma_controller__DOT__quant_if;
    Vmma_controller_if_weight_loader_if TOP__tb_mma_controller__DOT__weight_if;

    // CONSTRUCTORS
    Vmma_controller_if__Syms(VerilatedContext* contextp, const char* namep, Vmma_controller_if* modelp);
    ~Vmma_controller_if__Syms();

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
